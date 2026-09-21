# AI Employee Knowledge Assistant

A role-aware Retrieval-Augmented Generation (RAG) chatbot. Employees ask questions about
internal company documents and receive answers grounded **only** in documents they are
authorized to access, with supporting source references.

> Full architecture and the 9-day task roadmap:
> [`docs/AI_Employee_Knowledge_Assistant_Architecture_and_9_Day_Task_Roadmap.pdf`](docs/AI_Employee_Knowledge_Assistant_Architecture_and_9_Day_Task_Roadmap.pdf)

## Technology stack

| Component          | Technology                     | Purpose                                                        |
| ------------------ | ------------------------------ | -------------------------------------------------------------- |
| Frontend           | React.js (Vite)                | Login, chat, source display, admin upload                      |
| Backend            | Python FastAPI                 | Auth, RBAC, APIs, document processing, RAG orchestration       |
| Application data   | SQLite                         | Users, roles, document records, conversation history           |
| Vector database    | ChromaDB                       | Chunk storage, embeddings, role-filtered semantic search       |
| LLM                | Ollama (local) or external API | Generate grounded answers from authorized context              |
| Embedding model    | Chroma default (local ONNX)    | Vectors for documents and questions                            |
| Document parsing   | pypdf / python-docx            | Extract and chunk PDF/DOCX text                                |

## Project structure

```
.
├── backend/            # FastAPI application
│   ├── app/
│   │   ├── config.py   # Environment settings (.env)
│   │   └── main.py     # App entry point, /health (T01)
│   └── requirements.txt
├── frontend/           # React app (Vite) — login, chat, admin upload
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
