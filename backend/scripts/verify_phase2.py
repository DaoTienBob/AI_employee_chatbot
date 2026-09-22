"""Live verification of Phase 2 role-filtered retrieval against the running
API + ChromaDB index.

Run from the project root (API must be running on :8000):

    .venv/bin/python backend/scripts/verify_phase2.py
"""

import httpx

BASE = "http://localhost:8000"
RESTRICTED = {"thuong.docx", "bao-hiem.docx", "chinh-sach-phuc-loi.docx"}


def _headers(email: str) -> dict:
    response = httpx.post(
        f"{BASE}/auth/login", json={"email": email, "password": "password123"}
    )
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def main() -> None:
    for role in ("employee", "hr", "manager"):
        headers = _headers(f"{role}@company.com")
        response = httpx.get(f"{BASE}/documents", headers=headers)
        response.raise_for_status()
        documents = response.json()
        assert all(role in document["allowed_roles"] for document in documents)
        if role == "employee":
            assert not any(d["document_name"] in RESTRICTED for d in documents)
        response = httpx.get(
            f"{BASE}/documents/search",
            headers=headers,
            params={"query": "Mức thưởng và chính sách bảo hiểm như thế nào?"},
            timeout=60,
        )
        response.raise_for_status()
        hits = response.json()
        assert hits, f"No results for {role}; upload the demo corpus first"
        assert all(h["metadata"][f"allow_{role}"] for h in hits)
        print(f"{role}: {len(documents)} documents; retrieval ->",
              [h["metadata"]["document_name"] for h in hits])


if __name__ == "__main__":
    main()
