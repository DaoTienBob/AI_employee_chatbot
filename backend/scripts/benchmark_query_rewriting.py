"""Compare original vs rewritten unaccented queries on the active index.

Read-only against application storage. Requires the demo corpus in the selected
embedding collection and the configured LLM running. JSON output includes latency.
"""
import json
import sys
import time
import unicodedata
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.scripts.benchmark_embeddings import CASES
from backend.scripts.generate_demo_corpus import slugify
from backend.app.query_rewriting import rewrite_query, retrieve_queries
from backend.app.vector_store import get_vector_store


def main():
    store = get_vector_store()
    rows = []
    for topic, question, _ in CASES:
        query = ''.join(c for c in unicodedata.normalize('NFD', question)
                        if unicodedata.category(c) != 'Mn').replace('đ', 'd')
        expected = slugify(topic) + '.docx'
        started = time.monotonic()
        original = store.search(query, 'hr', top_k=5)
        original_seconds = time.monotonic() - started
        started = time.monotonic()
        rewritten = rewrite_query(query, [])
        hits = [] if rewritten.clarification else retrieve_queries(store, query, rewritten.query, 'hr', 5)
        def rank(hits):
            return next((i for i, h in enumerate(hits, 1)
                         if h['metadata']['document_name'] == expected), None)
        rows.append(dict(topic=topic, original=query, rewrite=rewritten.query,
                         clarification=rewritten.clarification, original_rank=rank(original),
                         rewritten_rank=rank(hits), original_seconds=round(original_seconds, 3),
                         rewritten_seconds=round(time.monotonic()-started, 3)))
    print(json.dumps({'original_top5': sum(r['original_rank'] is not None for r in rows),
                      'rewritten_top5': sum(r['rewritten_rank'] is not None for r in rows),
                      'total': len(rows), 'details': rows}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
