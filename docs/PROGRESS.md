# HireIQ Progress Log

## Day 1 — Backend foundation and infrastructure

**Status: code written; NOT yet executed.** The build sandbox had no internet, so FastAPI, SQLAlchemy, Celery, pydantic and pytest could not be installed, and Docker/PostgreSQL/Redis were unavailable. Nothing below is marked "passed" unless it was actually run.

### Objectives (official brief, Day 1)
FastAPI scaffold · PostgreSQL schema · Docker Compose (app + PostgreSQL + Redis + Celery worker) · GitHub repo.

### Implemented (written, not yet run)
- FastAPI app factory, settings (Pydantic Settings), CORS from env, safe 500 handler, Swagger UI.
- Endpoints: `GET /`, `GET /health`, `GET /health/db`, `GET /health/redis` (the last two do real connections and return HTTP 503 on failure). `/health/redis` is a small addition beyond the three required endpoints.
- Models: Candidate, Interview, Question, InterviewSession, CandidateResponse, Evaluation, Report + Alembic migration `0001_initial_schema`.
- Celery app (Redis, JSON-only, acks_late, prefetch 1, time limits) and demo task `hireiq.ping` with retry/backoff.
- Dockerfile, `docker-compose.yml`, `.env.example`, `.gitignore`, `.dockerignore`.
- GitHub Actions CI (`.github/workflows/ci.yml`) — an addition so tests and Docker can be verified for real from an Android-only workflow.

### Files created
`backend/app/**` (core, models, schemas, api, services, workers), `backend/alembic/**`, `backend/tests/**` (9 files), `backend/requirements*.txt`, `backend/pytest.ini`, `Dockerfile`, `docker-compose.yml`, `.env.example`, `.gitignore`, `.dockerignore`, `README.md`, `docs/ARCHITECTURE.md`, `docs/PROGRESS.md`, `.github/workflows/ci.yml`.

### Checks that WERE actually run (sandbox, no packages)
| Check | Result |
|---|---|
| Python syntax (`ast.parse`) on all 40 `.py` files | 0 errors |
| Internal imports: 124 `from app...` / `from tests...` names resolve to real modules/names | 0 problems |
| `docker-compose.yml` and `ci.yml` parse as YAML | OK |
| Compose assertions (services, healthchecks, depends_on, service-name URLs, no hardcoded passwords, DB/Redis not published) | PASS (same logic as `test_docker_compose_is_consistent`, run ad hoc) |
| `.env.example` has all 9 required keys, API keys empty; matching Settings fields exist | PASS |
| Regex scan for real-looking API keys in all files | none found |
| Migration columns vs model columns (regex cross-check, all 7 tables) | match |
| Fresh-extraction of the ZIP and re-run of the checks above | see final report |

### Tests
- **Test functions written: 62** (about 71 cases after parametrization).
- **Executed: 0. Passed: 0. Failed: 0.** pytest was not installable here.
- Skipped by design when run locally: 4 integration tests (need `RUN_INTEGRATION=1`).

| Type | Tests |
|---|---|
| Unit, real code (SQLite stand-in where a DB is needed) | config, schemas, models, DB config, migrations, API |
| Mocked | `test_health_redis_ok_with_fake_redis_client`, `test_demo_task_runs_in_eager_mode` |
| Static (repo files) | `test_repo_files.py` (6) |
| Real integration (CI only) | PostgreSQL reachable, migration up/down on PostgreSQL, Redis ping, Celery broker connection |

### Real vs mocked integrations
- Real PostgreSQL / Redis / Celery worker / Docker Compose: **not verified yet.** They will be exercised by CI after you push.
- The Celery task has been designed for a real worker, but the end-to-end worker run is only checked in the CI job `docker-compose-smoke`.

### Known risks (because nothing was run)
- Hand-written migration + model agreement is checked by `test_upgrade_creates_all_tables_and_matches_models`; a first-run failure there is possible and should be fixed, not skipped.
- Pinned dependency versions were chosen from memory and could not be resolved offline; bump a pin if `pip install` complains.

### Remaining limitations
- No authentication yet; no CRUD endpoints (not required on Day 1).
- Interview deletion behaviour with existing sessions relies on DB `RESTRICT`; not unit-tested.

### Day 2 preparation (React interview UI)
Needs: Node 20+ on the build environment, a decision on how a candidate session is created (Day 2 adds minimal `POST` endpoints for interview/question listing and audio upload), CORS origin `http://localhost:5173` (already allowed).
**Before Day 2, push Day 1 and make CI green.**


---

## Day 2 — React interview interface and browser audio recording

**Status: implemented and partly verified. Vitest and pytest were NOT executed (packages cannot be installed offline); the React app WAS run in a real Chromium browser.**

### Objectives
Candidate-facing React 18 + TypeScript + Vite UI; MediaRecorder recording; upload to FastAPI; safe temporary audio storage; a clean hook for Day 3 (no Whisper/Celery audio logic yet).

### Implemented
- Frontend: welcome/instructions/consent form, question display (technical/behavioral), progress bar, elapsed + remaining timer, recorder (start, pause, resume, stop, preview, record again), submit with upload progress and retry, Previous/Next, finish, completion page, resume after refresh, demo mode (clearly labelled sample data).
- Recorder error handling: unsupported browser, insecure (non-HTTPS) page, permission denied, no microphone, microphone busy, interruption, empty/too-short recording, automatic stop at the question time limit.
- Backend: `GET /api/interviews`, `POST /api/sessions`, `GET /api/sessions/{id}`, `POST /api/sessions/{id}/responses`, `POST /api/sessions/{id}/complete`; audio validation (type allow-list + magic bytes, size limit twice), server-generated filenames, private temp dir, stale-file purge at start-up, cleanup on DB failure; sample-interview seeder (`python -m app.scripts.seed_demo`).
- Infra: private `audio_tmp` volume shared by backend and worker; new env vars; CI jobs for frontend and sample seeding.

### Files
Created: `frontend/**` (config files, 24 files under `src/` including 2 test helpers, plus 6 test files), `backend/app/api/routes/{interviews,sessions}.py`, `backend/app/schemas/interview.py`, `backend/app/services/{audio_intake,session_service,transcription_dispatch,demo_seed}.py`, `backend/app/core/upload_limit.py`, `backend/app/scripts/seed_demo.py`, `backend/tests/{test_audio_intake,test_interview_api,test_seed_demo}.py`.
Modified (Day 1 files, additive only; verified by diff against the Day 1 zip: 45 of 54 Day 1 files byte-identical, none missing): `.env.example`, `Dockerfile`, `docker-compose.yml`, `.github/workflows/ci.yml`, `backend/app/main.py`, `backend/app/core/config.py`, `backend/requirements.txt`, `backend/tests/conftest.py`, `backend/tests/test_repo_files.py`, plus README/docs. No Day 1 test was removed or weakened.

### What was actually executed (and results)
| Check | Result |
|---|---|
| Real Chromium (Playwright) + fake microphone device, full interview flow against a **mock** backend server (not FastAPI): 4 questions recorded, paused/resumed, retaken, submitted, finished | Passed. Server received 4 real WebM files (header `1a45dfa3`, ~15-18 KB each), multipart fields as expected. No page errors. |
| Real Chromium failure/layout checks (HTTP 500 + retry, network drop, double-click = one upload, refresh-resume, too-short recording, no device, MediaRecorder removed, insecure origin, 375px viewport no overflow, buttons >= 44px) | 15/15 passed |
| Stub/simulated browser events in real Chromium (NotAllowedError via stubbed getUserMedia; mic track `ended` event dispatched; auto-stop at a 3 s limit with real recording) | 4/4 passed. The first two are **simulated**, not a real denied prompt or unplugged microphone. |
| Ad-hoc run of the real `audio_intake.py` code (fastapi import stubbed): all 5 formats, spoofed content, empty, oversized, exact limit, file modes, delete, purge | 18/18 passed (this is NOT pytest) |
| Partial strict TypeScript check (`tsc` 6.0.3, `noUnused*`, with stand-in types for React/Vitest, all 29 .ts/.tsx files) | 0 errors. Partial: real `@types/react` could not be installed |
| esbuild bundle of the app (React 19 dev build used locally because React 18 is not installed here) | Built (1.1 MB dev bundle) |
| 45 relative imports resolve; 53 Python files parse; compose + CI YAML parse | OK |
| Frontend types vs Pydantic schemas (6 pairs), URLs, multipart field names | All match |
| Secret scan, `.env` exclusion | None found |

### NOT executed
| Item | Why |
|---|---|
| Vitest: 72 `it` blocks written (about 80 cases with `it.each`) in 6 files | vitest/jsdom/testing-library could not be installed |
| pytest: 104 backend test functions (Day 1 + Day 2), including 42 new | fastapi/sqlalchemy/pytest could not be installed |
| `npm run build` (Vite, React 18) and `npm run typecheck` with real types | vite and `@types/react` unavailable |
| Real PostgreSQL / Redis / Docker Compose | not available here; CI covers them after you push |

### Real vs mocked
- Real: Chromium MediaRecorder + XMLHttpRequest multipart upload, using Chromium's **fake audio device** (a generated tone, not a human voice).
- Mocked: the backend in browser runs (a Python stand-in that re-implements the same validation rules), all Vitest tests (microphone, MediaRecorder, XHR and API are test doubles).
- Never tested: a physical microphone, a real phone, Safari, Firefox, a genuine permission-denied prompt (headless Chromium has no prompt UI and reports `NotSupportedError`, which the app shows as "not supported").

### Findings fixed during this work
- `sh` does not expand `{a,b}` in `mkdir`, which created wrongly named folders; they were removed and recreated.
- NotSupportedError from `getUserMedia` is now mapped to "unsupported" instead of "unknown".
- Several fragile test helpers were simplified; explicit types were added to handlers so the code also type-checks with real React/Vitest typings.

### Remaining limitations
See the README section "Known limitations (Day 2)". Also: the mock-backend browser runs do not prove the FastAPI endpoints behave the same; run CI to confirm.

### Day 3 preparation (audio pipeline) - historical note, all items were implemented in Day 3
Needs: add `ffmpeg` to the Dockerfile; add `pydub` and `openai-whisper` (and PyTorch CPU) to requirements; a `transcribe_response(response_id)` Celery task that calls `find_audio_path`, normalizes with PyDub, runs Whisper, saves `transcript`/`transcript_segments`, sets `transcription_status`, then `delete_audio`; retries on failure; status polling endpoint for the frontend; replace the log line in `dispatch_transcription`. **Before Day 3, push Day 2 and make CI green.**


---

## Day 3 — PyDub audio processing and asynchronous Whisper transcription

**Status: implemented and partly verified. pytest was NOT run (cannot be installed offline). Real Whisper (API or local) was NEVER run (no API key, no model).**

### Implemented
- Audio: PyDub pipeline (format sniffing, bounded decode, min/max duration, mono, 16 kHz, 16-bit, silence detection, peak normalization), scratch folders, stale-folder purge.
- Providers: `mock`, `openai` (Whisper API over HTTP, retry-aware error mapping, key never leaked), `local` (open-source Whisper, optional install), factory + settings validation (mock refused in production, openai needs a key).
- Celery: task `hireiq.transcribe_response` (retries with back-off, max retries, soft/hard time limits, acks_late), DB-guarded claim/finish (no duplicate or concurrent processing), dispatch with duplicate prevention, worker-start purge.
- API: `task_id` in the upload receipt; list/single status and retry endpoints; friendly error messages.
- DB: migration `0002_transcription_fields` (add-only).
- Frontend: polling hook, `TranscriptionPanel` (queued / processing / transcript / no speech / failed + retry / timed out / refresh error), demo-mode simulation.
- Infra: ffmpeg in the Docker image, new env vars in compose and `.env.example`, `smoke_pipeline` script, CI: ffmpeg install, frontend job, pipeline smoke test, manual `real-whisper.yml` workflow using a GitHub Secret.

### Files
Created (backend): `services/audio_processing.py`, `services/transcription/{__init__,base,mock_provider,openai_provider,local_provider,factory}.py`, `services/transcription_{service,dispatch,status}.py` (dispatch replaced the Day 2 stub), `workers/transcription_tasks.py`, `scripts/smoke_pipeline.py`, `alembic/versions/0002_transcription_fields.py`, `requirements-whisper-local.txt`; tests `test_audio_processing`, `test_transcription_{providers,service,tasks,api}`, `test_config_transcription`, `test_openai_real`, helpers `helpers_audio`, `builders`, `fake_openai`.
Created (frontend): `hooks/useTranscriptions.ts`, `components/TranscriptionPanel.tsx`, `test/flow.tsx`, tests `useTranscriptions`, `TranscriptionPanel`, `App.transcription`.
Created (CI): `.github/workflows/real-whisper.yml`.
Modified: `core/config.py`, `models/candidate_response.py`, `schemas/interview.py`, `services/{audio_intake,session_service}.py`, `api/routes/sessions.py`, `workers/celery_app.py`, `requirements.txt`, `pytest.ini`, `Dockerfile`, `docker-compose.yml`, `.env.example`, `.github/workflows/ci.yml`; frontend `types/interview.ts`, `services/{api,demoApi}.ts`, `pages/InterviewPage.tsx`, `styles/global.css`, `test/helpers.ts`; tests `conftest.py` (api_client now also patches the dispatcher: additive), `test_migrations.py`, `test_repo_files.py`.
**Existing tests:** none removed. Two Day 1/2 tests were adjusted for intentional changes: `test_migrations.test_there_is_exactly_one_migration_head` (head is now `0002`, plus it checks `0002` descends from `0001`) and the `api_client` fixture (so uploads use a fake queue instead of Redis). The Day 2 test that spies on `dispatch_transcription` is unchanged and still valid.

### Tests written
- Backend: **184 test functions** (Day 2: 104; Day 3: +80) in 19 files.
- Frontend: **99 `it` blocks** (Day 2: 72; Day 3: +27) in 9 files.

### What was actually executed
| Check | Kind | Result |
|---|---|---|
| `test_transcription_providers.py`: 22 cases (OpenAI provider vs a real local HTTP server that imitates the endpoint; mock provider; local provider with a fake `whisper` module) | **Custom mini-runner** (`pytest` stand-in kept outside the repo), real HTTP via `requests`, service is a TEST DOUBLE | 22 passed, 0 failed (factory test excluded: needs pydantic) |
| Real Chromium + fake mic against a MOCK backend: transcription UI (queued, processing, transcript, placeholder badge, polling stops, next question usable, failure + retry, status endpoint failing then recovering, mobile 375 px no overflow) | real browser, mock server simulates status | 13/13 passed |
| Day 2 browser regression suites on the Day 3 bundle | real browser, mock server | upload flow OK (4 WebM uploads), 15/15, 4/4 |
| Real Chrome-recorded WebM: `validate_source_file` accepts it; renamed `.wav` is rejected; ffmpeg decodes it (duration field is `N/A`, decoded 2.46 s) | real code + real ffmpeg | as expected |
| Partial strict TypeScript check (stand-in React/Vitest types) incl. all new frontend and test files | static | 0 errors |
| 75 Python files parse; 293 `app`/`tests` import names resolve; migration columns match model; TS types match Pydantic (4 pairs); routes match; Celery task registered/included; YAML parses; secret scan clean | static | all OK |

### NOT executed
| Item | Why |
|---|---|
| All 184 pytest functions (incl. PyDub tests, service/task/API/migration tests) | fastapi, sqlalchemy, celery, pydub, pytest not installable offline |
| All 99 Vitest `it` blocks | vitest/jsdom/testing-library not installable offline |
| `npm run build`, real-typings `tsc` | vite / `@types/react` unavailable |
| Real OpenAI Whisper call; local Whisper | no API key / model / network; `test_openai_real.py` is skipped by design |
| PyDub itself; Celery + Redis worker; PostgreSQL; Docker Compose; Alembic 0002 on a real DB | not available here; CI is the first real run |
| Physical microphone / real phone | never tested |

### Real vs mocked (summary)
Real: HTTP client code against a local fake server; Chromium recording and UI; ffmpeg decoding of a real recording; `validate_source_file`. Mocked: every transcription provider result in service/task tests, the Celery broker (a list), the backend in browser runs, all Vitest tests. Real Whisper: **not tested**.

### Risks to check first in CI
1. `test_audio_processing` (first real PyDub run), `test_migrations` (new batch downgrade on SQLite), Celery eager retry behaviour in `test_transcription_tasks`.
2. If `pip install` rejects a pin (`pydub==0.25.1`, `requests==2.32.3`), bump it.
3. `docker compose` build needs network for `apt-get install ffmpeg`.

### Day 4 preparation (LLM evaluation engine)
Transcripts are now stored per answer (`transcript`, `transcript_segments`, `no_speech_detected`). Day 4 needs: YAML rubric loader (`config/rubrics/*.yaml`), prompt templates with the bias-avoidance instruction, Pydantic schema for LLM JSON, evaluation Celery task chained after `completed`, `evaluations` rows (table exists), handling of `no_speech_detected` (score 0 with explanation, not a model call). **Push Day 3 and make CI green first.**
