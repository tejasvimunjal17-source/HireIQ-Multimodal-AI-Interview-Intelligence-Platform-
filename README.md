# HireIQ — Multimodal AI Interview Intelligence Platform

CODE-A-NOVA Internship · Project 4 · 10-Day Sprint
**Current status: Day 3 of 10 — audio processing (PyDub) and asynchronous transcription (Celery + Whisper providers), on top of the Day 1 foundation and the Day 2 interview UI.**

HireIQ will conduct AI-driven interviews: candidates record audio answers, the system transcribes them (Whisper), scores them against a YAML rubric using an LLM, adds NLP enrichment, and produces PDF reports and a hiring-manager dashboard. **Day 1 built the foundation** (API, database, queue, Docker). **Day 2 added the candidate interview screen and audio upload.** Whisper, LLM scoring, NLP, PDF and the hiring-manager dashboard come on later days.

> HireIQ assists human reviewers. It must never be treated as an automatic hiring decision.

## What exists today (Day 1)

| Area | Status |
|---|---|
| FastAPI app, Swagger UI, CORS, settings, error handling | Implemented |
| `GET /`, `GET /health`, `GET /health/db`, `GET /health/redis` | Implemented |
| 7 SQLAlchemy models + Alembic initial migration | Implemented |
| Celery + Redis config, demo task `hireiq.ping` | Implemented |
| Dockerfile + Docker Compose (backend, postgres, redis, worker) | Written; verified by CI only (see `docs/PROGRESS.md`) |
| GitHub Actions CI (pytest with real Postgres/Redis, compose smoke test) | Written; runs after you push |
| React 18 + TypeScript + Vite candidate interview UI (welcome, questions, timer, progress, recorder, preview, submit) | Implemented (Day 2) |
| `GET /api/interviews`, `POST /api/sessions`, `GET /api/sessions/{id}`, `POST /api/sessions/{id}/responses`, `POST /api/sessions/{id}/complete` | Implemented (Day 2) |
| PyDub audio preparation (mono / 16 kHz / normalized), validation, bounded decoding | Implemented (Day 3) |
| Transcription providers: `mock`, OpenAI Whisper API, local open-source Whisper | Implemented (Day 3). **Real Whisper never run yet** (no API key / model here) |
| Celery task `hireiq.transcribe_response`, status/list/retry endpoints, UI status panel | Implemented (Day 3) |
| LLM scoring, NLP, PDF, hiring-manager dashboard, rubric UI | **Not started** (Day 4–8) |

## Tech stack
Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2 · Alembic · PostgreSQL 16 · Redis 7 · Celery 5 · Docker Compose.
(React/Vite, Whisper, PyDub, spaCy, VADER, ReportLab, GPT-4o/Gemini are added on their scheduled days.)

## Folder structure
```
hireiq/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app factory
│   │   ├── core/              # config.py, database.py, logging.py
│   │   ├── models/            # 7 SQLAlchemy models
│   │   ├── schemas/           # Pydantic schemas
│   │   ├── api/routes/        # HTTP endpoints
│   │   ├── services/          # business logic (health checks today)
│   │   └── workers/           # Celery app + tasks
│   ├── alembic/               # database migrations
│   ├── tests/
│   ├── requirements.txt / requirements-dev.txt
│   └── pytest.ini
├── frontend/                  # Day 2: React 18 + TS + Vite candidate UI
│   └── src/ (components, pages, hooks, services, types, styles, utils, test)
├── docs/                      # PROGRESS.md, ARCHITECTURE.md
├── .github/workflows/ci.yml
├── docker-compose.yml  Dockerfile  .env.example  .gitignore
```
(`config/` for rubrics and `scripts/` will be added when they contain real files.)

## Environment variables
Copy the template and edit it. **Never commit `.env`.**
```bash
cp .env.example .env
```
| Variable | Meaning |
|---|---|
| `DATABASE_URL` | Used when running the API directly (not Docker). Docker builds its own URL. |
| `POSTGRES_USER / PASSWORD / DB` | PostgreSQL container credentials. Replace the `change-me` password. |
| `REDIS_URL` | Celery broker + result backend. |
| `SECRET_KEY` | Random string. Generate: `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Production refuses weak keys. |
| `OPENAI_API_KEY`, `GEMINI_API_KEY` | Leave empty until Day 4. Server-side only. |
| `CORS_ORIGINS` | Comma-separated allowed frontend URLs. |

## Run with Docker Compose (PC / server / CI)
```bash
cp .env.example .env          # then edit .env
docker compose up --build     # starts postgres, redis, backend (runs migrations), worker
```
Open http://localhost:8000/docs (Swagger UI). Check:
```bash
curl localhost:8000/health
curl localhost:8000/health/db      # 503 if PostgreSQL is not reachable
curl localhost:8000/health/redis   # 503 if Redis is not reachable
docker compose exec backend python -c "from app.workers.tasks import ping; print(ping.delay('hi').get(timeout=20))"
docker compose down            # add -v to also delete database data
```

## Run without Docker (needs your own PostgreSQL + Redis)
```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
export DATABASE_URL=... REDIS_URL=... SECRET_KEY=...   # or use a .env file
alembic upgrade head
uvicorn app.main:app --reload                          # API
celery -A app.workers.celery_app.celery_app worker --loglevel=info   # worker (second terminal)
```

## Tests
```bash
cd backend
pytest -v                       # unit tests (SQLite stand-in; integration tests are skipped)
RUN_INTEGRATION=1 pytest -v     # also runs real PostgreSQL/Redis tests (services must be running)
```
Test labels: **mocked** (test double), **static** (reads repo files), **integration** (real services, skipped by default).

### Android / Termux note
Docker and PostgreSQL are impractical in Termux. Instead, **push to GitHub**: the `CI` workflow runs all tests with real PostgreSQL and Redis and a Docker Compose smoke test. Open the repo's **Actions** tab to see the result (green = passed).

## API docs
Swagger UI: `/docs` · ReDoc: `/redoc` · OpenAPI JSON: `/openapi.json`


---

# Day 2 — Candidate interview UI and audio recording

## How it fits together
```
Browser (React)  --JSON/multipart-->  FastAPI  --SQLAlchemy-->  PostgreSQL
 MediaRecorder                         |  temp audio file (private volume/dir)
                                       '-- dispatch_transcription()   --> Celery transcription task (Day 3)
```
Audio is recorded in the browser with the native **MediaRecorder** API, previewed, and uploaded per question. After upload the answer is queued for **asynchronous transcription** (Day 3, see below); `transcription_status` moves `pending` -> `processing` -> `completed`/`failed`. Scoring of transcripts does not exist yet.

## Frontend setup
Needs Node.js 18+ (20 recommended).
```bash
cd frontend
cp .env.example .env.local      # optional; defaults work with the local backend
npm install
npm run dev                     # http://localhost:5173
```
Other commands: `npm run typecheck`, `npm test`, `npm run build`, `npm run preview`.

| Variable (frontend/.env.local) | Meaning |
|---|---|
| `VITE_API_BASE_URL` | Backend URL, default `http://localhost:8000`. |
| `VITE_DEMO_MODE` | `true` = built-in SAMPLE interview, nothing is sent or stored. A yellow banner is shown. Useful for previewing the UI without a backend. |
| `VITE_UPLOAD_TIMEOUT_MS` | Upload timeout, default 60000. |

Never put API keys in `VITE_*` variables: they are visible in the browser.

## Backend setup for Day 2
1. Start the stack as in Day 1 (`docker compose up --build`) or run the API directly.
2. Create the sample interview (sample data, clearly labelled):
   ```bash
   docker compose exec backend python -m app.scripts.seed_demo
   # without Docker:  cd backend && python -m app.scripts.seed_demo
   ```
3. Make sure `CORS_ORIGINS` includes the frontend address (default `http://localhost:5173`).

New backend variables: `AUDIO_MAX_UPLOAD_MB` (default 25), `AUDIO_TEMP_DIR` (Docker: `/var/hireiq/audio_tmp`, a private volume; otherwise `/tmp/hireiq-audio`), `AUDIO_STALE_AFTER_HOURS` (default 24).

## Using the interview screen
1. Open the frontend, read the instructions, choose the interview, enter name + email, tick the consent box, press **Start interview**.
2. For each question: **Start recording** (the browser asks for microphone permission) → speak → optional **Pause/Resume** → **Stop** → listen to the preview → **Submit answer** (or **Record again**).
3. Recording stops automatically at the question's time limit. The top bar shows elapsed time and (if configured) time left.
4. **Previous/Next** move between questions (locked while a recording waits to be submitted). **Finish interview** unlocks once every question is answered.
5. After a page refresh, the interview resumes where you left off (the session id is kept in `sessionStorage`).

## Browser microphone notes
- The microphone only works on **https://** pages or **http://localhost**. Opening the dev server from a phone via `http://192.168.x.x:5173` will show "secure pages only". Use HTTPS (e.g. a tunnel) or test on the same device via localhost.
- If you blocked the microphone, allow it in the browser's site settings and press **Try again**.
- Chrome/Edge/Firefox record WebM/Opus; Safari records MP4/AAC. The server accepts webm, ogg, mp4, mp3 and wav.

## API endpoints (Day 2)
| Method + path | Purpose | Notable errors |
|---|---|---|
| `GET /api/interviews?limit=20` | Active interviews with questions (limit 1–50) | 422 bad limit |
| `POST /api/sessions` | JSON `{interview_id, candidate_name, candidate_email, consent:true}` → session + questions | 404 unknown interview, 409 session already exists for that email+interview, 422 invalid input / no consent |
| `GET /api/sessions/{id}` | Session, questions, `answered_question_ids` (used to resume) | 404 |
| `POST /api/sessions/{id}/responses` | `multipart/form-data`: `question_id`, `duration_seconds` (optional), `audio` file → `201 {response_id, question_id, transcription_status:"pending", size_bytes, content_type}` | 400 empty, 404 session/question, 409 already answered or interview submitted, 413 too large, 415 type/content not allowed, 422 bad fields |
| `POST /api/sessions/{id}/complete` | Marks the session `submitted` when all questions are answered (idempotent) | 409 if questions remain |

Interactive docs: `/docs`.

## Audio upload safety rules (implemented)
- Declared MIME type must be on an allow-list **and** the file's first bytes must match that format (a text file renamed `.webm` is rejected).
- Size limit (`AUDIO_MAX_UPLOAD_MB`) enforced twice: from the `Content-Length` header before parsing, and while streaming to disk.
- The browser's filename is never used; files are stored as `<server-generated-uuid>.<ext>` in a private directory (mode 0700, files 0600), outside any served path. There is no URL that returns audio.
- Audio is temporary. Since Day 3 the worker deletes it right after the transcript is stored; the exact rules (including failures) are in **Audio retention and deletion policy** below. Anything older than `AUDIO_STALE_AFTER_HOURS` is purged at API/worker start-up.
- If saving to the database fails, the stored file is removed.

## Testing (Day 2)
```bash
cd backend  && pip install -r requirements-dev.txt && pytest -v       # backend (Day 1 + Day 2)
cd frontend && npm install && npm run typecheck && npm test && npm run build
```
GitHub Actions (`.github/workflows/ci.yml`) runs backend tests with real PostgreSQL/Redis, the frontend type-check/tests/build, and the Docker Compose smoke test (including seeding the sample interview).
Frontend tests use **mocked** MediaRecorder/microphone/XMLHttpRequest/backend. They do not prove a real microphone works.

## Known limitations (Day 2)
- No candidate authentication: the session id (an unguessable UUID) is the only credential. Add login/invite links before real use.
- One session per email per interview; there is no "retake" and no admin screen yet (Day 7–8).
- If a request has no `Content-Length` (chunked), only the streaming check applies; put a body-size limit on your reverse proxy in production.
- Audio of failed transcriptions is kept for recovery until the stale purge removes it (see the retention policy).
- Chrome-recorded WebM previews may show a duration of `0:00` before playing (a known browser quirk); the app shows its own measured duration.
- Not tested on a real phone microphone or in Safari/Firefox.


---

# Day 3 — Audio processing and asynchronous transcription

## What happens after an answer is uploaded
```
Browser -> POST /responses -> FastAPI saves audio (private temp dir) + DB row (pending) -> 201 {task_id}
                                   |
                                   '-> Redis -> Celery worker: claim row -> PyDub (mono/16k/normalize)
                                                -> provider (mock | openai | local) -> save transcript
                                                -> delete raw audio -> status "completed"
Browser polls  GET /api/sessions/{id}/transcriptions  (pending -> processing -> completed | failed)
```
The upload request never waits for transcription.

## Transcription providers (`TRANSCRIPTION_PROVIDER`)
| Value | What it does | Needs |
|---|---|---|
| `mock` (default) | Returns clearly fake text `[MOCK TRANSCRIPT] ...`. **No speech recognition.** The UI labels it "placeholder". Refused when `ENVIRONMENT=production`. | nothing |
| `openai` | Official OpenAI Whisper API (`whisper-1`, `verbose_json`) via the server only. | `OPENAI_API_KEY` in the server `.env` / GitHub Secret |
| `local` | The open-source Whisper model (the brief's "OpenAI Whisper (open-source model)") on this machine. | `pip install -r backend/requirements-whisper-local.txt` (PyTorch, large), ffmpeg |

Adding another provider: subclass `TranscriptionProvider` (`backend/app/services/transcription/base.py`) and register it in `factory.py`.

## Environment variables (new)
| Variable | Default | Meaning |
|---|---|---|
| `TRANSCRIPTION_PROVIDER` | `mock` | `mock`, `openai` or `local` |
| `OPENAI_API_KEY` | empty | Required when provider is `openai`. Never put it in the frontend. |
| `OPENAI_TRANSCRIPTION_MODEL` | `whisper-1` | Model name sent to the API |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Only change for a proxy / compatible endpoint |
| `LOCAL_WHISPER_MODEL` | `base` | tiny / base / small / medium / large |
| `TRANSCRIPTION_LANGUAGE` | empty (auto) | Force a language such as `en` |
| `TRANSCRIPTION_TIMEOUT_SECONDS` | 120 | HTTP timeout for the provider |
| `TRANSCRIPTION_MAX_RETRIES` | 3 | Automatic Celery retries for temporary errors |
| `TRANSCRIPTION_MAX_ATTEMPTS` | 6 | Automatic + manual attempts in total |
| `TRANSCRIPTION_STUCK_MINUTES` | 30 | After this long in "processing", the answer may be re-queued |
| `AUDIO_MAX_DURATION_SECONDS` | 600 | Longer recordings are rejected |
| `AUDIO_MIN_DURATION_MS` | 300 | Shorter recordings are rejected |
| `AUDIO_STALE_AFTER_HOURS` | 24 | Retention limit for any audio left on disk (see policy) |

## Audio retention and deletion policy
| Situation | What happens to the raw audio |
|---|---|
| Transcription succeeded (also "no speech") | **Deleted immediately**, but only after the transcript was committed to the database. |
| The file itself is bad (empty, too short/long, corrupt, spoofed) | **Deleted immediately.** Retrying cannot help. |
| Temporary failure that exhausted its retries, provider misconfigured, ffmpeg missing | **Kept** so the answer can be re-queued once the cause is fixed. |
| Anything still on disk after `AUDIO_STALE_AFTER_HOURS` (24 h) | **Purged** when the API or a worker starts (also scratch folders left by crashed workers). |
Intermediate files live in a per-attempt scratch folder (`<audio dir>/.work/<response-id>-xxxx/`) that is always removed after the attempt. Audio never goes into the database and is never served by any URL. Logs contain ids, error codes and text lengths only, never transcripts.
**Limitation:** the stale purge runs at start-up; a long-running API/worker does not re-run it. Restart or add a scheduled job (Day 10) for strict 24 h enforcement.

## Safety against duplicate or crashed work
- Upload stores a unique `celery_task_id` once (`UPDATE ... WHERE celery_task_id IS NULL`); a second dispatch for the same answer queues nothing.
- A worker only processes a row whose `celery_task_id` equals its own task id; the claim and every result write are guarded `UPDATE`s. A task that lost ownership discards its result and does not delete the audio.
- `acks_late` + `reject_on_worker_lost`: if a worker dies, the task is redelivered with the same id and resumes.
- If Redis is down at upload time, the upload still succeeds (`task_id: null`); `POST .../transcription/retry` queues it later.

## New / changed API endpoints
| Endpoint | Purpose |
|---|---|
| `POST /api/sessions/{id}/responses` | (Day 2) now also returns `task_id` |
| `GET /api/sessions/{id}/transcriptions` | Status of every answer in the session (used for polling) |
| `GET /api/sessions/{id}/responses/{response_id}/transcription` | Status of one answer |
| `POST /api/sessions/{id}/responses/{response_id}/transcription/retry` | `202`; re-queue a failed / never-queued / stuck answer while its audio still exists (`409` otherwise) |
`status` is `pending`, `processing`, `completed` or `failed`. The transcript is returned only when `completed`.

## Database changes (migration `0002_transcription_fields`)
Adds to `candidate_responses`: `transcript_language`, `transcription_provider`, `transcription_attempts` (default 0), `transcription_started_at`, `transcription_completed_at`, `no_speech_detected` (default false). It only adds columns, so existing data is untouched. Apply with `alembic upgrade head` (Docker does it on start-up).

## Running the worker
Docker: the `worker` service runs it. Without Docker (needs Redis + PostgreSQL, ffmpeg installed):
```bash
cd backend && celery -A app.workers.celery_app.celery_app worker --loglevel=info
```
The API and the worker must share the same `AUDIO_TEMP_DIR` (Docker uses the `audio_tmp` volume).

## How to test transcription
1. **Pipeline with the mock provider** (no key needed; proves API -> Redis -> worker -> PostgreSQL):
   ```bash
   docker compose up --build -d
   docker compose exec -T backend python -m app.scripts.smoke_pipeline
   ```
   It uploads a generated tone, waits for the worker and checks that the raw audio was deleted. This is NOT speech recognition.
2. **Real Whisper API** (needs your key): put `TRANSCRIPTION_PROVIDER=openai` and `OPENAI_API_KEY=...` in `.env`, restart, then run the smoke script with a real recording of you speaking:
   ```bash
   docker compose exec -T backend python -m app.scripts.smoke_pipeline --audio /path/answer.webm --show-text
   ```
   Or run the manual GitHub workflow **Real Whisper API test** (Actions tab) after adding the `OPENAI_API_KEY` repository secret. It only checks that the real request succeeds with a generated tone; accuracy (word error rate) needs real speech (Day 10).
3. Unit tests: `cd backend && pytest -v` (needs ffmpeg for the WebM/OGG/MP4/MP3 tests, otherwise those are skipped).

## Frontend (Day 3)
After **Submit answer** the page shows: queued -> "Transcribing your answer..." (spinner) -> the transcript (with language and length), "No speech detected", or a failure message with a **Try transcribing again** button when recovery is possible. Placeholder (`mock`/`demo`) text is labelled as not real recognition. Status is polled (0.8 s, then 2 / 3 / 5 s) only while something is unfinished, for at most 5 minutes (then a "Check again" button appears).

## Known limitations (Day 3)
- **Real Whisper (API or local) has not been run.** Only mock and fake-server tests exist.
- PyDub itself, ffmpeg-based WebM/OGG/MP4/MP3 decoding inside the pipeline, Celery with a real broker, PostgreSQL and Docker were not executed in the build environment; CI is the first real run.
- The decode step has no per-file CPU time limit other than the Celery soft limit (10 min).
- Near-silent recordings (< -60 dBFS average) are treated as "no speech" and not sent to the provider; very quiet real speech could be affected.
- Sessions are protected only by the unguessable session id; a candidate can see their own transcript and trigger retries (limited by `TRANSCRIPTION_MAX_ATTEMPTS`).
- Transcripts are not scored yet (Day 4). Speech recognition errors and accent bias must be documented in the bias review (Day 9).


---

<!-- VERIFICATION-STATUS:START -->
# Running the checks, and what has really been executed (state at end of Day 3)

## Commands
| What | Command (from the repo root) |
|---|---|
| Backend tests (Day 1-3) | `cd backend && pip install -r requirements-dev.txt && pytest -v` (install `ffmpeg` first, otherwise the WebM/OGG/MP4/MP3 tests are skipped) |
| Backend incl. real PostgreSQL/Redis tests | `cd backend && RUN_INTEGRATION=1 pytest -v` (services must be running) |
| Frontend tests | `cd frontend && npm install && npm test` |
| TypeScript type-check | `cd frontend && npm run typecheck` |
| Production build | `cd frontend && npm run build` (runs the type-check first) |
| Docker pipeline smoke test | `docker compose up --build -d && docker compose exec -T backend python -m app.scripts.smoke_pipeline` |
GitHub Actions (`.github/workflows/ci.yml`) runs all of the above on every push. **That is the first place where most of them run for real.**

## Executed in the build sandbox vs only written
Executed: 22 transcription-provider tests (own mini-runner, real HTTP against a local fake server, NOT pytest); real-Chromium browser runs with a fake microphone against a mock backend (Day 2 and Day 3 flows, 32 checks); ffmpeg decoding of a real Chrome recording; partial strict TypeScript check (stand-in types); static checks (syntax, imports, migrations vs models, TS vs Pydantic contracts, YAML, secret scan).
Written but **not executed** (packages cannot be installed offline): all pytest functions (184), all Vitest `it` blocks (99), `npm run build`, real-typings `tsc`, PyDub, Celery with a real broker, PostgreSQL, Docker Compose, and any real Whisper call. Details: `docs/PROGRESS.md`.
<!-- VERIFICATION-STATUS:END -->
