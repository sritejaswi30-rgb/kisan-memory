# KisanMemory

**AI that remembers every field and learns from every season.**

KisanMemory is a long-term memory layer for farm advice: it recalls what actually
happened on *this* farmer's field before it answers, explains which memories it
used, and stores each newly reported outcome so the next answer is smarter.

---

## The farmer's problem

A farmer accumulates real experience every season — which treatment worked, which
one failed, when heavy rain caused waterlogging, when the soil dried out. That
experience lives only in their memory.

A generic chatbot has none of it. It repeats standard advice, ignores what
actually happened on that field, and — crucially — **never learns** when the
farmer reports "that did not work." The lesson is lost the moment the chat ends.

## The solution

KisanMemory gives every farmer a persistent field memory backed by **Hindsight**:

1. **Recall before answering** — every question is matched against the farmer's
   own recorded experiences, not a generic knowledge base.
2. **Show the reasoning** — the answer comes with a *"Why this answer?"* card
   listing the exact memories used, and counters for memories retrieved vs.
   memories actually used.
3. **Learn from new outcomes** — when the farmer reports a new result ("I tried
   Treatment A again, but it did not help"), that experience is extracted,
   duplicate-checked, and retained for every future answer.
4. **Stay personal** — each farmer has an isolated memory bank, so one farmer's
   field history can never surface in another's answer.

## What the judge should notice

- **Persistent memory** — answers are built from a memory bank that outlives the
  conversation; the timeline and "Past field memory" panel show it live.
- **Personalization from field history** — the same question produces different,
  field-specific answers for Ravi (tomato) and Sita (paddy).
- **Learning from new experiences** — a newly reported outcome changes the very
  next answer, and repeats are detected instead of stored twice.
- **Multi-user memory isolation** — one Hindsight bank per farmer
  (`kisan-user-1001`, `kisan-user-1002`); the browser can never name a bank, and
  cross-bank memory sharing is zero.

---

## Why Hindsight?

A normal chatbot keeps *conversation history* — a short, ephemeral transcript of
what was said in the current session. That is not what this project needs:

| Conversation history | Persistent field memory (Hindsight) |
|---|---|
| Lives inside one chat session | Survives across sessions, seasons and devices |
| Stores *what was said* | Stores *what happened on the field* (with dates and metadata) |
| Retried/recycled as text | Semantically recalled: ask about "heavy rain" and the waterlogging memory comes back |
| Nothing is learned after the chat closes | New outcomes are retained and shape future answers |
| One user's transcript | One isolated bank per farmer |

The farmer's value is **accumulated field experience**, not a chat log. Hindsight
is the system of record for that experience: it is durable, queryable by meaning,
and isolated per user — which is exactly why it, and not the chat transcript, is
the core of KisanMemory.

---

## Architecture

```mermaid
flowchart TD
    F["🧑‍🌾 Farmer<br/>Browser UI (vanilla JS)"] -->|"question<br/>X-User-ID header"| API["FastAPI backend<br/>backend/main.py"]

    API -->|"users, fields<br/>structured metadata"| DB[("PostgreSQL<br/>(SQLite fallback)<br/>users / fields")]

    API -->|"1. recall(field history)"| H[("Hindsight<br/>persistent memory<br/>kisan-user-1001 / kisan-user-1002")]
    H -->|"past experiences"| API

    API -->|"2. question + recalled memories"| G["Groq<br/>openai/gpt-oss-120b"]
    G -->|"3. answer + memories used +<br/>new experience candidates"| API

    API -->|"4. retain new experience<br/>(duplicate-guarded)"| H
    API -->|"5. personalized response +<br/>Why-this-answer evidence"| F
```

**Separation of concerns**

| Store | Holds | Never holds |
|---|---|---|
| PostgreSQL / SQLite (`users`, `fields`) | structured profile data: name, language, field, crop, planting date | long-form field experiences |
| Hindsight (one bank per farmer) | field experiences, timeline events, memory metadata | user credentials |

### API surface

| Endpoint | Purpose |
|---|---|
| `POST /chat` | `{field_id, message}` — recall → reason → learn → answer |
| `GET /health` | live Hindsight + LLM connectivity |
| `GET /timeline?field_id=` | dated field events, served from Hindsight |
| `GET /users/me` | current farmer + their fields (`X-User-ID`) |
| `GET /fields` / `POST /fields` | list / create fields for the current farmer |
| `GET /` | the single-page demo UI |

`POST /chat` also accepts the legacy `{farmer, field, message}` body (no header)
so the earlier phase test scripts keep working; that path is a compatibility shim
and is not used by the multi-user UI.

---

## How Hindsight is used

- **Recall** — each question becomes a query (`Farmer Ravi, field Field A: …`)
  and returns relevant past memories (text, type, date).
- **Retain** — newly reported experiences are written back with `context` and
  `metadata` (`experience_hash`, `experience_sig`), which powers duplicate
  detection.
- **List / timeline** — recent memories drive the *Past field memory* panel and
  the dated field timeline.
- **Bank lifecycle** — each farmer's bank is created automatically on startup.

All Hindsight calls happen server-side; the browser never talks to Hindsight and
no API key ever reaches the frontend.

### The memory-learning loop

1. **Recall** — the farmer asks something; Hindsight returns the relevant field history.
2. **Answer** — Groq answers from that history and reports which memories it used.
3. **Learn** — the farmer reports a new outcome; Groq extracts it as a candidate experience.
4. **Guard** — before retaining, `is_duplicate_experience()` checks an in-process
   session set, stored `experience_hash` / `experience_sig` metadata, and an exact
   normalized-text match. Identical repeats are skipped and shown as
   *"already remembered"* instead of being stored twice.
5. **Retain** — genuinely new experiences go into Hindsight, the timeline
   refreshes, and the next answer includes them.

A genuinely new outcome is always retained; the guard only blocks obviously
identical repeats (same day + same field + same treatment, or identical text).

---

## Multi-user architecture

**One isolated Hindsight bank per farmer**

| User | Bank | Seeded history |
|---|---|---|
| `1001` (Ravi) | `kisan-user-1001` | tomato, Field A — rain → waterlogging → fungal symptoms → Treatment A helped, later failed |
| `1002` (Sita) | `kisan-user-1002` | paddy, Field B — irrigation → soil moisture → Treatment C helped, Treatment D failed |

**How a request stays inside one farmer's memory**

1. The browser identifies the farmer with `X-User-ID: 1001`.
2. The backend resolves the user and `field_id` from the database and rejects a
   `field_id` that does not belong to that user (404).
3. The backend derives the bank as `kisan-user-{user_id}` — the client can never
   name a bank directly.
4. Recall and retain happen **only** inside that bank.

---

## Demo story (60–90 seconds)

> **Ravi plants tomatoes in Field A.** In June, heavy rain causes waterlogging and
> fungal symptoms appear. He sprays **Treatment A** — and by 2 July the symptoms
> have reduced. That success is recorded in his Hindsight memory bank.
>
> **Weeks later the problem returns.** Ravi reports: *"I tried Treatment A again
> this time, but it did not help."* KisanMemory stores that as a **new**
> experience — and detects it as new rather than a duplicate.
>
> **Now ask the same question twice.** KisanMemory recalls **both** experiences
> and *distinguishes them*: Treatment A reduced the symptoms after the first
> application on 24 June 2026, but the re-application on 28 September 2026 did not
> improve the plants — so the answer says Treatment A is no longer effective here,
> instead of repeating the old advice.
>
> **Switch the farmer to Sita • Field B.** Her history is paddy, irrigation and
> soil moisture; none of Ravi's tomato memories are reachable, because her
> requests run only against `kisan-user-1002`.

### In the UI

Pick the farmer and field in the selector (the scope line shows
**"Memory scope: Ravi • Field A"**), then use the one-click demo buttons:

1. **"What happened after the heavy rain?"** — reconstructs the real history:
   waterlogging → fungal symptoms → Treatment A helped the first time.
2. **"What have I learned from my previous experiences?"** — states the lessons
   *and* distinguishes the earlier success from the later failure.
3. **🌱 Report: Treatment A did not help** — a new experience is learned: the UI
   shows *NEW MEMORY CREATED* and the timeline gains a new entry.
4. **Repeat step 3 or step 2** — the repeat is detected: *ALREADY REMEMBERED — no
   duplicate created*, and the answer still contrasts success vs. failure.

**↺ Demo Reset** clears the screen only — it never deletes Hindsight memories.

---

## Technology stack

| Layer | Choice |
|---|---|
| Backend | Python, FastAPI, Uvicorn, python-dotenv |
| Database | SQLAlchemy 2 + PostgreSQL (`psycopg`), SQLite fallback for local dev |
| Memory | **Hindsight** (`hindsight-client` SDK) |
| Reasoning | Groq via the OpenAI SDK (`openai/gpt-oss-120b`) |
| Frontend | vanilla HTML, CSS, JavaScript (no framework, no build step) |
| Tests | plain Python scripts (`test_hindsight.py`, `test_agent.py`, `test_isolation.py`) |

---

## Local setup

Requires Python 3.10+.

```powershell
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt
copy .env.example .env            # then fill in your keys
.venv\Scripts\uvicorn.exe backend.main:app --host 127.0.0.1 --port 8055
```

Open **http://127.0.0.1:8055/**. On startup the app creates the tables, seeds
users **1001 Ravi (Field A, tomato)** and **1002 Sita (Field B, paddy)**, creates
their Hindsight banks, and seeds each bank with its own memories. The header
shows live Hindsight / AI connectivity pills.

### Environment variables

| Variable | Purpose |
|---|---|
| `HINDSIGHT_BASE_URL` | Hindsight API base URL |
| `HINDSIGHT_API_KEY` | Hindsight API key |
| `HINDSIGHT_BANK_ID` | Shared/demo bank id (default `kisan-memory`) |
| `GROQ_API_KEY` | Groq API key |
| `GROQ_MODEL` | Model id (default `openai/gpt-oss-120b`) |
| `DATABASE_URL` | PostgreSQL URL (e.g. `postgresql+psycopg://USER:PASSWORD@HOST/DBNAME`). **Optional** — when missing the app uses the local SQLite file `kissanmemory.db`. |

`.env` is git-ignored and never committed. `.env.example` is the empty template.

### Production deployment

```powershell
# 1. provision PostgreSQL and set DATABASE_URL in .env
# 2. install and run behind a process manager / reverse proxy
pip install -r requirements.txt
uvicorn backend.main:app --host 0.0.0.0 --port 8055
```

- Set `DATABASE_URL` to PostgreSQL (the app converts `postgresql://` to
  `postgresql+psycopg://` automatically) — SQLite is only for local development.
- Keep `.env` on the server only; no key is ever shipped to the browser.
- Startup is idempotent: tables, demo users, and Hindsight banks are created if
  missing.
- `GET /health` reports `{"status":"ok","hindsight":…,"llm":…}` for monitoring.

### Tests

```powershell
.venv\Scripts\python test_hindsight.py   # Hindsight connection, bank, retain, recall
.venv\Scripts\python test_agent.py       # end-to-end /chat behaviour
.venv\Scripts\python test_isolation.py   # multi-user memory isolation
```

Validation available without the LLM: `python -m compileall -q backend`,
`node --check frontend/app.js`.

---

## Known limitations

- **`X-User-ID` is a demo identity header, not real authentication.** There is no
  login, session, or token validation; production would replace it with real auth.
- **Groq quota during final verification.** Groq's `openai/gpt-oss-120b` API
  temporarily reached its 200,000-token daily limit during final verification.
  Hindsight connectivity, memory retention/recall, multi-user isolation, frontend
  validation, and compilation were verified successfully. The same application
  flow had previously passed end-to-end before the external quota was exhausted.
- **Demo data is synthetic.** Ravi and Sita, their fields, and their seeded
  experiences are fixtures for the demo — not real farm records.
- **Duplicate guard is best-effort.** It combines an in-process session set
  (resets on restart) with persistent `experience_hash` / `experience_sig`
  metadata in Hindsight and an exact-text match; it targets obvious repeats, not
  semantic near-duplicates.
- **SQLite by default.** PostgreSQL is supported via `DATABASE_URL` but is not
  provisioned for the demo.

Further detail: [`SUBMISSION_STATUS.md`](SUBMISSION_STATUS.md).
