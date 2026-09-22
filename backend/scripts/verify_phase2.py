"""Live verification of Phase 2 role-filtered retrieval against the running
API + ChromaDB index.

Run from the project root (API must be running on :8000):

    .venv/bin/python backend/scripts/verify_phase2.py
"""

import sys
from pathlib import Path

# Allow running as a plain script without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx  # noqa: E402

from backend.app.vector_store import get_vector_store  # noqa: E402

BASE = "http://localhost:8000"
RESTRICTED = {"thuong.docx", "bao-hiem.docx", "chinh-sach-phuc-loi.docx"}


def _headers(email: str) -> dict:
    response = httpx.post(
        f"{BASE}/auth/login", json={"email": email, "password": "password123"}
    )
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def main() -> None:
    emp = httpx.get(f"{BASE}/documents", headers=_headers("employee@company.com")).json()
    hr = httpx.get(f"{BASE}/documents", headers=_headers("hr@company.com")).json()
    print(f"employee sees {len(emp)} docs, hr sees {len(hr)}")
    leak = [d["document_name"] for d in emp if d["document_name"] in RESTRICTED]
    print("employee restricted leak:", leak or "none")

    store = get_vector_store()
    for role in ("employee", "hr"):
        hits = store.search("Mức thưởng và chính sách bảo hiểm như thế nào?", role)
        print(f"{role} retrieval ->", [h["metadata"]["document_name"] for h in hits])


if __name__ == "__main__":
    main()
