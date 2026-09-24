"""Rebuild the configured model's index from active SQLite documents.

Stop the API before running. Does not modify document records or other model
collections. The target collection must be empty; choose a new model/config
or explicitly remove an abandoned target before retrying.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sqlalchemy import select
from backend.app.database import SessionLocal
from backend.app.models import Document
from backend.app.parsing import extract_text
from backend.app.chunking import chunk_document
from backend.app.vector_store import get_vector_store


def main():
    store = get_vector_store()
    if store._collection.count():
        raise SystemExit('Target collection is not empty; refusing to overwrite it.')
    count = 0
    try:
        with SessionLocal() as db:
            for document in db.scalars(select(Document).where(Document.is_active.is_(True))):
                extracted = extract_text(Path(document.file_path), document.file_type)
                if not extracted.body_text.strip():
                    raise ValueError(f'Document {document.id} has no readable content')
                chunks = chunk_document([(s.title, s.text) for s in extracted.sections],
                    document_id=f'DOC_{document.id:03d}', document_name=document.document_name,
                    allowed_roles=document.allowed_roles())
                store.index_chunks(chunks)
                count += len(chunks)
    except Exception:
        # Never leave a partly rebuilt index looking ready for use.
        store._client.delete_collection(store._collection.name)
        raise
    print(f'Indexed {count} chunks into {store._collection.name}; original collections retained.')


if __name__ == '__main__':
    main()
