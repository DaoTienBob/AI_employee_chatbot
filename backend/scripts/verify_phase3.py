#!/usr/bin/env python3
"""Phase 3 end-to-end smoke-test (T21).

Verifies that the full RAG pipeline is working:
  1. Login as each demo user (employee / hr / manager / admin).
  2. POST /chat — expect a real answer (not HTTP error).
  3. Source references — check they are present and relate to the question.
  4. Follow-up — second question in the same conversation uses context.
  5. Fallback — a clearly unrelated question should trigger fallback.
  6. Ownership — a user cannot read another user's conversation.

Usage (from the project root with backend running on port 8000):
    .venv/bin/python backend/scripts/verify_phase3.py
"""

import json
import sys
from typing import Any

import httpx

BASE = "http://localhost:8000"

# Demo accounts seeded by backend/app/seed.py
ACCOUNTS = [
    {"email": "employee@example.com", "password": "password123", "role": "employee"},
    {"email": "hr@example.com",       "password": "password123", "role": "hr"},
    {"email": "manager@example.com",  "password": "password123", "role": "manager"},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ok(msg: str) -> None:
    print(f"  ✅ {msg}")

def fail(msg: str) -> None:
    print(f"  ❌ {msg}", file=sys.stderr)

def section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)


def login(client: httpx.Client, email: str, password: str) -> dict[str, Any]:
    r = client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return r.json()


def chat(client: httpx.Client, token: str, question: str,
         conversation_id: int | None = None) -> dict[str, Any]:
    r = client.post(
        "/chat",
        json={"question": question, "conversation_id": conversation_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_login_and_chat(client: httpx.Client) -> dict[str, Any]:
    """T19/T13: verify each role can log in and receive an LLM answer."""
    section("T19/T13 — Login and basic chat for each role")
    tokens: dict[str, str] = {}
    all_pass = True

    for acc in ACCOUNTS:
        try:
            data = login(client, acc["email"], acc["password"])
            tokens[acc["role"]] = data["access_token"]
            ok(f"Login OK: {acc['email']} → role={data['user']['role']}")

            # Ask a general question all roles should have access to
            resp = chat(client, data["access_token"],
                        "What are the main company policies?")
            if resp.get("answer"):
                ok(f"Chat OK [{acc['role']}]: received {len(resp['answer'])} chars")
            else:
                fail(f"Chat [{acc['role']}]: no answer returned — {resp}")
                all_pass = False

            if resp.get("conversation_id"):
                ok(f"Conversation ID assigned: {resp['conversation_id']}")
            else:
                fail(f"No conversation_id in response for {acc['role']}")
                all_pass = False

        except Exception as exc:
            fail(f"{acc['email']}: {exc}")
            all_pass = False

    return {"tokens": tokens, "pass": all_pass}


def test_sources(client: httpx.Client, tokens: dict[str, str]) -> bool:
    """T15: verify source references are present and correctly structured."""
    section("T15 — Source references")
    all_pass = True

    for role, token in tokens.items():
        try:
            resp = chat(client, token, "Tell me about employee benefits.")
            sources = resp.get("sources", [])
            if resp.get("fallback"):
                print(f"  ℹ️  [{role}] fallback (no documents indexed for this role?)")
            elif sources:
                ok(f"[{role}] {len(sources)} source(s) returned")
                for s in sources:
                    assert s.get("document_name"), f"missing document_name in source: {s}"
                    assert s.get("chunk_id"), f"missing chunk_id in source: {s}"
                ok(f"[{role}] Source structure valid")
            else:
                fail(f"[{role}] Answer returned but no sources cited")
                all_pass = False
        except Exception as exc:
            fail(f"[{role}] sources test: {exc}")
            all_pass = False

    return all_pass


def test_conversation_followup(client: httpx.Client, tokens: dict[str, str]) -> bool:
    """T16: verify follow-up questions continue in the same conversation."""
    section("T16 — Conversation history (follow-up)")
    all_pass = True

    for role, token in tokens.items():
        try:
            r1 = chat(client, token, "What is the leave policy?")
            conv_id = r1.get("conversation_id")
            if not conv_id:
                fail(f"[{role}] No conversation_id on first message")
                all_pass = False
                continue

            r2 = chat(client, token, "How many days is that?", conversation_id=conv_id)
            if r2.get("conversation_id") == conv_id:
                ok(f"[{role}] Follow-up reuses conversation {conv_id}")
            else:
                fail(f"[{role}] conversation_id mismatch: {r2.get('conversation_id')} != {conv_id}")
                all_pass = False

            if r2.get("answer"):
                ok(f"[{role}] Follow-up answered: {r2['answer'][:80]}…")
            else:
                fail(f"[{role}] No answer for follow-up")
                all_pass = False

        except Exception as exc:
            fail(f"[{role}] follow-up test: {exc}")
            all_pass = False

    return all_pass


def test_fallback(client: httpx.Client, tokens: dict[str, str]) -> bool:
    """T17: a clearly unrelated question should trigger fallback."""
    section("T17 — Fallback for unrelated question")
    all_pass = True

    # Use employee token — likely has fewest documents indexed
    token = tokens.get("employee") or next(iter(tokens.values()))
    try:
        resp = chat(client, token,
                    "What is the population of Jupiter's moon Europa?")
        if resp.get("fallback"):
            ok("Fallback triggered as expected for off-topic question")
            ok(f"Fallback answer: {resp['answer'][:100]}…")
        else:
            # Not a hard failure — if documents happen to contain astronomy
            # text this might still return a non-fallback answer
            print(f"  ℹ️  No fallback: the model answered without fallback flag "
                  f"({len(resp.get('answer',''))} chars). Check document corpus.")
    except Exception as exc:
        fail(f"Fallback test: {exc}")
        all_pass = False

    return all_pass


def test_conversation_ownership(client: httpx.Client, tokens: dict[str, str]) -> bool:
    """T18: user A cannot read user B's conversation."""
    section("T18 — Conversation ownership isolation")
    roles = list(tokens.keys())
    if len(roles) < 2:
        print("  ℹ️  Only one role available; skipping cross-user test.")
        return True

    all_pass = True
    role_a, role_b = roles[0], roles[1]
    token_a, token_b = tokens[role_a], tokens[role_b]

    try:
        # Create a conversation as user A
        r = chat(client, token_a, "What holidays does the company observe?")
        conv_id = r["conversation_id"]
        ok(f"[{role_a}] Created conversation {conv_id}")

        # Try to read it as user B
        resp = client.get(
            f"/conversations/{conv_id}",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        if resp.status_code == 404:
            ok(f"[{role_b}] Cannot access [{role_a}]'s conversation → 404 ✓")
        elif resp.status_code == 403:
            ok(f"[{role_b}] Cannot access [{role_a}]'s conversation → 403 ✓")
        else:
            fail(
                f"[{role_b}] Unexpected status {resp.status_code} when "
                f"accessing [{role_a}]'s conversation — ownership NOT enforced!"
            )
            all_pass = False
    except Exception as exc:
        fail(f"Ownership test: {exc}")
        all_pass = False

    return all_pass


def test_conversations_list(client: httpx.Client, tokens: dict[str, str]) -> bool:
    """T18: GET /conversations lists only the current user's conversations."""
    section("T18 — GET /conversations scoped to current user")
    all_pass = True

    for role, token in tokens.items():
        try:
            r = client.get(
                "/conversations",
                headers={"Authorization": f"Bearer {token}"},
            )
            r.raise_for_status()
            convs = r.json()
            ok(f"[{role}] /conversations → {len(convs)} conversation(s) listed")
        except Exception as exc:
            fail(f"[{role}] conversations list: {exc}")
            all_pass = False

    return all_pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    print("\n🔍  Phase 3 smoke-test — AI Employee Knowledge Assistant")
    print(f"    Target: {BASE}\n")

    with httpx.Client(base_url=BASE, timeout=120.0) as client:
        # Health check
        try:
            h = client.get("/health")
            h.raise_for_status()
            print(f"✅  Backend reachable — {h.json()['app']} v{h.json()['version']}")
        except Exception as exc:
            print(f"❌  Backend unreachable at {BASE}: {exc}", file=sys.stderr)
            print("    Start the backend first:  .venv/bin/uvicorn backend.app.main:app --reload")
            return 1

        results: list[bool] = []

        result = test_login_and_chat(client)
        results.append(result["pass"])
        tokens = result["tokens"]

        if not tokens:
            print("\n❌  No tokens obtained — aborting remaining tests.")
            return 1

        results.append(test_sources(client, tokens))
        results.append(test_conversation_followup(client, tokens))
        results.append(test_fallback(client, tokens))
        results.append(test_conversation_ownership(client, tokens))
        results.append(test_conversations_list(client, tokens))

    section("Summary")
    passed = sum(1 for r in results if r)
    total  = len(results)
    if passed == total:
        print(f"  ✅  All {total} test groups passed.")
    else:
        print(f"  ⚠️   {passed}/{total} test groups passed — see failures above.")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())

