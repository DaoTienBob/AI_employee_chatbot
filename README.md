# AI Employee Knowledge Assistant

A role-aware Retrieval-Augmented Generation (RAG) chatbot. Employees ask questions about
internal company documents and receive answers grounded **only** in documents they are
authorized to access, with supporting source references.

> Full architecture and the 9-day task roadmap:
> [`docs/AI_Employee_Knowledge_Assistant_Architecture_and_9_Day_Task_Roadmap.pdf`](docs/AI_Employee_Knowledge_Assistant_Architecture_and_9_Day_Task_Roadmap.pdf)

## Technology stack

| Component          | Technology                     | Purpose                                                        |
| ------------------ | ------------------------------ | -------------------------------------------------------------- |
| Frontend           | React.js (Vite)                | Login, chat, source display (admin upload via API/scripts)     |
| Backend            | Python FastAPI                 | Auth, RBAC, APIs, document processing, RAG orchestration       |
| Application data   | SQLite                         | Users, roles, document records, conversation history           |
| Vector database    | ChromaDB                       | Chunk storage, embeddings, role-filtered semantic search       |
| LLM                | Ollama (local) or external API | Generate grounded answers from authorized context              |
| Embedding model    | Multilingual E5 / Ollama    | Vectors for documents and questions                            |
| Document parsing   | pypdf / python-docx            | Extract and chunk PDF/DOCX text                                |

## Project structure

```
.
├── backend/            # FastAPI application
│   ├── app/
│   │   ├── config.py   # Environment settings (.env)
│   │   ├── main.py     # App entry point, /health (T01)
│   │   ├── database.py # SQLAlchemy engine/session (T03)
│   │   ├── models.py   # SQLite ORM models: User, Document (T03/T04)
│   │   ├── schemas.py  # Pydantic request/response schemas (T03/T04)
│   │   ├── security.py # bcrypt hashing + JWT sessions (T03)
│   │   ├── seed.py     # Demo users (T03)
│   │   ├── parsing.py  # PDF/DOCX text extraction (T05)
│   │   ├── chunking.py # Token-aware chunking with source metadata (T06)
│   │   ├── vector_store.py # ChromaDB indexing + role-filtered search (T07-T10)
│   │   └── routers/    # API routers (auth.py T03, documents.py T04/T11)
│   ├── tests/          # Retrieval permission tests (T10/T12)
│   └── requirements.txt
├── frontend/           # React app (Vite) — login, chat, source display
├── data/               # Runtime artifacts: SQLite, ChromaDB, uploads (gitignored)
├── docs/               # Architecture & sprint roadmap
├── .env.example        # Template for local configuration
└── .venv/              # Python virtual environment (gitignored)
```

## Backend setup

```bash
# 1. Create and activate the virtual environment (already created if following this repo)
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r backend/requirements.txt

# 3. Configure the environment (optional; sane defaults are built in)
cp .env.example .env

# 4. Run the API (from the project root)
.venv/bin/uvicorn backend.app.main:app --reload --port 8000
```

- Health check: <http://localhost:8000/health>
- Interactive API docs: <http://localhost:8000/docs>

## Frontend setup

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
```

## Demo accounts (T03)

Created automatically on backend startup and stored in SQLite (`data/app.db`)
with bcrypt-hashed passwords:

| Email                   | Password      | Role     | Admin |
| ----------------------- | ------------- | -------- | ----- |
| `employee@company.com`  | `password123` | employee | no    |
| `hr@company.com`        | `password123` | hr       | no    |
| `manager@company.com`   | `password123` | manager  | no    |
| `admin@company.com`     | `password123` | employee | yes   |

> Admin permission (document upload/replace) is a separate flag, not an
> employee role (roadmap §3.4).

Try it:

```bash
# Login (issue session)
curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "employee@company.com", "password": "password123"}'

# Identify the authenticated user and role
curl -s http://localhost:8000/auth/me \
  -H "Authorization: Bearer <access_token>"
```

## Uploading documents (T04–T09, Days 2–3)

Only users with the administrator permission (`admin@company.com`) can upload.
Upload runs the full ingestion pipeline: validation (pypdf / python-docx
extraction), word-window chunking subdivided to fit the embedding tokenizer, source metadata,
and configurable embeddings and ChromaDB indexing where every chunk inherits the
document's role flags (`allow_employee` / `allow_hr` / `allow_manager`).

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@company.com", "password": "password123"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -X POST http://localhost:8000/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@policy.pdf" \
  -F "allowed_roles=hr,manager"
```

Validation: `.pdf`/`.docx` only (extension + MIME cross-check, `400`), max
`MAX_UPLOAD_SIZE_MB` (`413`), admin-only (`403`), role list must be a subset
of `employee,hr,manager` (`400`), unreadable/scanned files (`422`).

## Role-aware retrieval (T10–T12, Day 4)

- `GET /documents` lists only the documents the authenticated user's role may
  access (role always comes from the session, never the request).
- `GET /documents/search?query=...` performs semantic search using the current
  authenticated database role; returns authorized chunks and source metadata.
- `PUT /documents/{id}` (admin only) replaces a document: old indexed chunks
  are removed first, the replacement content is re-extracted/chunked/indexed,
  and the record is updated (T11). Replacement files use unique paths; failures
  during ingestion or commit restore the prior index, including saved embeddings.
  This is compensating rollback across SQLite/files/Chroma, not crash-atomic storage.
- `VectorStore.search(query, role)` (T10) applies the permission filter inside
  the ChromaDB query (`where={f"allow_{role}": True}`), so restricted chunks
  never become retrieval candidates — and can therefore never enter a future
  LLM prompt.

```bash
# List documents visible to the current role
curl http://localhost:8000/documents -H "Authorization: Bearer <access_token>"

# Replace a document (admin)
curl -X PUT http://localhost:8000/documents/1 \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@policy_v2.docx" \
  -F "allowed_roles=employee,hr,manager"
```

Run the permission tests (T10/T12):

```bash
.venv/bin/python -m pytest backend/tests -v
```

Live verification (API + indexed demo corpus):

```bash
.venv/bin/python backend/scripts/verify_phase2.py   # requires the API running
```

## Demo corpus (knowledge taxonomy)

The assistant's knowledge base is organized into 4 categories — **Policy**,
**Operations**, **Company tour**, **Contact** — with ~30 topics; see
[`docs/knowledge-taxonomy.md`](docs/knowledge-taxonomy.md) for the full list
and the suggested role visibility per document (compensation-sensitive topics
like `Thưởng`, `Bảo hiểm` are HR/Manager-only; `Contact` feeds the fallback
answer when no authorized evidence is found).

```bash
# Generate data/demo_corpus/*.docx + manifest.json (30 placeholder docs)
.venv/bin/python backend/scripts/generate_demo_corpus.py

# Upload them all as the admin (API server must be running)
.venv/bin/python backend/scripts/upload_demo_corpus.py
```

Prefer DOCX for Vietnamese content: python-docx extracts Unicode natively,
while PDFs need proper Unicode font maps or extraction fails.

## Planned API surface (from the roadmap)

| Method | Endpoint              | Purpose / access                                |
| ------ | --------------------- | ----------------------------------------------- |
| POST   | `/auth/login`         | Authenticate employee; issue session            |
| GET    | `/auth/me`            | Return authenticated user and current role      |
| POST   | `/chat`               | Role-aware RAG answer; authenticated user       |
| GET    | `/conversations`      | List only the current user's conversations      |
| GET    | `/conversations/{id}` | Read conversation only when owned by requester  |
| POST   | `/documents/upload`   | Upload/index PDF/DOCX; administrator only       |
| GET    | `/documents`          | List only documents accessible to current user  |
| PUT    | `/documents/{id}`     | Replace document and indexed content; admin only |

## Security invariants

- The permission filter is part of every ChromaDB retrieval query; restricted chunks must
  never enter prompt construction.
- Never trust a role supplied by the frontend — derive it from the authenticated session.
- Only return source references that correspond to authorized retrieved chunks.

## Configurable embeddings

The selected provider is Ollama with `nomic-embed-text-v2-moe` (see `.env.example`).
Embedding configuration is separate from the answer-generation LLM. To try E5:

```dotenv
EMBEDDING_PROVIDER=sentence_transformers
EMBEDDING_MODEL=intfloat/multilingual-e5-base
EMBEDDING_QUERY_PREFIX="query: "
EMBEDDING_DOCUMENT_PREFIX="passage: "
EMBEDDING_DEVICE=cpu
```

E5 runs locally; its first load downloads model weights to `data/models`.
The prefixes are required for E5 retrieval, including Vietnamese queries.
Local tokenizers split oversized document chunks and reject oversized queries
instead of silently truncating them. The chunk-size setting remains a word
window target; actual chunks can be smaller to fit the model context.

To use Ollama embeddings instead (after `ollama pull nomic-embed-text-v2-moe`):

```dotenv
EMBEDDING_PROVIDER=ollama
EMBEDDING_MODEL=nomic-embed-text-v2-moe
EMBEDDING_QUERY_PREFIX="search_query: "
EMBEDDING_DOCUMENT_PREFIX="search_document: "
EMBEDDING_TIMEOUT_SECONDS=120
```

Ollama uses `OLLAMA_BASE_URL` and `truncate=False`; an input exceeding its model
context is rejected rather than silently cut off. Other models may require
other prefixes; follow the selected model's instructions.

Changing provider, model, or prefixes selects a separate Chroma collection.
Existing collections are preserved. Stop the API, edit `.env`, rebuild the
new empty collection, then restart the API:

```bash
.venv/bin/python backend/scripts/reindex_embeddings.py
```

Reindexing reads active document records and original files, preserving source
metadata and role flags. It refuses to overwrite a nonempty target collection.
An old collection may be stale after subsequent document edits; do not switch
back to it without rebuilding. Changing only the model name never migrates
vectors automatically.

Run the repeatable 36-query Vietnamese/English retrieval smoke benchmark:

```bash
.venv/bin/python backend/scripts/benchmark_embeddings.py
```

It tests 12 topics in accented Vietnamese, unaccented Vietnamese and English
against the 30 Vietnamese demo documents, without writing to the index. The
initial gate is at least 11/12 correct documents in the top five for each group.
This is a retrieval smoke test, not proof of answer quality or a calibrated
fallback threshold. Recalibrate relevance thresholds for real documents when
changing embedding models; cosine scores are not comparable across models.

Benchmark results and limitations: [embedding evaluation](docs/embedding-evaluation.md).
For the locally installed Nomic alternative, use `EMBEDDING_MODEL=nomic-embed-text:latest`,
`EMBEDDING_QUERY_PREFIX="search_query: "`, and
`EMBEDDING_DOCUMENT_PREFIX="search_document: "` with the Ollama provider.

## Query rewriting (Phase 3: T14/T16/T18)

The chat pipeline now follows:

`original question → LLM rewrite → original + rewritten role-filtered searches → rank fusion → evidence check → grounded answer`

The rewrite restores Vietnamese accents and clarifies follow-ups using up to
three recent user messages from the owned conversation. Prior assistant answers
are excluded from both rewriting and answer generation because their evidence
may no longer be authorized. User history is intent context, not evidence.
The original question remains the final answer request and is saved unchanged.

```dotenv
QUERY_REWRITE_ENABLED=true
QUERY_REWRITE_MODE=adaptive
LLM_PROVIDER=ollama
LLM_MODEL=qwen3.5:latest
QUERY_REWRITE_PROVIDER=inherit
QUERY_REWRITE_MODEL=
QUERY_REWRITE_TIMEOUT_SECONDS=60
```

`QUERY_REWRITE_MODE` supports `always`, `adaptive`, and `off`. The example
configuration uses `adaptive`: local phrase rules route likely unaccented or
partially accented Vietnamese, ambiguous Vietnamese leave requests, and likely
follow-ups to Qwen. Other questions search directly. ASCII text alone is not a
Vietnamese signal. Short questions with prior user history are conservatively
rewritten. These rules are heuristics, not comprehensive language detection;
use `always` if your queries frequently fall outside their vocabulary.
`QUERY_REWRITE_ENABLED=false` overrides every mode. The code default remains
`always` for configurations that omit the new setting.

Both stages use the same local Qwen model: `inherit` uses `LLM_PROVIDER`, and
an empty `QUERY_REWRITE_MODEL` uses `LLM_MODEL`. Rewriting and answering make
separate requests with different prompts; they share the same model weights in
Ollama. Nomic embeddings still require a separate model. Actual memory use also
depends on context size and concurrent requests. The 60-second rewrite timeout
allows more time for local model loading; failures still use the original query.
To use an external rewrite provider later, override the provider/model and set
its corresponding API key. Only the question and recent user questions go to
rewriting, not document excerpts.
Changes require restarting the backend. Set the flag to false to search the
original query without rewriting. Timeout, unavailable model, or malformed JSON
falls back to the original query. Valid ambiguity output asks a clarification
question (`fallback=true`, no sources), without retrieval or answer generation.
This relies on the model detecting ambiguity; it is not a guaranteed classifier.

Each search uses the same authenticated role. Results are deduplicated by chunk
ID and combined with reciprocal-rank fusion, retaining the union (at most `2 * RETRIEVAL_TOP_K`).
No extra reranker model is introduced. Rewrites never become source evidence.

Measure current-index retrieval and latency (requires Ollama/demo documents):

```bash
.venv/bin/python backend/scripts/benchmark_query_rewriting.py
```

This 12-query smoke check is not held-out evaluation. Verify intent preservation,
ambiguous queries, follow-ups and final answer quality on real questions too.
