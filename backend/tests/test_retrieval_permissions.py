"""Role-aware retrieval permission tests (T10 / T12).

Uploads a general (all-roles) and a restricted (hr/manager-only) DOCX as the
admin, then exercises role-filtered retrieval as Employee, HR and Manager:
each role must only ever receive chunks assigned to it. Also covers document
replacement (T11): old chunk content must disappear from the index.
"""

import io

import pytest
from docx import Document as DocxDocument
from fastapi.testclient import TestClient

from backend.app.database import init_db
from backend.app.main import app
from backend.app.vector_store import get_vector_store


@pytest.fixture(scope="module")
def client():
    """TestClient against the isolated SQLite/Chroma/uploads dirs set up in
    conftest.py (env vars applied before any backend import)."""
    init_db()
    with TestClient(app) as test_client:
        yield test_client


def _login(client: TestClient, email: str) -> dict:
    response = client.post(
        "/auth/login", json={"email": email, "password": "password123"}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _docx_bytes(paragraphs: list[tuple[str, str]]) -> bytes:
    document = DocxDocument()
    for title, body in paragraphs:
        document.add_heading(title, level=1)
        document.add_paragraph(body)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


GENERAL_DOC = [
    ("Leave Policy", "Employees receive 12 days of annual leave per year."),
    ("Working Hours", "Standard working hours are from 9 AM to 6 PM."),
]
RESTRICTED_DOC = [
    ("Bonus Policy", "Managers and HR review the annual bonus pool of 5 percent."),
    ("Insurance", "Executive insurance coverage includes dental and vision."),
]
REPLACEMENT_DOC = [
    ("Leave Policy", "Employees receive 20 days of annual leave per year."),
]
# Distinct content so it never collides with assertions in other tests.
EMPLOYEE_ONLY_DOC = [
    ("Wellness Program", "Refreshment budget is replenished every quarter."),
]

ADMIN = "admin@company.com"
EMPLOYEE = "employee@company.com"
HR = "hr@company.com"

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture(scope="module")
def admin_headers(client):
    return _login(client, ADMIN)


@pytest.fixture(scope="module")
def indexed_documents(client, admin_headers):
    """Upload one all-roles document and one hr/manager-only document."""
    ids = {}
    for key, doc, roles in (
        ("general", GENERAL_DOC, "employee,hr,manager"),
        ("restricted", RESTRICTED_DOC, "hr,manager"),
    ):
        response = client.post(
            "/documents/upload",
            headers=admin_headers,
            files={"file": (f"{key}.docx", _docx_bytes(doc), DOCX_MIME)},
            data={"allowed_roles": roles},
        )
        assert response.status_code == 200, response.text
        ids[key] = response.json()["document"]["id"]
    return ids


# --- T09: every indexed chunk carries the expected role flags ---------------


def test_chunks_have_role_flags(indexed_documents):
    metadata_list = get_vector_store()._collection.get(include=["metadatas"])["metadatas"]
    assert metadata_list, "expected chunks to be indexed"
    for metadata in metadata_list:
        assert {"allow_employee", "allow_hr", "allow_manager"} <= set(metadata)
        assert metadata["document_id"].startswith("DOC_")


# --- T10/T12: role-filtered retrieval ----------------------------------------


def test_employee_retrieval_sees_only_general(indexed_documents):
    hits = get_vector_store().search("How many annual leave days do I get?", "employee")
    assert hits, "employee should retrieve the general document"
    assert all(h["metadata"]["allow_employee"] for h in hits)
    assert all(
        h["metadata"]["document_id"] == f"DOC_{indexed_documents['general']:03d}"
        for h in hits
    )


def test_hr_retrieval_sees_restricted(indexed_documents):
    hits = get_vector_store().search("What is the annual bonus pool percentage?", "hr")
    assert hits
    assert all(h["metadata"]["allow_hr"] for h in hits)
    document_ids = {h["metadata"]["document_id"] for h in hits}
    assert f"DOC_{indexed_documents['restricted']:03d}" in document_ids


def test_restricted_content_never_reaches_employee(indexed_documents):
    for question in (
        "What is the annual bonus pool of 5 percent?",
        "Executive insurance coverage dental vision",
        "bonus insurance",
    ):
        hits = get_vector_store().search(question, "employee")
        assert all(
            h["metadata"]["document_id"] == f"DOC_{indexed_documents['general']:03d}"
            for h in hits
        ), f"restricted chunk leaked to employee for query: {question!r}"


# --- GET /documents list is role-scoped --------------------------------------


def test_document_list_role_scoping(client, indexed_documents):
    employee_ids = {
        d["id"] for d in client.get("/documents", headers=_login(client, EMPLOYEE)).json()
    }
    assert employee_ids == {indexed_documents["general"]}
    hr_ids = {d["id"] for d in client.get("/documents", headers=_login(client, HR)).json()}
    assert indexed_documents["general"] in hr_ids
    assert indexed_documents["restricted"] in hr_ids


def test_employee_role_grants_access_to_all(client, admin_headers):
    """A document tagged for employees is visible/retrievable by every role."""
    response = client.post(
        "/documents/upload",
        headers=admin_headers,
        files={"file": ("employee_only.docx", _docx_bytes(EMPLOYEE_ONLY_DOC), DOCX_MIME)},
        data={"allowed_roles": "employee"},
    )
    assert response.status_code == 200, response.text
    doc_id = response.json()["document"]["id"]

    for email in (EMPLOYEE, HR, "manager@company.com"):
        ids = {d["id"] for d in client.get("/documents", headers=_login(client, email)).json()}
        assert doc_id in ids, f"{email} cannot list the employee-tagged document"

    store = get_vector_store()
    for role in ("employee", "hr", "manager"):
        hits = store.search("refreshment budget", role)
        assert any(
            h["metadata"]["document_id"] == f"DOC_{doc_id:03d}" for h in hits
        ), f"{role} cannot retrieve the employee-tagged document"


# --- T11: replacement removes old chunks -------------------------------------


def test_replacement_removes_old_chunks(client, admin_headers, indexed_documents):
    doc_id = indexed_documents["general"]
    store = get_vector_store()
    doc_key = f"DOC_{doc_id:03d}"
    assert store.count_for_document(doc_key) > 0

    response = client.put(
        f"/documents/{doc_id}",
        headers=admin_headers,
        files={"file": ("general_v2.docx", _docx_bytes(REPLACEMENT_DOC), DOCX_MIME)},
        data={"allowed_roles": "employee,hr,manager"},
    )
    assert response.status_code == 200, response.text

    # Old 12-day content is gone; only the replacement (20 days) remains.
    remaining = store._collection.get(
        where={"document_id": {"$eq": doc_key}}, include=["documents"]
    )["documents"]
    assert remaining, "replacement should be indexed"
    assert all("20 days" in text for text in remaining)
    assert not any("12 days" in text for text in remaining)

    # Employee retrieval reflects the updated content only.
    hits = store.search("annual leave days", "employee")
    assert all("12 days" not in h["text"] for h in hits)


def test_failed_replacement_restores_old_chunks(
    client, admin_headers, indexed_documents
):
    """A rejected replacement file must leave the old version retrievable."""
    doc_id = indexed_documents["restricted"]
    store = get_vector_store()
    doc_key = f"DOC_{doc_id:03d}"
    before = store.count_for_document(doc_key)
    assert before > 0

    response = client.put(
        f"/documents/{doc_id}",
        headers=admin_headers,
        # Garbage bytes with a valid .docx name/MIME: parsing must fail (422).
        files={"file": ("broken.docx", b"this is not a real docx", DOCX_MIME)},
        data={"allowed_roles": "hr,manager"},
    )
    assert response.status_code == 422

    assert store.count_for_document(doc_key) == before
    hits = store.search("What is the annual bonus pool percentage?", "hr")
    assert any(h["metadata"]["document_id"] == doc_key for h in hits)


def test_replace_requires_admin(client, indexed_documents):
    response = client.put(
        f"/documents/{indexed_documents['general']}",
        headers=_login(client, HR),
        files={"file": ("x.docx", _docx_bytes(REPLACEMENT_DOC), DOCX_MIME)},
        data={"allowed_roles": "employee"},
    )
    assert response.status_code == 403


def test_replace_unknown_document_404(client, admin_headers):
    response = client.put(
        "/documents/99999",
        headers=admin_headers,
        files={"file": ("x.docx", _docx_bytes(REPLACEMENT_DOC), DOCX_MIME)},
        data={"allowed_roles": "employee"},
    )
    assert response.status_code == 404
