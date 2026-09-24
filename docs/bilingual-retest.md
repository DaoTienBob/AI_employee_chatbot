# Audit fixes and bilingual retest — 2026-09-24

- Regression suite: 69 tests passed with `DEBUG=true`.
- Live models: BGE-M3 retrieval, Qwen 3.5 rewriting, Llama 3.2 answers.
- Retrieval: 12/12 top-five document matches for each of accented Vietnamese,
  English and unaccented Vietnamese (36 authored queries, 30 demo documents).
- Live answer checks: leave and WFH facts correct in both languages; employee
  bonus request correctly refused; HR bonus request answered; unrelated cake
  requests refused in both languages. All three refusals have no sources.
- Current persistent collection passes the complete startup permission check.
- Conversation persistence was stubbed for live checks, avoiding new demo chats.

Fixes cover explicit single-phrase refusals, complete prompt-source references,
startup permission validation plus current SQLite grants at retrieval time,
word/number checks on rewrites, quantity-homophone correction, and retaining the
original-plus-rewrite candidate union. Regression tests include mismatches past
the fifth chunk, orphan/inactive documents, and permissions revoked in SQLite.

Raw observations: [bilingual-retest.json](bilingual-retest.json).

Limits: this is a small smoke evaluation, not held-out production validation.
Refusal detection is heuristic. Source references identify all supplied context;
they do not prove which excerpt supported each generated claim. Word checks do
not prove semantic equivalence for every homophone. In this run the HR answer
to an English bonus question was in Vietnamese, so answer-language consistency
remains a separate quality issue.

## Gemini retry — 2026-09-24

Configured rewriting now uses `gemini-3.6-flash`: Gemini rejected
`gemini-2.5-flash` with HTTP 404 (unavailable to new users) and recommended
this replacement. Embeddings remain BGE-M3; answers remain Llama 3.2.

- Regression suite: **79 passed**, two dependency deprecation warnings.
- Top-five document matches: accented Vietnamese **12/12**, English **12/12**,
  unaccented Vietnamese **5/12**.
- Only **8/45** attempted calls (including the preflight) produced recorded
  parseable rewrite responses. All unaccented questions used unchanged queries.
  Individual API failure reasons were not captured in this benchmark.
- A separate direct unaccented WFH rewrite succeeded, restoring accents correctly.
  An instrumented confirmation run then stopped at preflight with **HTTP 503**.
  API availability is therefore a confirmed issue; these retrieval results do
  not isolate Gemini's rewrite quality from fallback behavior.
- Eight answer smoke checks: leave and WFH answers contained the expected 12-day
  and two-day facts in both languages; employee bonus access and unrelated cake
  questions were refused with no sources. HR bonus was answered in Vietnamese
  despite an English question, so language consistency remains unresolved.
- Conversation persistence was stubbed; no benchmark chats were saved.

Raw observations: [gemini-bilingual-retest.json](gemini-bilingual-retest.json).
Earlier results above describe the prior Ollama rewrite run, not Gemini.

## Shared Ollama model — 2026-09-24

Switched rewriting and answering to `qwen3.5:latest` through Ollama.
`QUERY_REWRITE_PROVIDER=inherit` and an empty `QUERY_REWRITE_MODEL` share the
answer model setting. Rewrite timeout is 60 seconds; BGE-M3 remains unchanged.
Regression suite: **79 passed**. A live smoke check restored
`toi duoc nghi phep may ngay moi nam` to
`Tôi được nghỉ phép mấy ngày mỗi năm?`; a separate answer call returned the
provided fact of 12 annual leave days. Both clients reported the same model.
This is a two-call smoke test, not a new full bilingual retrieval evaluation.

## Nomic v2 MoE + shared Qwen retest — 2026-09-24

Rebuilt all 30 active document chunks into a separate Nomic collection; previous
collections were retained. Configured `search_query: ` and `search_document: `
prefixes as recommended by the [Ollama model page](https://ollama.com/library/nomic-embed-text-v2-moe).
Both rewriting and answers used `qwen3.5:latest`. The index permission check and
all **79 regression tests** passed.

| Query language | Nomic alone: top 5 | Nomic + Qwen rewrite: top 5 |
| --- | --- | --- |
| Vietnamese with accents | 12/12 | 12/12 |
| English | 12/12 | 12/12 |
| Vietnamese without accents | 7/12 | 12/12 |

All 12 unaccented queries were rewritten. All 44 rewrite calls across retrieval
and answer checks completed without API errors. Unaccented baseline misses
were WFH, overtime, probation, resignation and expense reimbursement. These are
36 authored demo queries, not held-out production validation. The unaccented
normalizer removes both lowercase `đ` and uppercase `Đ` in this run.

Answer observations (eight checks, conversation writes stubbed):

- Leave and WFH facts were correct in Vietnamese and English.
- HR received the bonus schedule in English.
- Employee bonus response correctly said the authorized excerpts contain no
  schedule, but **refusal detection failed**: `fallback=false` with two unrelated
  context sources. No restricted bonus schedule appeared in that response.
- Both unrelated cake queries were refused with no sources. The Vietnamese
  query received the canned English refusal, so language consistency still fails.
- End-to-end answer latency ranged from **1.81 to 101.12 seconds**, including
  early refusals; the English leave check took 56.69 seconds. Shared Qwen is
  functional but answer latency remains a concern. No RAM usage was measured.

The embedding change is validated on this corpus; the full answer pipeline has
the refusal-metadata and language issues above. No refusal code was changed in
this retest. The model has a documented 512-token input limit; this successful
30-chunk reindex does not establish compatibility with larger documents.

Raw observations: [nomic-bilingual-retest.json](nomic-bilingual-retest.json).

## Adaptive rewriting — 2026-09-24

Enabled `QUERY_REWRITE_ENABLED=true` and `QUERY_REWRITE_MODE=adaptive` in the
local environment. The initial check found rewriting disabled; that direct-only
run reproduced 12/12 Vietnamese, 12/12 English, and 7/12 unaccented Vietnamese.
After enabling adaptive mode, all three groups scored **12/12 top-five matches**.
Only **12 rewrite calls** were needed instead of 36 (**67% fewer**), with no API
errors. All unaccented cases took the rewrite route; the other 24 skipped it.

Observed mean rewrite-plus-retrieval time (excluding the separate baseline
search) was 0.03 seconds for both accented Vietnamese and English, versus
1.97 and 2.27 seconds in the previous always-rewrite run. Unaccented queries
averaged 2.25 seconds versus 2.06 previously. These sequential warm-cache runs
are illustrative, not a controlled latency study. Final answer generation was
not repeated, and its earlier latency/refusal issues remain.

Four additional live checks show remaining limitations:

- `and next year?` with leave history routed to Qwen and asked a clarification.
- `còn thử việc thì sao?` routed to Qwen but did not incorporate the previous
  leave question; follow-up resolution is not yet reliable.
- `xin nghỉ` asked whether the user meant annual leave or resignation.
- Mixed English/ASCII Vietnamese routed correctly but returned unchanged text.

Routing is heuristic and may miss unfamiliar Vietnamese phrases. The existing
strict word-preservation guard and fallback remain; routing does not guarantee
a useful rewrite. The code default is `always` for compatibility; `.env.example`
selects `adaptive`. Disable with mode `off` or the existing enabled flag.

Validation: the full suite passed **106 tests**, then three adaptive failure
cases were added and the adaptive test file was rerun. Raw observations:
[adaptive-rewrite-retest.json](adaptive-rewrite-retest.json).
