# Embedding evaluation — 2026-09-23

36 fixed queries: 12 topics in Vietnamese, Vietnamese without diacritics,
and English against the same 30 Vietnamese demo documents. Exact cosine
ranking, all documents eligible (equivalent to HR/Manager visibility), no LLM.
Queries and the acceptance gate were fixed before evaluating new models.
See `backend/scripts/benchmark_embeddings.py` and `embedding-benchmark.json`.

| Model | Vietnamese top 1 / top 5 | No accents top 1 / top 5 | English top 1 / top 5 |
| --- | --- | --- | --- |
| MiniLM baseline | 5 / 8 | 5 / 7 | 1 / 4 |
| multilingual-e5-base | 12 / 12 | 1 / 4 | 9 / 12 |
| Ollama nomic-embed-text:latest | 7 / 11 | 7 / 11 | 1 / 2 |
| Ollama bge-m3 | 12 / 12 | 2 / 5 | 11 / 12 |

Each denominator is 12. E5 uses `query: ` / `passage: ` prefixes.
Nomic uses `search_query: ` / `search_document: ` prefixes. BGE-M3 uses none.
The gate was at least 11/12 top-five hits in **every** group. No model passed
all groups. Exit code 1 from the benchmark indicates this quality-gate miss,
not a service failure.

Selected **Ollama BGE-M3** for accented Vietnamese and English queries, with
an explicit remaining limitation for unaccented queries. It has the best
English top-one result among the candidates tested. The user's existing
Nomic model was also tested but performed poorly across English queries and
Vietnamese source text. This does not measure Nomic's English-only quality.

These are small, authored diagnostic queries over placeholder documents,
not held-out production evaluation. They do not establish answer quality,
fallback accuracy, typo robustness, or English-document retrieval quality.
Existing RAG distance thresholds need separate calibration for the selected
model. Do not claim full bilingual/no-accent acceptance based on this run.

Reproduce with the chosen settings in `.env`:

```bash
.venv/bin/python backend/scripts/benchmark_embeddings.py
```

Switch provider/model/prefixes using `.env.example` as a guide. Restart the
API and rebuild the selected model collection before serving queries.
