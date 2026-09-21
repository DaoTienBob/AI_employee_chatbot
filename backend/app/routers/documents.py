"""Document management endpoints (T04): admin-protected upload.

Flow (roadmap §4.3): verify admin permission → validate file type and size →
extract → chunk → return record. Embedding/indexing into ChromaDB lands on
Day 3 (T08); the SQLite record and file are stored here already.
"""

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from backend.app.config import SUPPORTED_FILE_EXTENSIONS, get_settings
from backend.app.chunking import Chunk, chunk_document
from backend.app.database import get_db
from backend.app.models import Document, ROLES, User
from backend.app.parsing import extract_text
from backend.app.schemas import DocumentPublic, DocumentUploadResponse
from backend.app.security import get_current_user

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


@router.post("/upload", response_model=DocumentUploadResponse)
def upload_document(
    file: UploadFile = File(...),
    allowed_roles: str = Form(..., description="Comma-separated roles, e.g. 'hr,manager'"),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> DocumentUploadResponse:
    """Upload a PDF/DOCX as an administrator; extracts and chunks the content."""
    settings = get_settings()

    # --- Validate role selection (FR02: admin selects permitted roles) ---
    requested_roles = [r.strip().lower() for r in allowed_roles.split(",") if r.strip()]
    invalid = [r for r in requested_roles if r not in ROLES]
    if not requested_roles or invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"allowed_roles must be a non-empty comma-separated list of "
            f"{', '.join(ROLES)}"
            + (f"; invalid: {', '.join(invalid)}" if invalid else ""),
        )

    # --- Validate file type (extension + MIME cross-check) ---
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

    # --- Persist file + SQLite record (roadmap §8: documents table) ---
    uploads_dir = Path(settings.upload_dir)
    uploads_dir.mkdir(parents=True, exist_ok=True)
    document = Document(
        document_name=Path(file.filename or "unnamed").name,
        file_path="",
        file_type=detected_type,
        file_size=len(data),
        allowed_employee="employee" in requested_roles,
        allowed_hr="hr" in requested_roles,
        allowed_manager="manager" in requested_roles,
    )
    db.add(document)
    db.flush()  # assign document.id
    target = uploads_dir / f"doc_{document.id}_{document.document_name}"
    target.write_bytes(data)
    document.file_path = str(target)
    db.flush()

    # --- Extract (T05) and chunk (T06) ---
    extracted = extract_text(target, detected_type)
    if not extracted.text.strip():
        db.rollback()
        target.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No readable text could be extracted from the document",
        )
    document.content = extracted.text

    chunks = chunk_document(
        [(s.title, s.text) for s in extracted.sections if s.text],
        document_id=f"DOC_{document.id:03d}",
        document_name=document.document_name,
        allowed_roles=requested_roles,
    )
    # Chunks are embedded into ChromaDB on Day 3 (T08); producing chunks with
    # usable source metadata is the Day 2 deliverable.
    db.commit()
    db.refresh(document)

    public = DocumentPublic(
        id=document.id,
        document_name=document.document_name,
        file_type=document.file_type,
        file_size=document.file_size,
        allowed_roles=document.allowed_roles(),
        uploaded_at=document.uploaded_at.isoformat(),
    )
    return DocumentUploadResponse(
        document=public,
        chunk_count=len(chunks),
        sections=extracted.section_titles,
    )