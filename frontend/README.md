# Frontend — AI Employee Knowledge Assistant

React + Vite app: login, chat, source display and (later) the admin upload screen.

## Run

```bash
npm install   # first time only
npm run dev   # http://localhost:5173
```

## Backend connection

`vite.config.js` proxies `/api/*` to `http://localhost:8000` (the FastAPI backend),
stripping the `/api` prefix. Example: `fetch('/api/health')` → `GET http://localhost:8000/health`.

Start the backend first (from the repo root):

```bash
.venv/bin/uvicorn backend.app.main:app --reload --port 8000
```

## Roadmap mapping

- T02: basic chat layout wired to `/api/health` ✅ (this scaffold)
- T19–T20: login integration, history, loading states, source references
