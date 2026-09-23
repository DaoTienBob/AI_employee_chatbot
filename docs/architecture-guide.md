# How Our RAG Chatbot Works (and Why) — An Intern's Guide

This document explains the architecture behind the backend in
`backend/app/`. Read it top to bottom; each section builds on the previous one.

---

## 1. The big picture

The system answers employee questions **using only company documents the
employee is allowed to see**. That sentence contains the three core ideas:

1. **RAG** (Retrieval-Augmented Generation) — we never let the language model
   answer from its "memory". We first *retrieve* relevant document chunks, then
   tell the model: "answer using ONLY these excerpts."
2. **RBAC** (Role-Based Access Control) — retrieval itself is filtered by the
   user's role (`employee` / `hr` / `manager`), so an employee can never even
   accidentally receive HR-only content.
3. **Grounding** — every answer comes back with *source references*, so users
   can verify where the answer came from.

```
User question
     │
     ▼
[1] Query rewriting ──── qwen3.5 (local Ollama, JSON mode)
     │                     fixes missing Vietnamese accents,
     │                     resolves follow-ups ("còn OT thì sao?")
     ▼
[2] Retrieval ─────────── ChromaDB + bge-m3 embeddings
     │                     WHERE allow_<role> = true  ← the RBAC filter
     ▼
[3] Fallback check ────── weak evidence? → safe "I don't know" reply
     ▼
[4] LLM answer ────────── llama3.2, grounded on the excerpts
     ▼
[5] Sources + history ─── saved to SQLite, returned to the frontend
```

---

## 2. Why rewrite the query at all?

Vietnamese users often type without diacritics:
`toi duoc nghi phep bao nhieu ngay` ("how many leave days do I get?").
Embedding models match this poorly against properly accented documents.

So before retrieval, a **small dedicated LLM** (qwen3.5) rewrites the question:

- restores accents: → `Tôi được nghỉ phép bao nhiêu ngày mỗi năm?`
- turns follow-ups into standalone questions using *previous user questions only*
- may instead return a **clarification** (e.g. bare "tôi muốn xin nghi" could
  mean annual leave *or* resignation — the bot asks which)

Key safety rules baked into the rewriter:


---

## 3. How RBAC actually works (the important part)

The naive approach — generate an answer, then *check* it before sending — is
unsafe: the model may already have leaked restricted facts.

Instead, **the permission filter is part of the database query itself**:

```python
# backend/app/vector_store.py
self._collection.query(
    query_embeddings=...,
    n_results=k,
    where={f"allow_{role}": {"$eq": True}},   # ← filter BEFORE ranking
    ...
)
```

Every indexed chunk carries `allow_employee / allow_hr / allow_manager` flags
copied from its parent document. ChromaDB applies this filter *before* ranking,
so **unauthorized chunks are never candidates** — they cannot enter the prompt,
the answer, or the source list. There is nothing to "check afterwards".

Where does `role` come from? **Always the database, never the request.**
`get_current_user()` re-loads the user from SQLite on every request using the
JWT's `sub` (user id). The token's role claim is informational only — a user
editing their token cannot promote themselves.

Two more layers:

- **Conversation ownership**: users can only read/continue conversations they
  created. Foreign IDs return 404 (not 403) so nobody can *discover* that
  another user's conversation exists.
- **History hygiene**: prior *assistant* answers are excluded from both the
  rewriter and the grounding prompt. Otherwise an answer generated under an old
  (more permissive) role could be replayed to a restricted user forever.

> **Intern takeaway:** filter at the data layer, not the presentation layer.
> And make the source of truth for identity the database, not client input.

- Only **user** questions from history are visible to it. Assistant answers are
  excluded — they could contain evidence the user's role shouldn't see.
- The rewriter's output is **untrusted data**, validated with a strict Pydantic
  schema (`extra='forbid'`). Anything malformed → fall back to the original
  question. A broken rewrite can never break the app.
- We search **both** the original and rewritten question, then merge results
  with Reciprocal Rank Fusion (RRF) — so a bad rewrite can only add noise,
  never delete the original's results.

> **Intern takeaway:** never trust an LLM's output as data. Validate it, and
> design so the failure mode is "fall back to the safe path."

---

## 4. Answer quality: what we fixed and why

These came out of a live audit — each is a lesson in how small local models fail.

### 4.1 "Answer only the latest question"

**Problem:** in a conversation ("how many leave days?" → "and WFH?"), llama3.2
kept answering *earlier* questions, or produced a garbled mix of all of them.

**Fix:** history is **not** sent as chat turns (small models treat message
lists as a quiz to answer one by one). Earlier questions go into the system
prompt as inert, clearly-labelled context:

```
--- Earlier questions in this conversation (context only, DO NOT answer these) ---
- Tôi được nghỉ phép bao nhiêu ngày mỗi năm?
--- End of earlier questions ---
```

The API message list is just `[system, current_question]`.

> **Lesson:** prompt *instructions* are weak; prompt *structure* is strong.
> When a small model ignores what you say, change what it sees.

### 4.2 A refusal is not an answer

**Problem:** when evidence was missing, the model replied "I don't have that
information…" — but the API still reported `fallback: false` and attached 5
sources, so the frontend couldn't tell an answer from a polite failure.

**Fix:** a lightweight heuristic (`_is_refusal` in `rag.py`) counts "no
evidence" phrases (Vietnamese + English); ≥2 markers → report
`fallback: true`, strip sources. The refusal text itself is kept — it's more
informative than a canned message.

> **Lesson:** the *shape* of your API response must reflect the *meaning* of
> the content, or the UI will lie to users.

### 4.3 Sources = what was used, not what was fetched

Sources are capped to the top 3 chunks supplied to the prompt. Listing all 5
retrieved chunks on a refusal (or on an answer that used one chunk) erodes
trust in citations.

### 4.4 No hallucinated facts — by design, with a backstop

The grounding prompt says: use ONLY the excerpts, don't infer beyond them.
The distance-threshold fallback catches "no relevant evidence at all" cases,
and the refusal detector catches "evidence existed but didn't answer the
question" cases. Two different failure modes, two different guards.

---

## 5. The other guards you'll see in the code

| Guard | Where | Why |
|---|---|---|
| SQLite busy timeout (30s) | `database.py` | concurrent writes (chat + admin upload) wait instead of 500-ing |
| Upload size caps | `routers/documents.py` | declared-size check + hard cap on bytes actually read — no memory exhaustion |
| Startup index check | `main.py` | compares ChromaDB permission flags vs SQLite; a crash mid-replacement can't silently change who can see a document |
| Demo users only in debug | `seed.py` | known-password admin accounts must never exist in a real deployment |
| Short tokens + `/auth/refresh` | `security.py`, `routers/auth.py` | a stolen token is worthless after 60 minutes |

---

## 6. How to verify changes yourself

```bash
.venv/bin/python -m pytest backend/tests -q                    # 54 tests
.venv/bin/python backend/scripts/benchmark_embeddings.py       # retrieval quality
.venv/bin/python backend/scripts/benchmark_query_rewriting.py  # rewriting quality
```

For live end-to-end checks, start the server
(`.venv/bin/uvicorn backend.app.main:app --port 8000`) and log in with the demo
accounts, then ask:

1. an **answerable** question → grounded answer + sources
2. a **restricted** question as employee → refusal, no restricted sources
3. the same question as HR → correct answer from the restricted doc
4. a **nonsense** question → safe refusal with `fallback: true`

If any of those four misbehave, you have found a real bug — not a flake.

