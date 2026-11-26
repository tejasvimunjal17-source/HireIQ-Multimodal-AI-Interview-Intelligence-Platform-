# HireIQ — Multimodal AI Interview Intelligence Platform

HireIQ is a CODE-A-NOVA Month 2 internship project. Candidates answer interview questions by voice in the browser; the system transcribes the audio, scores each answer against a configurable YAML rubric with a language model, adds advisory NLP insights, produces a PDF evaluation report and shows hiring managers a dashboard.

> **HireIQ assists human reviewers. Its scores and recommendations are advice, never an automatic hiring decision.** See `docs/BIAS_AND_FAIRNESS_REVIEW.md` before using it with real candidates.

**Project status (Day 10): code-complete, documented and deployment-ready. It has NOT been deployed anywhere** (no cloud account or Docker daemon was available) **and large parts have never been run against real services** (PostgreSQL, Redis, Celery, Whisper, a real LLM). Exact test status: `docs/FINAL_PROJECT_REPORT.md` section 8 and `docs/DAY9_TESTING_REPORT.md`. The per-day development log (Days 1–9) follows this overview.

## Problem statement
First-round interviews are slow to schedule, hard to compare and often scored inconsistently. HireIQ explores a structured alternative: every candidate gets the same questions, every answer is scored against the same written rubric with quoted evidence, and a human reviewer sees scores, evidence and an advisory recommendation in one place.

## Objectives
1. Record and transcribe spoken interview answers.
2. Evaluate each answer against a configurable, validated rubric and keep the evidence.
3. Add advisory NLP context (keywords, entities, sentiment, a confidence heuristic) that never changes the score.
4. Produce a PDF report per session and a manager dashboard.
5. Make rubrics and questions manageable through configuration.
6. Keep fairness, privacy and honest limitations visible.

## Main features (what is implemented)
| Area | Implemented | Verified here |
|---|---|---|
| Candidate interview UI (consent, questions, timer, MediaRecorder, preview, upload, transcript status) | Yes | component tests written; browser smoke test only for the dashboard (mock API) |
| Audio processing (PyDub/ffmpeg, validation) and asynchronous transcription (`mock`, OpenAI Whisper API, local Whisper) | Yes | audio/Whisper paths blocked (no packages/model/credentials) |
| LLM evaluation (mock, OpenAI) against YAML rubrics, evidence check, weighted scoring, retries | Yes | pipeline/schema/prompt logic tested offline; engine and Celery task not run |
| NLP enrichment (spaCy keywords/entities, VADER sentiment, confidence heuristic) — advisory only | Yes | logic tested with fakes; real spaCy/VADER not run |
| PDF evaluation report (ReportLab) behind a bearer token | Yes | renderer tested for real; HTTP route not run |
| Hiring manager dashboard (`/#/dashboard`, token gate, filters, pagination, details, PDF download) | Yes | schemas tested; UI smoke-tested against a **mock** API |
| Rubric tooling and manager-only question bank API | Yes | rules tested offline; API/DB/migration not run |
| Docker Compose stack: postgres, redis, backend, worker, frontend (nginx) | Yes (frontend container added Day 10) | `docker compose config` validated; **images never built, stack never started** |

## Technology stack
Frontend: React 18, TypeScript, Vite · Backend: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic · Database: PostgreSQL 16 · Queue: Celery 5 + Redis 7 · Speech: OpenAI Whisper (API or local) · Evaluation: OpenAI chat model (default `gpt-4o`) or the built-in mock provider (Gemini is only a reserved setting, **no Gemini provider is implemented**) · NLP: spaCy, VADER · Audio: PyDub + ffmpeg · PDF: ReportLab · Containers: Docker, Docker Compose, nginx.

## Architecture overview
```mermaid
flowchart LR
  B[Browser: React app] -->|JSON / audio upload| API[FastAPI]
  M[Hiring manager: dashboard] -->|Bearer token| API
  API --> DB[(PostgreSQL)]
  API -->|enqueue| R[(Redis)]
  R --> W[Celery worker]
  W -->|prepare audio, transcribe| ASR[Whisper: mock / API / local]
  W -->|score with rubric| LLM[LLM: mock / OpenAI]
  W --> NLP[spaCy + VADER, advisory]
  W --> DB
  API -->|ReportLab| PDF[PDF report]
```
Details: `docs/ARCHITECTURE.md`.

## Directory structure
```
hireiq/
├── backend/
│   ├── app/            main.py, core/, models/, schemas/, api/routes/, services/ (evaluation, nlp, reporting, rubrics, transcription, ...), workers/, scripts/
│   ├── alembic/        migrations 0001-0004
│   ├── config/rubrics/ YAML rubrics (default.yaml)
│   ├── tests/          pytest suites (unit, API, bias, security, e2e)
│   └── requirements*.txt, pytest.ini
├── frontend/           React app (src/components, pages, hooks, services, types), Dockerfile, nginx.conf
├── docs/               ARCHITECTURE, DEPLOYMENT_GUIDE, USER_GUIDE, DEMO_SCRIPT, FINAL_PROJECT_REPORT, PROGRESS, BIAS_AND_FAIRNESS_REVIEW, DAY9_TESTING_REPORT, RUBRICS_AND_QUESTION_BANK
├── .github/workflows/  ci.yml, real-whisper.yml
└── docker-compose.yml  Dockerfile (backend image)  .env.example  .dockerignore
```

## Installation requirements
Docker route: Docker Engine + Compose v2. Local route: Python 3.12, Node.js 20, PostgreSQL 16, Redis 7, ffmpeg. Optional: spaCy model (`backend/requirements-nlp-model.txt`), local Whisper (`backend/requirements-whisper-local.txt`), an OpenAI API key for real transcription/evaluation.

## Environment setup
```bash
cp .env.example .env     # never commit .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # -> SECRET_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # -> REPORT_ACCESS_TOKEN (>= 16 characters)
```
Edit `.env`: set `POSTGRES_PASSWORD`, `SECRET_KEY` and (to use the dashboard/PDF/question bank) `REPORT_ACCESS_TOKEN`. The defaults use the **mock** transcription and evaluation providers, so no paid API key is needed to try the application. Every variable is explained in `docs/DEPLOYMENT_GUIDE.md` section 3.

## Run with Docker (recommended)
```bash
docker compose up --build -d
docker compose exec backend python -m app.scripts.seed_demo     # sample interview
```
Candidate app http://localhost:3000 · manager dashboard http://localhost:3000/#/dashboard · API docs http://localhost:8000/docs.
The backend container runs `alembic upgrade head` before starting. *This exact sequence has not been executed by the author's environment (no Docker daemon); the CI job `docker-compose-smoke` is the intended first check.* Troubleshooting: `docs/DEPLOYMENT_GUIDE.md`.

## Run locally without Docker
```bash
# terminal 1: PostgreSQL and Redis must already be running
cd backend && python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt -r requirements-nlp-model.txt
export DATABASE_URL=postgresql+psycopg://USER:PASSWORD@localhost:5432/hireiq REDIS_URL=redis://localhost:6379/0 SECRET_KEY=... REPORT_ACCESS_TOKEN=...
alembic upgrade head && python -m app.scripts.seed_demo
uvicorn app.main:app --reload
# terminal 2
celery -A app.workers.celery_app.celery_app worker --loglevel=info
# terminal 3
cd frontend && npm install && npm run dev        # http://localhost:5173
```

## Database migrations
`alembic upgrade head` (head = `0004_question_bank_fields`; chain 0001 → 0002 → 0003 → 0004, checked statically). **No migration has been executed against a real database by the author.** Verification steps and troubleshooting are in `docs/DEPLOYMENT_GUIDE.md` section 5.

## API documentation
Swagger UI `/docs`, ReDoc `/redoc`, OpenAPI JSON `/openapi.json`. Public candidate routes: `/api/interviews`, `/api/sessions...`. Manager routes (bearer token): `/api/reports/{session_id}/pdf`, `/api/dashboard/...`, `/api/question-bank/...`. Health: `/health`, `/health/db`, `/health/redis`.

## Testing
```bash
cd backend && pytest -v                       # needs the project dependencies; SQLite stand-in for the database
RUN_INTEGRATION=1 pytest tests/test_integration_services.py    # needs real PostgreSQL + Redis
cd frontend && npm install && npm run typecheck && npm test && npm run build
```
Honest status of what was actually run in the authoring sandbox (no network): `docs/FINAL_PROJECT_REPORT.md` section 8.

## Demo
Script: `docs/DEMO_SCRIPT.md` (5–7 minutes). With the default **mock** providers the transcripts are fixed placeholder text and the scores are placeholder scores: the demo shows the workflow, not real speech recognition or real AI judgement. Real behaviour needs `TRANSCRIPTION_PROVIDER=openai`, `EVALUATION_PROVIDER=openai` and an `OPENAI_API_KEY`.

## Known limitations (summary)
Not deployed; most runtime integrations never executed; manager access is one **shared bearer token** (not per-user authentication, no rate limiting); no Gemini provider; no question/interview editing or question-bank UI; no frontend lockfile; transcripts and candidate details are stored without a retention policy; fairness has not been validated with real data. Full list: `docs/FINAL_PROJECT_REPORT.md` section 12.

---

# Development log (Days 1–9)
The sections below are the original per-day notes, kept unchanged for traceability (they describe each milestone as it was delivered).

**Historical status line (written at Day 9; the current status is Day 10, see the top of this file):** Day 9 of 10 completed (see "Day 9" below). The older paragraph that follows describes the state at earlier milestones.

## Day 1 notes (original text)
CODE-A-NOVA Internship · Project 4 · 10-Day Sprint
**Status at Day 9 (historical; Day 10 has since been completed, see the top of this file): Day 9 of 10 completed (end-to-end, security and bias review; see "Day 9" below; Day 10 NOT started). Day 8 of 10 — rubric tooling and question bank implemented (see "Day 8" below and `docs/RUBRICS_AND_QUESTION_BANK.md`; rubric/schema tests ran, the database and API paths did NOT run). Day 7 — hiring manager dashboard implemented (see "Day 7" below; verified in a real browser against a MOCK API only; backend dashboard endpoints and the vitest/pytest suites were NOT run). Day 6: PDF evaluation report implemented (see "Day 6" below; the PDF renderer is tested with real ReportLab, the database/API route has NOT been run). Day 5: NLP enrichment implemented (see "Day 5" below; real spaCy/VADER and database paths not yet executed). Day 4 (accepted by the project owner as code-complete): Phases 1–3 are implemented: YAML rubric, response schema, prompt builder, and now the evaluation providers (mock + OpenAI), weighted scoring, the evaluation engine, persistence and the `hireiq.evaluate_response` Celery task. The OpenAI path has NOT been run against the real API, and the database/Celery tests were written but could not be executed in the build sandbox. Runtime verification of FastAPI, PostgreSQL, Alembic and Celery is still pending (see "Remaining Day 4 work").** Days 1–3 (foundation, interview UI, PyDub + asynchronous Whisper transcription) are unchanged.

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
| YAML rubric file (`backend/config/rubrics/default.yaml`), validated loader, technical/behavioral selection, evaluation settings | Implemented (Day 4, Phase 1) |
| Pydantic evaluation response schema + evidence grounding check (`app/schemas/evaluation.py`) | Implemented (Day 4, Phase 2) |
| Evaluation prompt builder (`app/services/evaluation/prompt_builder.py`) | Implemented (Day 4, Phase 2) |
| Evaluation providers (mock/OpenAI), weighted scoring, engine, persistence, Celery evaluation task, transcription/session coordination | Implemented (Day 4, Phase 3); DB/Celery tests written, **not executed** in the sandbox; real OpenAI call **not made** |
| End-to-end tests, security and bias review (Day 9) | **Completed, awaiting independent approval** (no application code changed; live-service paths blocked) |
| Rubric tooling + question bank API (Day 8) | **Implemented** (database/API path not run; see Day 8) |
| Hiring manager dashboard (Day 7) | **Implemented** (see Day 7; real backend/DB path not run) |
| PDF evaluation report (Day 6) | **Implemented** (renderer tested; route not run, see Day 6) |
| NLP, PDF, hiring-manager dashboard, rubric UI | **Not started** (Day 5–8) |

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
`backend/config/rubrics/` (YAML rubric files) and `backend/app/services/rubrics/` (validation models + loader) were added in Day 4 Phase 1.

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
| `OPENAI_API_KEY`, `GEMINI_API_KEY` | Leave empty unless a provider that needs them is selected. Server-side only. |
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

# Day 4 (in progress) — Phase 1: YAML rubric and evaluation configuration

**Scope of Phase 1 (done): rubric files, rubric validation/loading, evaluation settings. Not done: everything that calls a language model** (prompt template, Pydantic response parser, providers, scoring, grounding, Celery evaluation task, API). Day 4 is therefore **not complete**.

## Rubric files
`backend/config/rubrics/<name>.yaml`. `Interview.rubric_name` (e.g. `default`) selects the file; `Question.rubric_key` (`technical` / `behavioral`) selects a block inside it. If a question has no `rubric_key`, its question type is used. A rubric has a `score_scale` (default 0–10) and, per question type, criteria with: `key`, `name`, `description`, `weight`, `strong_examples`, `weak_examples` and `score_ranges` (bands that must cover the scale with no gap or overlap). **All weights and wording live in the YAML, not in Python.** To change scoring, edit the YAML (or add another file) — no code change.

## Validation rules (`app/services/rubrics`)
- Unknown or misspelled keys, missing fields, wrong types (a quoted `"0.5"` or `true` is not a weight) are rejected, each with its location, e.g. `question_types.technical.criteria.0.weight: ...`.
- Criterion weights in a block must sum to 1.0 (tolerance 1e-6, floating-point noise only). They are **never normalised automatically**.
- Score ranges must start at the scale minimum, end at the scale maximum, and neither overlap nor leave gaps.
- YAML is read with a safe loader (no Python object tags) that also rejects duplicate keys; file size is capped; the rubric name must match `^[a-z0-9][a-z0-9_-]{0,63}$` (blocks `../` path tricks) and must equal the name inside the file.
- Errors are `RubricNotFoundError`, `RubricFormatError`, `RubricValidationError`, `RubricKeyError` (all `RubricError`).

## New settings (all optional; see `.env.example`)
| Variable | Default | Meaning |
|---|---|---|
| `EVALUATION_PROVIDER` | `mock` | `mock` or `openai`. **`mock` is refused when `ENVIRONMENT=production`** (also when the variable is simply not set). `openai` needs `OPENAI_API_KEY`. |
| `EVALUATION_MODEL` | `gpt-4o` | Model name (max 100 characters; will be stored in `evaluations.llm_model`). |
| `EVALUATION_TIMEOUT_SECONDS` | `60` | 5–300. |
| `EVALUATION_MAX_RETRIES` | `3` | 0–10 automatic retries. |
| `EVALUATION_RETRY_BACKOFF_SECONDS` | `5` | 1–300 base delay. |
| `RUBRICS_DIR` | *(unset)* | Folder with rubric YAML files; unset = `backend/config/rubrics`. |

`OPENAI_API_KEY` / `GEMINI_API_KEY` stay `SecretStr`, server-side only; nothing is exposed to the frontend. These settings are passed to the backend and worker in `docker-compose.yml`. **Existing tests changed:** because production now also refuses mock evaluation, the two existing tests that build a valid production configuration now name real providers (assertions unchanged) — see `docs/PROGRESS.md`.

## Dependencies
`PyYAML==6.0.2` was added to `backend/requirements.txt` (the file the Docker image installs). It was already pinned in `requirements-dev.txt`, which only CI uses.

## Tests added (Phase 1)
`tests/test_rubric_loader.py` (23 functions), `tests/test_rubric_validation.py` (31), `tests/test_config_evaluation.py` (17): 71 functions, 131 cases. Run: `cd backend && pytest -v tests/test_rubric_loader.py tests/test_rubric_validation.py tests/test_config_evaluation.py`. They need no database, Redis or network.

## Known limitations (Day 4, Phase 1)
- Rubrics are validated and loadable, but **nothing uses them to score an answer yet**.
- The Docker image build and the real-`pydantic-settings` run of these tests were not possible in the build sandbox; CI is the first full run. See `docs/PROGRESS.md`.
- Gemini is not an evaluation provider yet (`EVALUATION_PROVIDER=gemini` is rejected); the `GEMINI_API_KEY` setting is kept for later.
- Rubric content (examples, bands) is a starting point and has not been reviewed for fairness by a human; the bias review is planned for Day 9.

---

# Day 4 (in progress) — Phase 1 correction and Phase 2: response schema and prompt builder

Day 4 is **not complete**. Done so far: Phase 1 (rubric + settings), the Phase 1 immutability correction, Phase 2A (response schema) and Phase 2B (prompt builder). Still pending: evaluation providers, weighted scoring, orchestration and database writes, the Celery task, the API, real-API verification.

## Phase 1 correction: rubrics are now immutable all the way down
A review found that the frozen rubric models still exposed mutable nested lists and dicts. Now, after validation, lists are tuples and `Rubric.question_types` is a read-only mapping; collections are copied during validation, so editing the source dict later cannot change a loaded rubric. YAML format, validation rules and technical/behavioral selection are unchanged; `model_dump()`, JSON round-trip, `deepcopy` and `pickle` still work.

## Phase 2A: evaluation response schema — `backend/app/schemas/evaluation.py`
What a model must return for one answer (provider-independent):
`overall_score`, `criteria_scores[]` (`criterion_key`, `score`, `explanation`, `evidence_quotes[]`), `strengths[]`, `areas_for_improvement[]`, `summary`, `recommendation`.

- **Strict structure:** required fields, exact types (a score is a whole number: `"7"`, `7.5`, `true` are rejected), no extra fields, length limits, `recommendation` must be exactly `proceed`, `hold` or `reject` (the same values as the existing `Recommendation` enum; a test compares them).
- **Checked against the rubric (an `EvaluationContext` is mandatory):** every rubric criterion present exactly once; no unknown or duplicate criterion; scores and `overall_score` inside the rubric scale. Nothing is clamped, rounded or rescaled.
- **Evidence grounding:** a score above the scale minimum needs at least one quote; every quote must be a contiguous run of words from the transcript (case, punctuation and spacing are ignored; paraphrases, reordered or invented words are rejected); a quote needs at least 3 words (shorter only if the whole answer is shorter). An empty quote list is allowed only at the minimum score ("nothing in the answer earns credit").
- **No weighted overall score is computed.** `overall_score` is the model's own holistic score on the rubric scale; how it is combined with the criterion scores is a later (scoring) decision.
- `parse_evaluation_response(raw_json_or_dict, context)` returns a verified, immutable response or raises `EvaluationParseError` listing every problem. Error messages never contain the transcript or the model's quotes. Strict JSON only: code fences or extra prose are rejected.

## Phase 2B: prompt builder — `backend/app/services/evaluation/prompt_builder.py`
`build_evaluation_prompt(rubric=..., question_text=..., transcript=..., rubric_key=..., question_type=...)` returns an `EvaluationPrompt` (`system`, `user`, prompt/rubric versions, resolved rubric key, criteria keys, and the `EvaluationContext` for validating the model's answer).
- Criteria, descriptions, **weights**, score bands, strong/weak examples and the scale are all read from the YAML rubric. The Python file contains no weights or criteria (a test scans it).
- The system prompt tells the model to: evaluate only the actual answer, follow the rubric, score each criterion independently, explain each score, quote verbatim evidence, never invent evidence, separate "missing" from "incorrect", make no assumptions about identity or circumstances, ignore accent, gender, ethnicity, disability and other irrelevant characteristics, treat the question and transcript as untrusted data (prompt-injection defence), not compute a weighted total, and return only JSON.
- The user prompt contains the question and transcript between unique delimiters (a different delimiter is chosen if the transcript contains the default one; the transcript is never altered), the rubric, the required response shape for exactly this rubric's criteria, and the JSON Schema.
- Empty transcript → `EmptyTranscriptError` (the caller should store a no-speech result instead); oversized transcript → `TranscriptTooLongError` (refused, never truncated); unknown `rubric_key` → `RubricKeyError` (no fallback to another block).

## Tests added in Day 4 Phase 2 (no API key, no network, no database)
`tests/test_rubric_immutability.py` (17 functions, 22 cases), `tests/test_evaluation_schema.py` (57 functions, 144 cases), `tests/test_prompt_builder.py` (35 functions, 63 cases), helper `tests/evaluation_samples.py` (realistic technical and behavioral questions, Whisper-style transcripts). Run: `cd backend && pytest -v tests/test_rubric_immutability.py tests/test_evaluation_schema.py tests/test_prompt_builder.py`.

## Known limitations (Day 4, Phase 2)
- Nothing calls a model yet; the prompt has never been tried against a real model, so its effectiveness (and whether models reliably return quotes that pass the grounding check) is **unverified**.
- The schema carries a per-answer `recommendation`, but the existing `Evaluation` table has no column for it; where it is stored (or whether it is only advisory) is decided in Phase 3. The final report recommendation is still planned to come from rubric thresholds (Day 6).
- `overall_score` is on the rubric scale (0–10 by default) while `evaluations.overall_score` is 0–100: conversion is a Phase 3 task.
- Evidence matching ignores punctuation, so it cannot catch a quote that differs from the transcript only in punctuation.
- Tests ran on pydantic 2.13.5; the project pins 2.10.3 (see `docs/PROGRESS.md`).

<!-- VERIFICATION-STATUS:START -->
# Running the checks, and what has really been executed (state at end of Day 3; Day 4 Phase 1 results are in docs/PROGRESS.md)

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


# Day 4 (in progress) — Phase 3: evaluation providers, engine and Celery task

Day 4 is **not complete**. This phase connects the schema + prompt builder to a model and stores validated results.

## Provider architecture (`backend/app/services/evaluation/providers/`)
`EvaluationProvider.evaluate(prompt) -> ProviderOutput(raw_text, provider, model)`; providers return the model's **raw text only**, the engine validates it, so every provider is held to the same rules. Failures are `EvaluationProviderError(code, retryable, retry_after)` with fixed messages (no key, prompt, transcript or model text).
- **mock** (default; refused in production): deterministic, offline, answers through the same JSON path. Scores are fake.
- **openai**: `POST {OPENAI_BASE_URL}/chat/completions`, JSON mode, `temperature 0`, model = `EVALUATION_MODEL`, key = the existing `OPENAI_API_KEY` (no new key setting), timeout = `EVALUATION_TIMEOUT_SECONDS`. Timeout / connection / 429 / 5xx / unreadable or truncated body are retryable; 401/403, other 4xx, `insufficient_quota` and refusals are permanent.
- Gemini is **not** implemented: add a provider class and one entry in `factory.PROVIDER_BUILDERS`.

Configuration: `EVALUATION_PROVIDER=mock|openai`, `EVALUATION_MODEL`, `EVALUATION_TIMEOUT_SECONDS`, `EVALUATION_MAX_RETRIES`, `EVALUATION_RETRY_BACKOFF_SECONDS`, `RUBRICS_DIR` (all from Phase 1). Nothing new is required in `.env`.

## Workflow
transcription completes → `evaluation_dispatch.after_transcription` (called by the transcription task) → one evaluation task per answer → `engine.run`: claim → load question + the interview's rubric (`interviews.rubric_name`, block = `question.rubric_key` or the question type) → prompt builder → provider → strict JSON parse + schema + rubric + **transcript-evidence** validation → weighted score → one transaction that stores the `Evaluation` and marks the answer `completed` → session status refresh.

| Situation | Behaviour |
|---|---|
| transcription pending/processing | evaluation is not started |
| transcription failed | no evaluation; session refresh (retry via the existing transcription retry) |
| no speech | evaluation `skipped` (`no_speech`), **no model call, no score, no Evaluation row** (a system outcome, not a zero) |
| transcript missing/blank | evaluation `failed` (`transcript_missing`), permanent |
| duplicate delivery | the task id stored in the database must match, and `evaluations.response_id` is unique: nothing runs twice |

Session status (existing `submitted → processing → evaluated | failed`): any unfinished answer ⇒ `processing`, never `evaluated`; all finished, no failures, ≥1 evaluated ⇒ `evaluated`; otherwise `failed` (needs attention, reasons are per answer). Sessions not yet submitted are never advanced. `POST /sessions/{id}/complete` settles the status itself only if every answer is already finished; no API route or response shape changed.

## Weighted scoring
`weighted = Σ(weight_i · score_i) / Σ(weight_i)` on the rubric scale, `overall_score (DB, 0–100) = (weighted − scale_min) / (scale_max − scale_min) · 100`. Weights, criteria and the range come only from the YAML. Invalid scores are rejected, never clamped or rescaled. The model's own holistic `overall_score` is stored for reference but not used. Intermediates are unrounded; rounding (2 decimals) happens only when the row is built.
Example (technical, scale 0–10): scores 8, 7, 6, 9 with weights 0.35, 0.25, 0.20, 0.20 → 2.8 + 1.75 + 1.2 + 1.8 = **7.55** → **75.5**.

## Persistence and the recommendation decision
Existing `Evaluation` columns are reused: `overall_score`, `criteria_scores` (`{criterion_key: {score, weight, weighted_contribution, explanation, evidence_quotes}}`), `explanation` (the summary), `nlp_enrichment` (left NULL, Day 5), `llm_provider`, `llm_model`, `rubric_name`.
**Decision:** the validated recommendation gets a dedicated nullable column `evaluations.recommendation` (same `proceed|hold|reject` enum as the schema) because Day 6 must query/aggregate it; it is not hidden in JSON. The other validated output (strengths, improvements, the model's holistic score, rubric key/version, prompt version) goes into one additive JSON column `evaluations.evaluation_details`. Migration `0003_evaluation_fields` (on top of `0002`, which is untouched) also adds `candidate_responses.evaluation_status | evaluation_task_id | evaluation_attempts | evaluation_error` for the claim and failure codes. This per-answer recommendation is advice for a human; the session-level report recommendation is still Day 6.

## Celery task `hireiq.evaluate_response`
Only the answer id travels through Redis; results carry a status and a code, never text. `acks_late`, no shared in-memory state. Retries are bounded by `EVALUATION_MAX_RETRIES` with backoff `base·2ⁿ` (cap 300 s, honouring `Retry-After`); invalid model output (bad JSON, schema or evidence failure) is retried **once**; permanent failures (missing key/rubric/rubric key, auth, quota, missing transcript) are not retried. A failed answer is recorded with a code and **nothing unvalidated is ever stored**. Logs contain ids and codes only.

## Remaining Day 4 work
Real-API verification of the OpenAI provider (RUN with a key), executing the DB/Celery tests in CI, a read endpoint for evaluations (if the frontend needs one), a decision on exposing the re-queue (`evaluation_dispatch.requeue_failed_evaluation`, currently callable only from code/a shell) as an endpoint, and the Day 4 review. Day 5 (NLP) and Day 6 (report/dashboard) are not started.


## Phase 3 stabilization (what is verified and what is not)
**Implemented:** everything in the Phase 3 section above, plus: (1) the silent 0–100 clamp is gone — the weighted score is range-checked (`scoring.py`) and the persistence mapper raises a controlled `scoring_invalid` failure for any out-of-range value (only ≤1e-9 float noise is tolerated); (2) a database `IntegrityError` is treated as "already evaluated" only if the evaluation row really exists, otherwise the answer fails with `persistence_rejected` and nothing is stored; (3) `evaluation_dispatch.requeue_failed_evaluation(response_id)` re-queues a `failed` evaluation (guarded UPDATE, no Evaluation row can exist for it, normal duplicate protection applies; no endpoint was added); (4) the mock provider only quotes tokens that contain a word character.
**Verified by execution (sandbox):** scoring and the weighted example, range guarantees, persistence mapping, mock determinism, OpenAI request/failure handling against a *fake* HTTP session, provider selection, schema/evidence/JSON validation, the pure state rules — 464 tests passed, 1 skipped, 0 failed (run with `-W error`, a stand-in `pydantic_settings`, no database).
**Verified statically only:** migration `0003` is additive, chains onto `0002`, and every column it adds exists in the models; `0001`/`0002` are byte-identical to the Day 3 archive.
**NOT verified (blocked: no `sqlalchemy`, `fastapi`, `celery`, `alembic`, `redis` and no network in the build sandbox):** backend imports, FastAPI start-up, the migration chain and `0003` upgrade/downgrade, the model-vs-migration comparison, evaluation persistence, duplicate protection, session status updates, no-speech/transcription-failure handling in the database, Celery registration and eager task execution (`tests/test_evaluation_engine.py` and the migration test are written but did not run), and any real OpenAI call.
**Environment needed to run the full pipeline:** Python 3.12 with `backend/requirements.txt` installed (pins include pydantic 2.10.3, SQLAlchemy 2.x, Celery, Alembic, PyYAML), PostgreSQL (or SQLite for the unit tests), Redis for a real worker, `OPENAI_API_KEY` + `EVALUATION_PROVIDER=openai` for real evaluations. Run `cd backend && pytest` in CI first.
**Known limitations:** pydantic 2.10.3 vs the 2.13.5 used here is unchecked; the re-queue has no endpoint or attempt cap; invalid model output gets one retry only. Day 4 is still **not complete**.


# Day 5 — NLP enrichment (spaCy + VADER)

Context for a human reviewer, stored in the existing `evaluations.nlp_enrichment` JSON column. **No migration was needed.** It runs after the LLM evaluation has been validated and scored, and it can never change the score, the recommendation or the criteria.

## Architecture (`backend/app/services/nlp/`, schema in `app/schemas/nlp.py`)
| Module | Role |
|---|---|
| `spacy_backend.py` | the only spaCy import; loads the pip-installed model once per worker, **never downloads** it; gazetteer matcher for technologies |
| `text_analysis.py` | pure keyword and entity selection (no library needed) |
| `sentiment.py` | VADER wrapper + label thresholds |
| `confidence.py` | rule-based confidence signal (pure) |
| `service.py` | orchestrator `enrich()` / `enrich_fields()`; never raises |

## Flow
`LLM output → schema/evidence validation → weighted score → enrich_fields (keywords + entities, sentiment, confidence) → one transaction: Evaluation row incl. nlp_enrichment`. A retry of the LLM call never repeats NLP (it runs only after success); a duplicate delivery cannot create a second row (unchanged Day 4 protection).

## Installation
`pip install -r backend/requirements.txt` (spaCy 3.8.2, vaderSentiment 3.3.2) and then `pip install -r backend/requirements-nlp-model.txt` (model `en_core_web_sm`). The Docker image does both at build time; the CI workflow installs the model too. The app never downloads anything at start-up or run time. Settings: `NLP_ENABLED` (default true; false leaves the column NULL) and `NLP_SPACY_MODEL` (default `en_core_web_sm`; must be a package name, never a path). Without the libraries or the model the evaluation still completes and the column holds a `partial`/`failed` marker with a short code (e.g. `spacy_model_missing`).

## Stored structure (`schema_version` 1)
```
{"schema_version": 1, "status": "completed|partial|failed|skipped", "word_count": 123,
 "keywords": [{"text": "race condition", "count": 1}, ...],              # max 10
 "entities": [{"text": "Kubernetes", "label": "TECHNOLOGY", "count": 2}], # max 20, unique per text
 "sentiment": {"positive","negative","neutral","compound","label","note"},
 "confidence": {"kind": "heuristic", "score": 0..1, "label": "low|moderate|high",
                "indicators": [{"name","value","weight","limitation"}], "unavailable": [...],
                "affects_evaluation": false, "disclaimer": "..."},
 "errors": {"spacy": "spacy_model_missing"}, "models": {"spacy": "en_core_web_sm 3.8.0"}}
```
Each component runs on its own; one failing gives `partial` and the rest are kept; empty transcripts give `skipped`.

## Keywords
Noun phrases and nouns from spaCy, trimmed of determiners/pronouns/stop words, vague nouns removed ("thing", "way", "lot"...), merged per lemma, ranked `(1 + 0.3·ln(count)) · (1 + 0.5·(words−1)) · (1.5 if proper noun)` so frequency counts for little and specific phrases/names win; a single word that only occurs inside a kept phrase is dropped. Lexical only: it cannot tell if a term was used correctly.

## Entities
spaCy NER plus a small built-in technology gazetteer (label `TECHNOLOGY`, whole-word, case-insensitive; no everyday English words). Kept labels: ORG, PERSON, GPE, LOC, FAC, PRODUCT, EVENT, WORK_OF_ART, LAW, LANGUAGE, DATE, TECHNOLOGY. Dropped on purpose: NORP (nationality/religious/political group — a protected-group description) and purely numeric labels. Entities are **not** evidence of competence, and PERSON entries are personal data: they are stored with the evaluation but never logged. The small model misses and mislabels technology names, hence the gazetteer.

## Sentiment (VADER)
Per answer, deterministic. Label from the compound score: ≥ 0.05 positive, ≤ −0.05 negative, otherwise neutral. **Limits:** VADER was built for short English social-media text; it measures the tone of wording only. Technical answers are mostly neutral; words such as "failed", "crash" or "exception" lower the score for reasons unrelated to the candidate; negation and irony are weak spots. It is never used in scoring or in the confidence signal.

## Confidence signal (experimental heuristic)
Five text-only signals, each 0–1, weighted and re-weighted if one is unavailable: completeness 0.25 (words, saturating at 40), structure 0.20 (sentences and linking words), supporting detail 0.25 (keywords + entities + numbers, cap 8), directness 0.20 (question words repeated in the first 40 words), low hedging 0.10 (explicit uncertainty phrases above 3 per 100 words; "I think" is deliberately not counted). Labels: < 0.40 low, < 0.70 moderate, otherwise high. Each indicator carries its limitation in the stored output. **Not used:** sentiment, grammar, spelling, accent, pronunciation, filler words, speech speed, pauses, duration, vocabulary level, names or any personal characteristic. It is labelled a heuristic, has `affects_evaluation: false`, and must not be used to rank or reject people. **Limits:** concise speakers are under-rated by completeness; structure depends on the transcriber's punctuation; hedging phrases are English-only and uncertainty can be honest; directness is lexical.

## Bias and fairness
Nothing demographic is read or inferred. The signal can still correlate with language proficiency or speaking style (for example, shorter answers in a second language), which is why it is advisory-only, documented as experimental, and kept out of scoring. Sentiment and confidence must not be shown to reviewers as quality measures; Day 9's bias review should test them.

## Testing status (Day 5)
See `docs/PROGRESS.md` for exact numbers. Pure NLP logic and the orchestrator were executed; the real spaCy/VADER tests and the database persistence tests are written but **not executed** in the build sandbox (libraries, model and database drivers absent, no network).


---

# Day 6 — PDF evaluation report

One session's **stored** evaluation as a downloadable PDF. Pure reading: no LLM call, no re-scoring, no change to stored evaluations, nothing saved on disk.

## Architecture
`app/services/reporting/`
- `data.py` — plain, sanitising data model (no database, no ReportLab). Malformed or out-of-range stored JSON is dropped and counted, never guessed.
- `loader.py` — reads one session (candidate name, interview, every question with its answer and evaluation) and the optional `reports` row. Read-only; filtered by the requested session id only; e-mail is not loaded.
- `radar.py` — criteria aggregation and the radar chart (ReportLab vector graphics).
- `pdf.py` — the renderer (`render_report(data) -> bytes`), ReportLab only, bundled Bitstream Vera font, "Page X of Y" footer.
- `app/api/routes/reports.py` — the download route.

## PDF contents
Header (HireIQ name, title *Candidate Interview Evaluation Report*, generation time) · candidate information (only fields that exist) · executive summary (overall score, stored recommendation, summary, strengths, improvements) · score summary table · criteria radar chart · per-question evaluation (question, full transcript, score, criterion scores, explanations, evidence quotes) · NLP insights (optional; labelled experimental/advisory; "unavailable" when missing) · stored recommendation · footer on every page (confidentiality notice, page numbers, report name).
- The overall score is the stored value, unchanged (shown as `/ 100`). If no session score is stored, the plain average of the evaluated answers is shown and labelled as such.
- The recommendation is the stored one. If none is stored the report says so and lists the per-answer advice; it never computes a new decision. Sentiment and the confidence indicator play no part.
- A session with unevaluated answers gets a **PARTIAL REPORT** banner with the reason per question. A session with no evaluated answer gets 409 instead of a misleading PDF.

## Radar chart
Each axis = plain mean of the stored criterion score across the evaluated answers that contain that criterion; the axis range is the stored rubric scale (e.g. 0–10). 3–16 criteria are supported. Missing scores are not filled in (the note under the chart lists criteria present in only some answers). No chart (with a stated reason) if there are fewer than 3 criteria, the scale is missing, or answers use different scales.

## Endpoint
`GET /api/reports/{session_id}/pdf` with header `Authorization: Bearer <REPORT_ACCESS_TOKEN>`

| Status | Meaning |
|---|---|
| 200 | `application/pdf`, `Content-Disposition: attachment; filename="hireiq-evaluation-<session_id>.pdf"`, `Cache-Control: no-store`, `X-Content-Type-Options: nosniff` |
| 401 | missing/wrong token (checked before the session lookup) |
| 404 | `Interview session not found.` |
| 409 | no answer of the session has been evaluated yet |
| 422 | `session_id` is not a UUID |
| 503 | `REPORT_ACCESS_TOKEN` not configured (downloads disabled) |

```bash
# in .env:  REPORT_ACCESS_TOKEN=<at least 16 random characters, e.g. from: openssl rand -hex 24>
curl -H "Authorization: Bearer $REPORT_ACCESS_TOKEN" -o report.pdf http://localhost:8000/api/reports/<session_id>/pdf
```
```python
from app.services.reporting.pdf import render_report
pdf_bytes = render_report(report_data)   # report_data from load_report_data(db, session_id) or build_report(...)
```

## Dependencies
`reportlab==4.2.5` (runtime). `pypdf==5.1.0` (dev only, reads PDFs in tests). Nothing else; no browser, no wkhtmltopdf.

## Privacy and security
- **Authorization decision:** the project has no user accounts and a candidate knows their own session id, so the id alone could expose the recommendation. The route therefore needs a shared server-side token (constant-time comparison); unset = disabled. This is a stop-gap until real hiring-manager authentication exists.
- Transcripts, names, questions and explanations are treated as untrusted: markup is escaped, control/bidi characters removed, long tokens broken so nothing is clipped, unsupported glyphs are counted and noted.
- Logs contain only session id, counts and byte size; never names, transcripts or scores.
- The PDF is generated in memory per request: no temp files, no stored duplicates. The file name contains the session id, not the candidate name.
- Candidate e-mail is not read or printed.

## Limitations (Day 6)
- The font (Bitstream Vera) covers Latin scripts only; CJK/Arabic/etc. characters print as `?` and the report says how many.
- Large sessions are rendered synchronously in the request (a 9-page sample with a very long transcript rendered in about 0.3 s in the sandbox), there is no caching.
- Per-answer recommendations are listed, not combined; no weighting between questions exists.
- Output was reviewed on screen only (rendered to images); not printed, not opened in every PDF viewer.
- The route, loader and token dependency have **not been run** (FastAPI/SQLAlchemy not installable offline).

## Testing (Day 6)
`tests/test_report_pdf.py` (40 tests, real ReportLab + pypdf, ran and passed), `tests/test_report_settings.py` (3, ran and passed), `tests/test_report_api.py` (15: loader, endpoint, auth, headers; **written, blocked**). Run `pytest backend/tests/test_report_pdf.py`.


---

# Day 7 — Hiring manager dashboard

Open **`/#/dashboard`** (candidates stay on `/`; no link to the dashboard is shown to them). It reads stored data only: no scoring, no LLM call, nothing is written.

## Access (important)
The API still has **no user accounts**, and the dashboard shows candidate names and evaluations. All `/api/dashboard/*` routes therefore require the same shared secret as the PDF download: `Authorization: Bearer <REPORT_ACCESS_TOKEN>`. The manager **types the token into the dashboard**; it is kept in memory for that tab only (no localStorage/sessionStorage, not in the URL, not in the built JavaScript, not in a `VITE_*` variable). Signing out or refreshing forgets it. If `REPORT_ACCESS_TOKEN` is unset the dashboard API answers 503. **This is a stop-gap, not production-grade authentication or authorization**: everyone who knows the token sees every candidate.

## Features and data sources
| Feature | Source |
|---|---|
| Overview metrics + score distribution | `GET /api/dashboard/summary` |
| Session table, search, filters, pagination | `GET /api/dashboard/sessions` |
| Candidate evaluation view | `GET /api/dashboard/sessions/{id}` (reuses the Day 6 loader) |
| PDF download | existing `GET /api/reports/{id}/pdf`, fetched with the token, saved as `hireiq-evaluation-<id>.pdf`. No PDF logic in the browser |
| Interview/role filter options | existing `GET /api/interviews` |

## How the numbers are calculated (backend `app/services/dashboard.py`)
- **Interview sessions** = all `interview_sessions` rows. **Completed interviews** = status submitted, processing, evaluated or failed (the candidate finished). **Awaiting evaluation** = submitted + processing. **Evaluated sessions** = status `evaluated`. Failed evaluations are shown separately.
- **Session score** = the stored `reports.overall_score` if a Report row exists (nothing writes one yet), otherwise the plain average of the session's stored per-answer `evaluations.overall_score`; the table says which. No score → `null`/"Not scored", **never 0**.
- **Average score** = mean of the per-session scores over scored sessions only (not over answers); the card states how many sessions it covers. **Score distribution** = counts of those session scores in 0-20, 20-40, 40-60, 60-80, 80-100 (100 belongs to the last bucket).
- **Recommendation** column = the stored *session-level* recommendation (`reports.recommendation`, normally empty → "Not recorded"). The stored *per-answer* advice is shown as counts ("Answer advice: Proceed 1 · Hold 1") and is never combined into a new decision.

## Table, search and filters
Columns: candidate (or "Unnamed candidate (id)"), interview, date (completed → started → created), status with "n of m answers evaluated", score + source, recommendation, View. Long names wrap; under 760 px the table becomes stacked cards. Controls (all combine with AND, server-side, 20 per page, any change returns to page 1): candidate-name search (case-insensitive substring, debounced 300 ms, `%`/`_` are literal; e-mail is deliberately not searchable), interview/role, status, "Answer advice" (sessions with at least one evaluated answer carrying that stored advice).

## Visualisations
Score cards, score-distribution columns, per-session criterion bars (mean stored score per criterion on the rubric scale, same aggregation and "no chart if misleading" rules as the PDF radar) and per-answer score bars. Missing values are text, never empty bars.

## Candidate evaluation view
Overall score and its source, interview info, partial-data warning, criteria chart, and per answer: score, stored advice, summary, strengths, improvements, criterion scores with explanations and evidence quotes, and NLP insights labelled **Experimental · advisory** (sentiment = tone of wording only; confidence = heuristic). They never influence a score or recommendation. **Transcripts are not part of any dashboard response** (evidence quotes are); they stay in the PDF.

## API added
`GET /api/dashboard/summary`, `GET /api/dashboard/sessions?search&interview_id&status&recommendation&page&page_size(≤100)`, `GET /api/dashboard/sessions/{session_id}`. Errors: 401 (missing/wrong token), 404 (unknown session), 422 (bad parameters), 503 (token not configured). The listing runs one aggregate query (no per-row queries) and selects no e-mail, transcript, audio path or task id. Existing endpoints and contracts are unchanged; the Day 6 loader was split into `load_session_data` (404 only) and `load_report_data` (adds the 409), and the 401/503 detail texts were made generic.

## Security review (Day 7 audit)
- No token or credential is in the frontend source or bundle; no `VITE_*` token variable; no web-storage writes by the dashboard; no `console.*` calls; the token is not in URLs, error messages or the DOM (browser check).
- User-provided text (names, questions, explanations, evidence quotes) is rendered as React text; there is no `dangerouslySetInnerHTML`/`innerHTML`.
- Responses carry no e-mail, transcript, audio path, task id or provider internals (a schema test checks field names; the NLP block is cut down to what the UI shows). Evidence quotes are short excerpts of the transcript and do appear in the detail view.
- Every dashboard route and the PDF route check the token before touching the database, so an unauthorised caller cannot probe which sessions exist. Errors return the generic FastAPI JSON `detail`.
- All dashboard queries are read-only. Session detail is loaded by the requested id only.
- **Not done / limitation:** one shared token for everyone, no rate limiting or lockout, no audit log, no HTTPS enforcement in the app (use TLS in front of it), token comparison is constant-time but a leaked token exposes all candidates. Do not treat this dashboard as production-secure until real per-user authentication and authorization exist.

## Known limitations (Day 7)
- Shared-token access, no per-user login or audit trail (see above); the token must be re-entered after a refresh.
- No sorting controls (newest first), no candidate comparison view, no export of the table, no auto-refresh of the overview.
- The score distribution and average are computed in Python from one (status, score) row per session: fine for thousands of sessions, not for millions.
- With nothing writing the `reports` table, the session-level recommendation column is empty for real data; the answer-advice filter is the usable recommendation filter.
- Language: English only; dates are shown in UTC.

## Testing (Day 7)
Frontend: `npm test` runs vitest (`utils/dashboard.test.ts`, `services/dashboardApi.test.ts`, `components/dashboard/dashboard.components.test.tsx`, `pages/DashboardPage.test.tsx`, `Root.test.tsx`). Backend: `pytest backend/tests/test_dashboard_api.py backend/tests/test_dashboard_schemas.py`. See `docs/PROGRESS.md` for what has really been executed.


---

# Day 8 — Rubric configuration and question bank

Full guide with examples: **`docs/RUBRICS_AND_QUESTION_BANK.md`**.

**Rubrics.** The Day 4 YAML rubric system already validated names, criteria, weights (sum 1.0), score scales and bands (no gap/overlap) and fed the evaluation pipeline, so it was verified and left unchanged. Day 8 adds `python -m app.scripts.validate_rubrics [folder]` (checks every file with the real loader; exit code 0/1/2) and `app/services/rubrics/catalog.py` (list/validate a folder, describe a rubric without its prompt material, resolve a question's key). A rubric added only as a YAML file is scored by the unchanged pipeline (tested with the mock provider).

**Question bank.** Migration `0004_question_bank_fields` adds three optional columns to `questions` (`category`, `difficulty`, `expected_skills`; additive, existing rows NULL). Manager-only endpoints (same bearer token as the PDF/dashboard routes) under `/api/question-bank`: `GET /rubrics`, `POST /interviews`, `PUT /interviews/{id}/active`, `POST /interviews/{id}/questions`, `GET /questions` (filters: interview, type, category, difficulty, skill, text; pagination), `GET /questions/{id}`. A stored question's rubric key must exist in its interview's rubric, interview type limits question types, text/skills are validated and normalised, duplicates and over-50 questions are refused, and questions cannot be added once candidates have sessions. New interviews start inactive until they have questions. The candidate API is unchanged and does not show the new metadata. Frontend, dashboard, PDF, NLP and scoring code are unchanged.

**Limitations.** Shared-token access (not per-user authentication); no edit/delete of questions or interviews and no UI for the bank; stored evaluations are not re-scored after a rubric edit.

**Testing status.** Executed here and passing: rubric catalog/CLI/pipeline tests, question-bank schema tests and static migration checks (plus all earlier suites that can run offline). Written but **not run** (SQLAlchemy/FastAPI/Alembic unavailable): `tests/test_question_bank_api.py` and the new `test_migrations.py` case. See `docs/PROGRESS.md`.


---

# Day 9 — End-to-end testing, security review and bias review

**Status (as written at Day 9): completed. Day 10 was done afterwards; see `docs/FINAL_PROJECT_REPORT.md`.** No application source file was changed; Day 9 added tests and documents only.

- `docs/DAY9_TESTING_REPORT.md` — environment, exact commands, written/collected/executed/passed/failed/skipped/blocked accounting, workflow coverage, integration and regression results, security summary, limitations.
- `docs/BIAS_AND_FAIRNESS_REVIEW.md` — structured bias review (each finding labelled source-code observation / executed test / needs real-world validation). It does **not** claim HireIQ is unbiased or fair; its output is advice for a human reviewer and must not be used for automated hiring decisions.

**Tests added:** `test_day9_e2e_chain.py` (17), `test_day9_bias_fairness.py` (39), `test_day9_security.py` (36) — **92 executed, 92 passed**; `test_day9_workflow_e2e.py` (6) written but **blocked and never run**.
**Whole offline suite (one run):** 749 collected, 748 passed, 0 failed, 2 skipped; 18 test files blocked at collection (SQLAlchemy/FastAPI/Celery/Alembic missing, about 246 test functions).
**Not verified:** anything needing PostgreSQL, Redis, Celery, Alembic migrations, FastAPI HTTP behaviour, Whisper, a real LLM, spaCy/VADER or the frontend test runner. The "end-to-end chain" test is an in-process simulation with mock providers, not a live workflow. Run commands for the blocked paths are in the testing report.
**Findings needing a decision (documented, not changed):** recommendation not reconciled with score; weak evidence relevance check; missing evidence can become the minimum score; no transcription-quality signal; rubric style assumptions; shared-token access without rate limiting; wildcard CORS accepted in production; no retention policy for candidate data.
