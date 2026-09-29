# KisanMemory — Submission Status

Prepared in submission mode. No application logic, frontend, database, or AI pipeline was changed for this document.

## 1. Project

- **Project:** KisanMemory — farm memory + AI advisor for Indian farmers (Hindsight long-term memory, Groq LLM reasoning).
- **Repository:** `C:\Users\Shre0\OneDrive\Desktop\kissan-memory`
- **Branch:** `master`
- **Current commit:** `0695248` (`0695248d939bd2d84df31d43a3699b82ff9e8a77`) — *feat: UI accuracy, memory presentation, and submission documentation* (previous: `68bab2b`, *feat: complete KisanMemory multi-user MVP*).
- **Working tree:** `README.md` + `frontend/index.html` carry presentation-only edits from the final polish pass (see §10). Nothing was pushed.

## 2. Architecture

```
frontend/            static SPA (index.html, app.js, styles.css) served by FastAPI at /
backend/
  main.py            FastAPI app: /health, /users/me, /fields, /chat, /timeline, /
  groq_agent.py      Groq LLM: system prompt + JSON answer generation
  hindsight_client.py Hindsight SDK wrapper: recall/retain/timeline event extraction
  db.py models.py    SQLAlchemy models + engine (SQLite by default, PostgreSQL via DATABASE_URL)
  seed.py            demo users/fields/bank memories (Ravi 1001, Sita 1002)
test_hindsight.py    Phase 1 Hindsight connectivity (connect → bank → retain → recall)
test_agent.py        chat round-trip checks
test_isolation.py    cross-user isolation assertions
requirements.txt     runtime dependencies
```

Request path: browser → `POST /chat` (`X-User-ID`) → SQLite field/user lookup → Hindsight `recall` (per-user bank) → Groq `answer(...)` → dedupe guard → Hindsight `retain` of genuinely new experiences → JSON response (answer + retrieved/used/retained/history counts).

## 3. Hindsight role

Long-term memory store (Hindsight Cloud SDK `0.10.1`). It is the **source of truth for farm history**:

- `recall` — every `/chat` request retrieves live memories (never fabricated).
- `retain` — stores new farmer experiences, guarded against duplicates.
- `list_memories` / `timeline_entries` — feed the Activity panel and the dated timeline (event labels, kind, counts).
- Banks double as the isolation unit (§6).

No Hindsight code path was modified in submission mode.

## 4. Groq role

LLM reasoning only (`openai/gpt-oss-120b` via OpenAI-compatible endpoint): reads recalled memories and produces a JSON answer (`answer`, `memory_facts_used`, `new_memory_candidates`). The system prompt enforces crop consistency, memory-grounded phrasing, and a ban on chemical/dosage prescriptions. **Groq never stores memories.** Groq is currently rate-limited (§8).

## 5. PostgreSQL role

Optional production database for users/fields (`DATABASE_URL`). SQLAlchemy models are engine-agnostic; with `DATABASE_URL` empty the app falls back to local SQLite (`kissanmemory.db`, gitignored). PostgreSQL was **not** required or configured for this demo submission.

## 6. Multi-user isolation design

- Each user maps to its own Hindsight bank: `bank_for_user(id)` → `kisan-user-<id>` (e.g. `kisan-user-1001`, `kisan-user-1002`).
- Identity is taken from the `X-User-ID` header; all `/fields`, `/chat`, `/timeline` queries are scoped to that user's row + bank.
- Recall, retain, and timeline reads are never issued against another user's bank.
- Verified read-only: 9 memories in `kisan-user-1001`, 8 in `kisan-user-1002`, **0 identical memory texts shared between banks**.

**Known limitation:** `X-User-ID` is a **demo-only identity header, not real authentication** — there is no login, session, or token validation. For production, replace it with real auth.

## 7. Frontend / backend architecture

- **Frontend:** dependency-free static SPA. `index.html` shell, `app.js` (state, fetch to API, Why-This-Answer evidence rows, timeline rendering, activity counters), `styles.css`. Served directly by FastAPI (`GET /`), so a single port is enough.
- **Backend:** FastAPI + Uvicorn. Pydantic request/response models, SQLAlchemy session per request, async Hindsight/Groq clients, per-process duplicate-experience guard, lifespan seeding of demo users/banks.

## 8. Verification results

### PASS — actually verified in this submission run

| Check | Command | Result |
|---|---|---|
| Backend compiles | `python -m compileall -q backend` | PASS (exit 0) |
| Frontend syntax | `node --check frontend/app.js` | PASS (exit 0) |
| Hindsight connectivity test | `python test_hindsight.py` | PASS (exit 0): connection, bank, retention, recall |
| Hindsight read-only check | temp script (no writes) | PASS: version 0.10.1, bank counts 9 / 8, recall works, 0 shared texts |
| Live non-Groq endpoints | `GET /health`, `GET /fields`, `GET /timeline` | PASS: `{"status":"ok","hindsight":true,"llm":true}`, Ravi 7 / Sita 6 timeline events |
| No secrets tracked | `git grep` for key patterns in tracked files | PASS: no matches |
| Ignore rules | `git check-ignore` for `.env`, `.venv/`, `*.db`, `*.log` | PASS: all ignored, none tracked |
| Required files present | backend `*.py`, `frontend/*`, `requirements.txt`, `README.md` | PASS |

### BLOCKED — cannot verify right now (external Groq rate limit)

| Check | Why blocked |
|---|---|
| `test_agent.py` (calls `/chat` → Groq) | Groq HTTP 429 daily token limit |
| `test_isolation.py` (calls `/chat` → Groq) | Groq HTTP 429 daily token limit |
| End-to-end demo scenario (calls `/chat` → Groq) | Groq HTTP 429 daily token limit |

**These are external rate limits, not code failures.** Earlier today, at this same code state, `test_agent.py` and `test_isolation.py` both returned **PASS** (after the user-approved bank clear + reseed), and the end-to-end demo returned **PASS** before the limit was hit. They are reported as BLOCKED above because they cannot be re-run **now**.

### Exact external limitation

```
openai.RateLimitError: Error code: 429
model: openai/gpt-oss-120b
type/code: rate_limit_exceeded  (HTTP 429)
message: tokens per day (TPD): Limit 200000, Used 199274, Requested 2643,
         Please try again in 13m48.144s
```

Recorded from `uvicorn.err.log`; organization id redacted. No further Groq calls were attempted while the limit was active.

## 9. Deployment & environment

**Deployment command (Windows, verified):**

```powershell
python -m venv .venv
.venv\Scripts\pip.exe install -r requirements.txt
.venv\Scripts\uvicorn.exe backend.main:app --host 127.0.0.1 --port 8055
```

Linux/macOS equivalent: `uvicorn backend.main:app --host 0.0.0.0 --port 8055`

**Required environment variables** (copy `.env.example` → `.env`; `.env` is gitignored and **not** included in this submission):

| Variable | Required | Purpose |
|---|---|---|
| `HINDSIGHT_BASE_URL` | yes | Hindsight Cloud endpoint |
| `HINDSIGHT_API_KEY` | yes | Hindsight auth |
| `HINDSIGHT_BANK_ID` | yes | Shared/demo bank name (default `kisan-memory`) |
| `GROQ_API_KEY` | yes | Groq auth (LLM) |
| `GROQ_MODEL` | yes | `openai/gpt-oss-120b` |
| `DATABASE_URL` | no | PostgreSQL URL; empty ⇒ SQLite |

**No secrets are included in this repository or this document.**

## 10. Files changed

**Committed in `0695248` — 7 files, +873/−95:**

```
backend/groq_agent.py       |  16 +-
backend/hindsight_client.py | 296 ++++++++++++++++++++++++---
backend/main.py             |  46 ++++-
frontend/app.js             | 411 +++++++++++++++++++++++++++++++++++++-------
frontend/index.html         |  10 +-
frontend/styles.css         |  45 ++++-
SUBMISSION_STATUS.md        | (new)
```

Content: UI accuracy/memory-presentation work (Why-This-Answer evidence, timeline event granularity, retrieved-vs-used counts, response safety wording, crop consistency) plus this document.

**Uncommitted presentation-only polish (2 files):** `README.md` (competition-facing rewrite: architecture diagram, demo story, "Why Hindsight?", judge checklist, known limitations) and `frontend/index.html` (3 label text tweaks, no logic). Nothing was pushed.

## 11. Submission readiness

- Core application logic, Hindsight architecture, database architecture, frontend, user isolation, and tests were **not** altered in submission mode.
- All validations that do not require Groq: **PASS**.
- Groq-dependent tests: **BLOCKED** by an external 429 quota — re-run them once the daily token limit resets.
