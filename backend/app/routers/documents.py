"""Document management endpoints (T04, T07-T11).

Flow (roadmap §4.3): verify admin permission → validate file type and size →
extract → chunk → embed/index into ChromaDB with role-flag metadata (T07-T09)
→ return record. ``GET /documents`` lists only role-accessible documents and
``PUT /documents/{id}`` replaces a document plus its indexed chunks (T11).
"""

import logging
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import SUPPORTED_FILE_EXTENSIONS, get_settings
from backend.app.chunking import Chunk, chunk_document
from backend.app.database import get_db
from backend.app.models import Document, ROLES, User
from backend.app.parsing import extract_text
from backend.app.schemas import (
    DocumentPublic,
    DocumentReplaceResponse,
    DocumentUploadResponse,
)
from backend.app.security import get_current_user
from backend.app.vector_store import get_vector_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

_MIME_ALIASES = {
    "application/pdf": "pdf",
    "application/x-pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Dependency: only users with the administrator permission pass (FR02)."""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator permission required",
        )
    return current_user


def _file_type_for(filename: str, content_type: str | None) -> str:
    """Derive the canonical file type from extension, cross-checking MIME."""
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_FILE_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type {extension or '(none)'}; "
            f"allowed: {', '.join(SUPPORTED_FILE_EXTENSIONS)}",
        )
    detected = "pdf" if extension == ".pdf" else "docx"
    if content_type:
        mime_type = _MIME_ALIASES.get(content_type.split(";")[0].strip().lower())
        if mime_type is not None and mime_type != detected:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File content ({content_type}) does not match extension ({detected})",
            )
    return detected


def _check_declared_size(upload: UploadFile, max_bytes: int) -> None:
    """Reject uploads whose declared size exceeds the limit (fast path)."""
    if upload.size is not None and upload.size > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {max_bytes // (1024 * 1024)} MB upload limit",
        )


def _validate_roles(allowed_roles: str) -> list[str]:
    """Shared role-list validation for upload and replace (FR02)."""
    requested_roles = [r.strip().lower() for r in allowed_roles.split(",") if r.strip()]
    invalid = [r for r in requested_roles if r not in ROLES]
    if not requested_roles or invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"allowed_roles must be a non-empty comma-separated list of "
            f"{', '.join(ROLES)}"
            + (f"; invalid: {', '.join(invalid)}" if invalid else ""),
        )
    return requested_roles


def _ingest_file(
    db: Session,
    file: UploadFile,
    document: Document,
    requested_roles: list[str],
    staged_files: list[Path],
) -> tuple[list[Chunk], list[str]]:
    """Stage a unique file and prepare chunks; the caller owns rollback."""
    settings = get_settings()

    # --- Validate file type (extension + MIME cross-check) and size ---
    detected_type = _file_type_for(file.filename or "", file.content_type)
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    _check_declared_size(file, max_bytes)

    # --- Read with a hard cap so oversize payloads cannot exhaust memory ---
    data = file.file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {settings.max_upload_size_mb} MB upload limit",
        )
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")

    # --- Update record fields and persist the file (roadmap §8) ---
    document.document_name = Path(file.filename or "unnamed").name
    document.file_type = detected_type
    document.file_size = len(data)
    document.allowed_employee = "employee" in requested_roles
    document.allowed_hr = "hr" in requested_roles
    document.allowed_manager = "manager" in requested_roles
    db.flush()  # assign document.id for the storage path

    uploads_dir = Path(settings.upload_dir)
    uploads_dir.mkdir(parents=True, exist_ok=True)
    target = uploads_dir / f"doc_{document.id}_{uuid4().hex}.{detected_type}"
    staged_files.append(target)
    document.file_path = str(target)
    target.write_bytes(data)
    db.flush()

    # --- Extract (T05) and chunk (T06) ---
    try:
        extracted = extract_text(target, detected_type)
    except Exception as exc:  # Malformed documents raise parser-specific errors.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The file could not be parsed; it may be corrupt, "
            "password-protected, or not a real PDF/DOCX document",
        ) from exc
    if not extracted.body_text.strip():
        # Titles alone (e.g. auto "Page 1" headings from blank/scanned pages)
        # are not readable content; such a document would be indexed with
        # zero chunks, so reject it as unreadable (T05 / FR02).
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="No readable text could be extracted from the document",
        )
    document.content = extracted.text

    chunks = chunk_document(
        [(s.title, s.text) for s in extracted.sections if s.text],
        document_id=f"DOC_{document.id:03d}",
        document_name=document.document_name,
        allowed_roles=requested_roles,
    )
    return chunks, extracted.section_titles


def _save_document(
    db: Session,
    file: UploadFile,
    document: Document,
    requested_roles: list[str],
    *,
    replacing: bool = False,
) -> tuple[DocumentPublic, int, list[str]]:
    """Compensate file/index writes if ingestion or the SQL commit fails.

    SQLite's write transaction (acquired by flush) serializes ingestions.
    Snapshots include embeddings so recovery does not need the embedding model.
    """
    old_path = document.file_path if replacing else ""
    store = None
    snapshot = None
    changed_index = False
    doc_key = None
    staged_files: list[Path] = []
    try:
        chunks, sections = _ingest_file(db, file, document, requested_roles, staged_files)
        store = get_vector_store()
        doc_key = f"DOC_{document.id:03d}"
        if replacing:
            snapshot = store.get_document_chunks(doc_key)
        changed_index = True
        store.delete_document_chunks(doc_key)
        indexed = store.index_chunks(chunks)
        public = _to_public(document)
        db.commit()
    except Exception:
        try:
            if changed_index:
                store.delete_document_chunks(doc_key)
                if snapshot is not None:
                    store.restore_chunks(snapshot)
        finally:
            db.rollback()
            for staged_path in staged_files:
                staged_path.unlink(missing_ok=True)
        raise
    if old_path and old_path != document.file_path:
        try:
            Path(old_path).unlink(missing_ok=True)
        except OSError:
            logger.exception("Could not remove superseded file %s", old_path)
    return public, indexed, sections


@router.post("/upload", response_model=DocumentUploadResponse)
def upload_document(
    file: UploadFile = File(...),
    allowed_roles: str = Form(..., description="Comma-separated roles, e.g. 'hr,manager'"),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> DocumentUploadResponse:
    """Upload a PDF/DOCX as an administrator; extracts, chunks and indexes it."""
    requested_roles = _validate_roles(allowed_roles)

    document = Document(
        document_name=Path(file.filename or "unnamed").name,
        file_path="",
        file_type="",
        file_size=0,
        allowed_employee=False,
        allowed_hr=False,
        allowed_manager=False,
    )
    db.add(document)
    public, indexed, sections = _save_document(db, file, document, requested_roles)
    return DocumentUploadResponse(
        document=public,
        chunk_count=indexed,
        sections=sections,
    )


@router.get("", response_model=list[DocumentPublic])
def list_documents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DocumentPublic]:
    """List only documents the current user's role may access (FR03).

    The role comes from the authenticated session, never from the request.
    """
    role = current_user.role
    if role not in ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Unknown role {role!r}")
    documents = db.scalars(
        select(Document)
        .where(Document.is_active.is_(True), getattr(Document, f"allowed_{role}").is_(True))
        .order_by(Document.id)
    ).all()
    return [_to_public(d) for d in documents]


@router.get("/search")
def search_documents(
    query: str = Query(..., min_length=1, max_length=2000),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """Search with the current database role, never a client-supplied role."""
    if current_user.role not in ROLES:
        raise HTTPException(status_code=403, detail="Unknown role")
    if not query.strip():
        raise HTTPException(status_code=422, detail="Query must not be blank")
    return get_vector_store().search(query, current_user.role)


@router.put("/{document_id}", response_model=DocumentReplaceResponse)
def replace_document(
    document_id: int,
    file: UploadFile = File(...),
    allowed_roles: str = Form(..., description="Comma-separated roles, e.g. 'hr,manager'"),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> DocumentReplaceResponse:
    """Replace a document and its indexed content (T11 / FR08).

    Removes the old indexed chunks first (roadmap risk mitigation: outdated
    content must not surface after replacement), then indexes the replacement
    and updates the document record.
    """
    document = db.get(Document, document_id)
    if document is None or not document.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    requested_roles = _validate_roles(allowed_roles)

    public, indexed, sections = _save_document(
        db, file, document, requested_roles, replacing=True
    )

    return DocumentReplaceResponse(
        document=public,
        chunk_count=indexed,
        sections=sections,
    )


def _to_public(document: Document) -> DocumentPublic:
    return DocumentPublic(
        id=document.id,
        document_name=document.document_name,
        file_type=document.file_type,
        file_size=document.file_size,
        allowed_roles=document.allowed_roles(),
        uploaded_at=document.uploaded_at.isoformat(),
    )