# KisanMemory

**AI that remembers every field and learns from every season.**

## Problem

Farmers accumulate field history — which treatment worked, which failed, when rain caused waterlogging — but that experience lives in memory and is lost across seasons. Generic AI advice repeats itself, ignores what actually happened on *this* field, and never learns when a farmer reports that something did not work.

## Solution

KisanMemory is a farmer's long-term field-memory assistant. It recalls the farmer's own past experiences from a Hindsight memory bank before answering, shows exactly which memories were used and why, and stores each newly reported field outcome back into memory so the next answer is smarter. Repeated reports of the same experience are detected and skipped instead of being stored twice.

## Architecture

```
Browser (vanilla HTML/CSS/JS, frontend/)
    │  POST /chat   GET /health  GET /timeline  GET /
    ▼
FastAPI (backend/main.py)
    ├── Hindsight client (backend/hindsight_client.py)  ── long-term memory
    │       recall → retain (with metadata) → list / timeline
    └── Groq agent (backend/groq_agent.py)              ── reasoning
            answers + new experience candidates (JSON)
```

- `POST /chat` — recalls memories, asks Groq to answer, extracts new field experiences, applies the duplicate guard, retains what is new, returns the answer plus memory metadata.
- `GET /health` — live Hindsight and LLM connectivity.
- `GET /timeline` — field events grouped by date, served from Hindsight.
- `GET /` and `/static/*` — the single-page demo UI.

## MULTI-USER ARCHITECTURE

KisanMemory separates **structured application data** from **long-term experiential memory**.

**PostgreSQL — users / fields / structured application data**

| Table | Columns |
|---|---|
| `users` | `id`, `name`, `preferred_language`, `created_at` |
| `fields` | `id`, `user_id` → `users.id`, `name`, `crop`, `planting_date`, `created_at` |

Only structured profile/application data lives in the database. Long-form field
experiences are **never** stored in PostgreSQL — they belong in Hindsight.
`DATABASE_URL` selects PostgreSQL for deployment; when it is missing the app
falls back to a local SQLite file (`kissanmemory.db`) for development.

**Hindsight — long-term farmer experience and field memory**

One isolated memory bank per farmer, so memories can never leak between users:

| User | Bank |
|---|---|
| `1001` (Ravi) | `kisan-user-1001` |
| `1002` (Sita) | `kisan-user-1002` |

Banks are created automatically on startup if they do not exist, and each demo
user is seeded with different synthetic experiences (Ravi: rain → waterlogging →
fungal symptoms → Treatment A helped, then failed; Sita: paddy → irrigation →
soil moisture → Treatment C helped, Treatment D failed).

**Backend — maps the current user to the correct Hindsight bank**

The browser identifies the current farmer with an `X-User-ID` header
(e.g. `X-User-ID: 1001`). The backend:

1. resolves the user and the requested `field_id` from PostgreSQL and rejects a
   `field_id` that does not belong to that user (404),
2. derives the Hindsight bank as `kisan-user-{user_id}` — the client can never
   name a bank directly,
3. recalls/retains **only** inside that bank.

Every Hindsight call happens server-side; the browser never talks to Hindsight
and no API key ever reaches the frontend.

**Current-user endpoints**

| Endpoint | Purpose |
|---|---|
| `GET /users/me` | current farmer + their fields (requires `X-User-ID`) |
| `GET /fields` | fields of the current farmer |
| `POST /fields` | create a field for the current farmer |
| `GET /timeline?field_id=` | timeline of the current farmer's selected field only |
| `POST /chat` | `{field_id, message}` — farmer derived from `X-User-ID` |

`POST /chat` still accepts the legacy `{farmer, field, message}` body (no
header) so the Phase 3/4 demo scripts keep working; that path is a test
compatibility shim and is not used by the multi-user UI.

## Hindsight's role

Hindsight is the long-term memory store — one bank per farmer (`kisan-user-1001`,
`kisan-user-1002`; the shared `kisan-memory` bank is only used by the legacy test
path). It provides:

- **Recall** — each question becomes a query (`Farmer Ravi, field Field A: …`) and returns relevant past memories (text, type, date).
- **Retain** — new farmer-reported experiences are written back with `context` and `metadata` (`experience_hash`, `experience_sig`), which powers duplicate detection.
- **List / timeline** — recent memories drive the "Past field memory" panel and the field timeline.
- **Bank lifecycle** — the bank is created on startup if missing.

## Groq's role

Groq runs the reasoning model `openai/gpt-oss-120b` through the OpenAI-compatible API. Given the farmer's message plus the recalled memories, it returns a strict JSON object:

- `answer` — the reply grounded in the farmer's own history (not invented events).
- `memory_facts_used` — which recalled memories it actually relied on (the UI turns this into the "Why this answer?" card).
- `new_memory_candidates` — new field experiences the farmer just reported, which become retain candidates.

If structured JSON output fails, the call retries without it and the answer falls back to raw text.

## How the memory-learning loop works

1. **Recall** — the farmer asks something; Hindsight returns the relevant field history.
2. **Answer** — Groq answers from that history and states which memories it used.
3. **Learn** — the farmer reports a new outcome (e.g. "I tried Treatment A again, but it did not help"). Groq extracts it as a candidate experience.
4. **Guard** — before retaining, `is_duplicate_experience()` checks (a) an in-process session set, (b) stored `experience_hash` / `experience_sig` metadata in Hindsight, (c) an exact normalized-text match. Identical recent experiences are skipped and surfaced as *"already remembered"* instead of being stored again.
5. **Retain** — genuinely new experiences are stored in Hindsight, the timeline refreshes, and the next answer includes them.

A genuinely new outcome is always retained; the guard only blocks obviously identical repeats (same day + same field + same treatment, or identical text).

## Local setup

Requires Python 3.10+.

```powershell
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt
copy .env.example .env            # then fill in your keys
```

## Environment variables

| Variable | Purpose |
|---|---|
| `HINDSIGHT_BASE_URL` | Hindsight API base URL |
| `HINDSIGHT_API_KEY` | Hindsight API key |
| `HINDSIGHT_BANK_ID` | Memory bank id (default `kisan-memory`) |
| `GROQ_API_KEY` | Groq API key |
| `GROQ_MODEL` | Model id (default `openai/gpt-oss-120b`) |
| `DATABASE_URL` | PostgreSQL URL for deployment (e.g. `postgresql+psycopg://USER:PASSWORD@HOST/DBNAME`). **Optional** — when missing the app uses a local SQLite file `kissanmemory.db`. |

`.env` is git-ignored — never commit it. `.env.example` holds the empty template.

## How to run

```powershell
.venv\Scripts\uvicorn.exe backend.main:app --host 127.0.0.1 --port 8055
```

Open **http://127.0.0.1:8055/** in a browser. The header shows live Hindsight / AI connectivity pills.
On startup the app creates the tables, seeds users **1001 Ravi (Field A, tomato)** and
**1002 Sita (Field B, paddy)**, creates their Hindsight banks and seeds each bank with
its own synthetic memories.

Optional test suites:

```powershell
.venv\Scripts\python test_hindsight.py   # Phase 1: Hindsight connection, bank, retain, recall
.venv\Scripts\python test_agent.py       # Phase 2: end-to-end /chat behaviour
.venv\Scripts\python test_isolation.py   # Phase 5: multi-user memory isolation
```

## Demo flow

Pick the farmer and field in the selector at the top — the memory scope line shows
**"Memory scope: Ravi • Field A"** (or Sita • Field B) and everything below follows it.

Four steps, all available as one-click demo buttons:

1. **"What happened after the heavy rain?"** — the answer reconstructs the real history: waterlogging → fungal symptoms → Treatment A helped the first time.
2. **"What have I learned from my previous experiences?"** — the model states the lessons *and* distinguishes the earlier success from the later failure.
3. **"I tried Treatment A again this time, but it did not help."** — a new experience is learned: the UI shows *NEW MEMORY CREATED* and the timeline gains a new entry.
4. **Repeat step 3 or step 2** — the repeat is detected: *ALREADY REMEMBERED — no duplicate created*, and the answer still contrasts success vs. failure.

**↺ Demo Reset** clears the screen for the next run. It never deletes Hindsight memories.

Switch the selector to **Sita • Field B**: her history is about paddy, irrigation and
soil moisture — none of Ravi's tomato memories are reachable, because her requests run
only against `kisan-user-1002`.

## Technology stack

- **Backend** — Python, FastAPI, Uvicorn, python-dotenv
- **Database** — SQLAlchemy 2 + PostgreSQL (`psycopg`), SQLite fallback for local dev
- **Memory** — Hindsight (`hindsight-client` SDK)
- **Reasoning** — Groq via OpenAI SDK (`openai/gpt-oss-120b`)
- **Frontend** — vanilla HTML, CSS, JavaScript (no framework)
- **Tests** — plain Python scripts (`test_hindsight.py`, `test_agent.py`)
