"""Upload the generated demo corpus to the running backend as the admin.

Requires the API server to be running (uvicorn backend.app.main:app) and the
corpus to exist (backend/scripts/generate_demo_corpus.py).

Usage (from the project root):

    .venv/bin/python backend/scripts/upload_demo_corpus.py [base_url]

Note: re-running creates duplicate document records; wipe data/app.db (and
restart the API) for a clean slate.
"""

import json
import sys
from pathlib import Path

import httpx

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
ADMIN_EMAIL = "admin@company.com"
ADMIN_PASSWORD = "password123"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR = PROJECT_ROOT / "data" / "demo_corpus"
MANIFEST = CORPUS_DIR / "manifest.json"

DOCX_MIME = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def main() -> None:
    entries = json.loads(MANIFEST.read_text(encoding="utf-8"))
    print(f"Uploading {len(entries)} documents to {BASE_URL}")

    with httpx.Client(base_url=BASE_URL, timeout=60) as client:
        response = client.post(
            "/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        )
        response.raise_for_status()
        token = response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        succeeded = 0
        for entry in entries:
            response = client.post(
                "/documents/upload",
                headers=headers,
                files={
                    "file": (
                        entry["filename"],
                        (CORPUS_DIR / entry["filename"]).read_bytes(),
                        DOCX_MIME,
                    )
                },
                data={"allowed_roles": ",".join(entry["suggested_allowed_roles"])},
            )
            if response.status_code == 200:
                body = response.json()
                print(
                    f"  OK  {entry['filename']:<42} chunks={body['chunk_count']:<3} "
                    f"roles={','.join(body['document']['allowed_roles'])}"
                )
                succeeded += 1
            else:
                print(f"FAIL  {entry['filename']:<42} {response.status_code} {response.text[:100]}")

    print(f"Done: {succeeded}/{len(entries)} uploaded")


if __name__ == "__main__":
    main()
