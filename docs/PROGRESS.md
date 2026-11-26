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


---

## Day 4 — Phase 1: YAML rubric and evaluation configuration foundation

**Status: Day 4 is NOT complete. Phase 1 is implemented and its new tests pass in a limited sandbox (see exactly what ran below). Phase 2+ (prompt, response parser, providers, scoring, grounding, Celery task, API) has not been started.**

### Baseline before any change (Day 3 code, sandbox without most dependencies)
| Item | Result |
|---|---|
| Backend test functions discovered (static count) | 184 in 19 files; frontend 99 `it` blocks in 9 files |
| `pytest` exactly as CI runs it | **Cannot start**: `conftest.py` imports `sqlalchemy`, which is not installed (no network, so no `pip install`) |
| Missing dependencies | `fastapi`, `sqlalchemy`, `celery` (blocking 13 test files), also `pydantic-settings`, `alembic`, `pydub`, `httpx`, `redis` |
| Executable subset (`--noconftest`, with a local stand-in for `pydantic_settings`, see below) | 6 files, 56 test cases: 54 passed, **1 failed**, 1 skipped |
| Blocked test functions | 138 in 13 files (api, audio_intake, audio_processing, celery_app, database_config, integration_services, interview_api, migrations, models, seed_demo, transcription_api/service/tasks) |
| Frontend tests, Docker, PostgreSQL, Redis, GitHub CI | Not run: npm registry unreachable, no Docker daemon, no Git repository or GitHub access in this workspace |

**Pre-existing Day 3 defect found by running the tests:** `test_config.py::test_production_accepts_strong_secret` failed at baseline. It builds a production configuration with the default transcription provider (`mock`), which Day 3 had started refusing in production. Day 3 never ran this test.

### Implemented in Phase 1
- `PyYAML==6.0.2` added to `backend/requirements.txt` (previously only in `requirements-dev.txt`, so the Docker image would not have had it).
- Settings: `evaluation_provider` (`mock`/`openai`), `evaluation_model`, `evaluation_timeout_seconds`, `evaluation_max_retries`, `evaluation_retry_backoff_seconds`, `rubrics_dir` (+ `rubrics_path`). Mock evaluation is refused in production; `openai` needs `OPENAI_API_KEY`. Existing key fields unchanged (`SecretStr`).
- `.env.example` and `docker-compose.yml` (backend + worker) pass the new settings.
- `backend/config/rubrics/default.yaml`: `technical` (4 criteria) and `behavioral` (4 criteria), scale 0–10, each criterion with description, weight, strong/weak examples, 5 score bands.
- `backend/app/services/rubrics/` (`models.py`, `loader.py`, `__init__.py`): strict Pydantic models, safe YAML loader, selection by `Question.rubric_key` with fallback to the question type.
- No database model or migration was added or changed; the existing `Evaluation` model is to be reused.

### Files
New: `backend/app/services/rubrics/{__init__,models,loader}.py`, `backend/config/rubrics/default.yaml`, `backend/tests/{test_rubric_loader,test_rubric_validation,test_config_evaluation}.py`.
Modified (additive unless stated): `backend/requirements.txt`, `backend/app/core/config.py`, `.env.example`, `docker-compose.yml`, `README.md`, `docs/PROGRESS.md`, `docs/ARCHITECTURE.md`, and two existing tests (below).
**Existing tests modified (assertions unchanged, none removed or skipped):** `test_config.py::test_production_accepts_strong_secret` (fixes the baseline failure by naming real transcription and evaluation providers) and `test_config_transcription.py::test_production_with_a_real_provider_is_accepted` (passed at baseline; needs a real evaluation provider now that production refuses mock evaluation).

### Tests
- **Written:** 71 functions (loader/selection 23, validation 31, settings/packaging 17) = 131 cases. Backend total is now 255 functions.
- **Executed:** all 131 new cases plus the 56 collectable existing cases: **186 passed, 1 skipped (real OpenAI test, by design), 0 failed**. Command: `cd backend && PYTHONPATH=<standin> pytest --noconftest <the 9 collectable files>`.
- **Mutation check:** 10 deliberate breakages of the rubric/config code were applied in a scratch copy (loose weight tolerance, no gap check, no overlap check, extra keys allowed, bool/str weights allowed, mock allowed in production, unsafe YAML loader, no duplicate-key check, no file-name check, no question-type fallback). All 10 are caught by the tests (the unsafe-loader test was strengthened after the first attempt was not caught).
- **Blocked (not executed):** the 138 existing functions in 13 files listed above, all 99 Vitest blocks.

### Limits of this verification (read before trusting "passed")
- `pydantic-settings` could not be installed, so the Settings tests ran against a small **stand-in** of that package (reads environment variables into the real `Settings` class; kept outside the repository). The validators are the real code, but the real library has never run these tests. CI will.
- Python 3.13 sandbox; the project targets 3.12.
- `--noconftest` was used because `conftest.py` needs SQLAlchemy; the new tests do not need its fixtures.
- **Docker was not verified**: no Docker daemon. What is checked statically: runtime `requirements.txt` pins PyYAML, the Dockerfile installs that file and copies `backend/` (including `config/rubrics`), and `.dockerignore` does not exclude it.
- Not verified by any run: everything in the 13 blocked files (these cover Day 1–3 behaviour, so **Day 1–3 regression is only partly verified**), the Alembic migrations, Celery, PostgreSQL.

### Remaining Day 4 work (not started)
Prompt template with explicit bias-avoidance and grounding instructions · Pydantic parser for the model's JSON · evaluation provider interface + mock + OpenAI providers · weighted scoring and grounding checks · orchestration service writing `Evaluation` rows · Celery evaluation task chained after transcription · evaluation API routes · tests for all of it · real-API verification.


---

## Day 4 — Phase 1 correction and Phase 2 (response schema + prompt builder)

**Status: Day 4 is NOT complete.** Phase 1, the Phase 1 immutability correction, Phase 2A and Phase 2B are implemented and their tests pass in a limited sandbox. Providers, scoring, orchestration, the Celery evaluation task and the API are not started. Day 5 is not started.

### Phase 1 correction (from the independent review)
Nested rubric collections were mutable although the models were `frozen`. Fixed in `backend/app/services/rubrics/models.py`: lists → tuples (`FrozenTuple`), `question_types` → read-only mapping (`FrozenMapping`, copied so the source dict is never aliased), serializer keeps `model_dump()`/JSON working, `Rubric.__deepcopy__`/`__reduce__` added because a read-only mapping otherwise breaks `deepcopy` and `pickle`. Text and dicts are not silently turned into tuples. No YAML or validation rule changed. A weakness found in my first test (a long string was rejected for the wrong reason) was fixed by using short strings.

### Phase 2A / 2B implemented
See README "Day 4 ... Phase 2" and `docs/ARCHITECTURE.md`. New code: `app/schemas/evaluation.py`, `app/services/evaluation/{__init__,prompt_builder}.py`. No database model or migration was added or changed; no provider, Celery task, route or frontend file was touched.

### Files
New: `backend/app/schemas/evaluation.py`, `backend/app/services/evaluation/__init__.py`, `backend/app/services/evaluation/prompt_builder.py`, `backend/tests/evaluation_samples.py`, `backend/tests/test_rubric_immutability.py`, `backend/tests/test_evaluation_schema.py`, `backend/tests/test_prompt_builder.py`.
Modified: `backend/app/services/rubrics/models.py` (immutability only), `README.md`, `docs/PROGRESS.md`, `docs/ARCHITECTURE.md`. No existing test was changed in this step.

### Tests (one consolidated run, `-W error`)
- **Written:** 109 new functions (immutability 17, schema 57, prompt builder 35). Backend total 364 functions (Phase 1: 255).
- **Collected and executed:** the 12 collectable files = **416 cases: 415 passed, 1 skipped (real-OpenAI test, off by default), 0 failed**. Per file: rubric_loader 39, rubric_validation 67, rubric_immutability 22, config_evaluation 25, evaluation_schema 144, prompt_builder 63 (all passed).
- **Command:** `cd backend && PYTHONPATH=<standin> pytest --noconftest -W error <12 files>`.
- **Blocked (not executed):** the same 13 existing Day 1–3 files as before (138 functions: they need `fastapi`, `sqlalchemy`, `celery`), plain `pytest` via `conftest.py` (needs SQLAlchemy) and all 99 Vitest tests.
- **Early failures that were fixed (tests, not code):** 5 of my own new schema tests initially failed because of wrong expectations (absolute score bound reached before the rubric-range check, pydantic 2.13 error wording, a docstring matched by an import-independence test). They were corrected, not weakened.

### Limits of this verification
- `pydantic-settings` is a local stand-in (outside the repo); `--noconftest` is used. Real `pydantic-settings` and real CI have not run.
- **pydantic version:** tests ran on 2.13.5; `requirements.txt` pins 2.10.3. The schema uses an after-model-validator that receives validation context (`ValidationInfo`) and `exc.errors(include_input=False, ...)`; these are believed supported in 2.10 but **not verified on 2.10.3**. Error-message wording differs between versions, so tests assert only stable fragments.
- The prompt has never been sent to a model. Whether real models follow it and return grounded quotes is unknown.
- Phase 1 limits still apply: Docker, Alembic, Celery, PostgreSQL, Day 1–3 regression (13 blocked files) unverified.

### Open design questions for review (Phase 3)
1. Where to store the per-answer `recommendation` (no column exists; `criteria_scores` JSON or advisory only).
2. How `overall_score` (rubric scale) relates to the criterion scores and weights, and conversion to 0–100.
3. Whether to retry or fail when a model's quotes do not pass grounding.

### Remaining Day 4 work (not started)
Provider interface + mock + OpenAI provider · weighted scoring · orchestration writing `Evaluation` rows (reusing the existing model) · Celery evaluation task chained after transcription · evaluation API · tests · real-API verification.



## Day 4 — Phase 3 (LLM providers, evaluation engine, Celery task)

**Status: Day 4 is NOT complete.** Implemented and statically checked; the pure parts were executed, the database/Celery parts could not be.

### Implemented
Providers (interface, deterministic mock, OpenAI over HTTP, factory), `scoring.py` (YAML-driven weighted score, 0–10 → 0–100), `persistence.py` (rounding only here), `pipeline.py` (database-free core: rubric → prompt → provider → parse/evidence validation → score), `engine.py` (claim, load, persist in one transaction), `states.py` + `coordination.py` (transcription/evaluation/session rules), `evaluation_dispatch.py`, `workers/evaluation_tasks.py` (`hireiq.evaluate_response`), a hook at the end of the transcription task, a "settle if already finished" step in `complete_session`, migration `0003_evaluation_fields`.
Recommendation decision: dedicated column `evaluations.recommendation` + JSON `evaluation_details` (see README).

### Tests
- Written: `test_evaluation_pipeline.py` (38 tests: weighted scoring, rounding, persistence mapping, mock determinism, OpenAI request shape and every failure class using a fake HTTP session, key never leaking, provider selection, invalid JSON/schema/evidence/range, permanent failures, state rules); `test_evaluation_engine.py` (24 tests: engine, duplicate delivery, no-speech, missing transcript, invalid output never stored, dispatch, eager Celery retries, session coordination); one migration 0002→0003 test.
- **Executed and passed (sandbox, stand-in `pydantic_settings`, no DB):** the 38 pipeline tests; with all earlier collectable files **453 passed, 1 skipped (real-API test), 0 failed**.
- **Written but BLOCKED (not executed):** 24 engine tests + 1 new migration test + the 138 existing DB/API/Celery tests — `sqlalchemy`, `fastapi`, `celery`, `httpx`, `redis` are not installed and there is no network. They must run in CI.
- **Not done:** no real OpenAI request was made; the OpenAI provider was exercised only against a fake HTTP session.
- Existing test changes (deliberate, assertions otherwise unchanged): `test_migrations.py` single-head assertion now expects `0003_evaluation_fields`; `conftest.py` gained an autouse fixture that stubs the evaluation enqueue so no test reaches a broker.

### Risks to check first in CI
`complete_session` now runs a small status query after the commit; the transcription task now calls the evaluation hook (it never raises); the migration-vs-model comparison test for `0003`; SQLite `trim`/`length` in the status queries.

### Superseded note
The Day 3 preparation note said no-speech should become "score 0 with explanation". Phase 3 changes this on purpose: no speech is a system outcome (skipped, no score), per the Phase 3 brief.

### Remaining Day 4 work
See README ("Remaining Day 4 work"). Day 4 is not marked complete.


## Day 4 — Phase 3 stabilization pass

**Status: Day 4 is NOT complete.** Review found two real defects (fixed) and one missing capability (added minimally).
- **Clamp removed:** `persistence.py` no longer clamps the overall score; `scoring.calculate_score` checks the weighted score is inside the rubric scale and the mapper raises `ScoringError` (→ failure code `scoring_invalid`, permanent) otherwise. Formula and weights unchanged.
- **Defect fixed:** `engine._persist` treated every `IntegrityError` as a duplicate and would have marked the answer `completed` with no row stored (e.g. a CHECK violation). It now confirms the row exists; otherwise `persistence_rejected` (permanent, answer `failed`, nothing stored).
- **Re-queue added:** `evaluation_dispatch.requeue_failed_evaluation` (no endpoint, no frontend change).
- **Mock provider:** quotes skip punctuation-only tokens.

**Executed:** 464 passed, 1 skipped, 0 failed (all collectable files; `-W error`; stand-in `pydantic_settings`). New in this pass: 11 pure tests (clamp/noise, scoring-error mapping, extremes 0/100, mock punctuation).
**Written, blocked (not executed):** `test_evaluation_engine.py` (28 tests incl. 4 new: DB rejection ≠ duplicate, re-queue success/no-op/failed-transcription), the 0002→0003 migration test, and the 138 pre-existing DB/API/Celery tests. Blocker: `sqlalchemy`, `fastapi`, `celery`, `alembic`, `redis`, `httpx`, `pydantic_settings` are absent; no existing virtualenv or wheel cache was found; no network. Nothing about FastAPI start-up, the database, Alembic or Celery was run.
**Static checks:** `0003` is additive and chained to `0002`; its 6 columns all exist on the models; `0001`/`0002` identical to the Day 3 archive. No real OpenAI call was made.


## Day 5 — NLP enrichment (spaCy keywords/entities, VADER sentiment, confidence heuristic)

**Status:** implemented and wired into the Day 4 engine; **the real-library and database paths were not executed** (see below). Day 6+ not started.

### Implemented
`app/services/nlp/` (`spacy_backend`, `text_analysis`, `sentiment`, `confidence`, `service`), `app/schemas/nlp.py`, settings `NLP_ENABLED` / `NLP_SPACY_MODEL`, `requirements.txt` (+spaCy 3.8.2, vaderSentiment 3.3.2), `requirements-nlp-model.txt` (model wheel; kept separate because `test_requirements_pin_every_package` requires `==` pins), Dockerfile build step, CI step that installs the model. Integration: one call in `engine._evaluate_claimed` (`enrich_fields`), after validation and scoring, before the single persistence transaction. **No migration** (`evaluations.nlp_enrichment` already existed). Day 4 scoring, pipeline, prompt and schema are untouched.

### Tests
| | Count |
|---|---|
| Written (new) | `test_nlp_analysis.py` 42, `test_nlp_service.py` 20, `test_nlp_real_libs.py` 4, plus 5 new DB tests in `test_evaluation_engine.py` |
| **Executed and passed** (all collectable files, `-W error`, stand-in `pydantic_settings`) | **526 passed, 0 failed** (62 of them new Day 5 tests) |
| Skipped | 2 — `test_nlp_real_libs.py` (spaCy not installed) and the existing real-API test |
| **BLOCKED** | `test_nlp_real_libs.py` (4 tests: real spaCy model + VADER); `test_evaluation_engine.py` (33 incl. 5 Day 5 persistence tests), `test_migrations.py` (5), and the 138 earlier DB/API/Celery tests: `sqlalchemy`, `fastapi`, `celery`, `alembic`, `redis`, `spacy`, `vaderSentiment` and the model are not installed and there is no network |

What the executed tests cover: keyword/entity selection (trimming, vague-noun filter, dedupe, ranking, limits, NORP/numeric labels dropped), sentiment label boundaries and output shape (with an injected fake VADER), the confidence heuristic (weights, signals, hedging allowance, filler words ignored, no sentiment/demographic inputs, missing signals re-weighted, empty/short input), the orchestrator (partial/failed/skipped/disabled, schema validation, no candidate text in logs or stored errors, determinism), and that enrichment changes only `nlp_enrichment` of a real mock-provider evaluation result (score, recommendation, criteria untouched).
**NOT verified:** how the real spaCy model and VADER behave on real transcripts (keyword quality, entity labels, sentiment values) — those tests will run in CI where the model is installed; database persistence of the enrichment; the Dockerfile build.

### Deliberate change to an earlier test
`test_evaluation_engine.py::test_run_persists_a_validated_evaluation_and_settles_the_session` asserted `nlp_enrichment is None` (the Day 4 contract). It now asserts a schema-versioned dict is stored. No other earlier assertion changed.

### Found while testing
The first keyword ranking let a noun repeated three times outrank a proper noun and a specific phrase; frequency weight was reduced (`1 + 0.3·ln(count)`, proper-noun bonus 1.5) and a test pins the behaviour.

### Known limitations
Entity/keyword quality of `en_core_web_sm` is unmeasured here; English only; the technology gazetteer is small and hand-made; VADER and the confidence heuristic have the limitations listed in the README and must stay advisory.


## Day 6 — PDF evaluation report (ReportLab)

**Status:** implemented. The renderer, data sanitising, radar and settings were **executed and pass**. The database loader, the download route and the token dependency were **written but NOT executed** (SQLAlchemy/FastAPI/Celery cannot be installed offline). Day 7 not started.

### Implemented
`app/services/reporting/{data,loader,radar,pdf}.py`, `app/api/routes/reports.py` (registered in `main.py`), setting `REPORT_ACCESS_TOKEN` (`config.py`, compose, `.env.example`), `reportlab==4.2.5`, dev `pypdf==5.1.0`. No migration, no change to scoring, recommendation, pipeline or NLP.

### Tests
| | Count |
|---|---|
| Written (new) | `test_report_pdf.py` 40, `test_report_settings.py` 3, `test_report_api.py` 15 (loader 6, endpoint 9 incl. 401/503/404/409/422/headers/no writes) |
| **Executed and passed** | **569 passed, 0 failed, 2 skipped** (all collectable files, `--noconftest`, `-W error`, stand-in `pydantic_settings`, env vars normally set by conftest). 526 earlier + 43 new |
| Skipped | 2 — `test_nlp_real_libs.py` (no spaCy), real OpenAI test (by design) |
| **Blocked** | 15 files fail at collection (no `sqlalchemy`/`fastapi`/`celery`): the 14 earlier DB/API/Celery/migration files and the new `test_report_api.py` |

Covered by executed tests: valid PDF structure and footer on every page; candidate details; exact stored score and recommendation; per-question and criterion data; transcript; 600-sentence transcript pagination with word boxes inside the margins (poppler `pdftotext -bbox`); 400-character unbroken token; HTML/script/control-character escaping; unsupported glyph note; partial/empty/malformed data; missing NLP; radar mean, no fabrication, 3–12 axes, <3 criteria, differing scales; no candidate text in logs/repr; no files written.
**NOT verified:** `load_report_data` against a database, the route (headers, 401/404/409/503), session isolation in SQL, behaviour in the Docker image, opening the PDF in Acrobat/Preview/print. The PDF was inspected visually only as rendered images in the sandbox.

### Notes
- Authorization: shared bearer token (no accounts exist); unset = endpoint disabled.
- Test baseline note: `test_config.py::test_get_settings_is_cached_and_reads_environment` needs the conftest env defaults; with `--noconftest` they must be exported by hand.
- Pinned `pypdf==5.1.0` is untested here (the sandbox has 6.x); tests use only `PdfReader`/`extract_text`.

### Known limitations
Latin-only font; synchronous rendering without cache; per-answer advice not combined; hiring-manager authentication still missing.


## Day 7 — Hiring manager dashboard

**Status:** implemented. **Verified in a real browser (headless Chromium) against a MOCK API server, plus pure-logic tests through a mini runner. The backend dashboard endpoints, the SQL, and the real vitest/jsdom suites were NOT executed** (sqlalchemy/fastapi/celery/vitest/jsdom/@testing-library/@types/react are not installed; no network). Day 8 not started.

### Implemented
Backend: `app/schemas/dashboard.py`, `app/services/dashboard.py`, `app/api/routes/dashboard.py` (registered in `main.py`); `reporting/loader.py` split into `load_session_data`/`load_report_data` (behaviour of the Day 6 path unchanged); generic 401/503 texts in `routes/reports.py`.
Frontend: `types/dashboard.ts`, `services/dashboardApi.ts`, `utils/dashboard.ts`, `components/dashboard/*` (MetricCard, DashboardOverview, FilterPanel, InterviewTable, Pagination, ScoreBar, CriteriaChart, RecommendationBadge, ReportDownloadButton, CandidateEvaluationView, TokenGate), `pages/DashboardPage.tsx`, `Root.tsx` (hash route), `main.tsx` (renders Root), dashboard CSS appended to `global.css`. No migration, no new dependency.

### Tests
| | Count |
|---|---|
| Written, backend | `test_dashboard_api.py` 29 cases (21 functions; DB + API), `test_dashboard_schemas.py` 10 cases |
| Written, frontend (vitest) | `utils/dashboard.test.ts`, `services/dashboardApi.test.ts` (24 cases together), `dashboard.components.test.tsx` (22), `DashboardPage.test.tsx` (15), `Root.test.tsx` (2) |
| **Executed, pytest** | **579 passed, 0 failed, 2 skipped** (`--noconftest -W error`, stand-in `pydantic_settings`, conftest env vars exported by hand): 569 earlier + 10 new schema cases |
| **Executed, frontend pure tests** | **24 passed, 0 failed** — `utils/dashboard.test.ts` and `services/dashboardApi.test.ts` run through a small hand-written vitest stand-in (outside the repo), NOT real vitest |
| **Executed, browser check** | **24 checks passed, 0 failed**: real Chromium, the real built React app and real `dashboardApi` client against a Node mock server (a script kept outside the repo): token gate, wrong token, listing, metrics, missing name, long name (no overflow at 1280 and 390 px), search + status + advice + interview filters together, clear, server-error state, detail view, advisory NLP label, PDF download through the endpoint (file name and `%PDF-` header), disabled PDF button, sign-out, candidate app unchanged, no token in storage or DOM. Built with React 19 (the project pins React 18) |
| Skipped | 2 (no spaCy; real OpenAI by design) |
| **Blocked** | all DB/API pytest files (16 files incl. `test_dashboard_api.py` and `test_report_api.py`); real vitest suites: component, page and Root tests (39 cases) and the jsdom-dependent storage assertions; `npm run build`/`typecheck` |

Type check: only a partial `tsc` pass was possible, with hand-made stubs for React (`@types/react` missing): `Root`, `DashboardPage`, `dashboardApi`, `utils` and the new components showed no errors except artefacts of the stubs (`key` props, event parameter types). The real `npm run typecheck` has not run.
**NOT verified:** every SQL statement and filter in `services/dashboard.py` on SQLite/PostgreSQL; the 401/503/404/422 responses of the real routes; CORS with the real FastAPI middleware (it echoes requested headers with `allow_headers=["*"]`, but this was not run); behaviour with real data volumes; React 18 behaviour; other browsers.

### Found while testing
Screenshots showed a thin bar for a 0-count bucket and a missing full stop in "This answer has no score"; both fixed. A first smoke run failed only because the mock server kept its request log from a previous run.

### Known limitations
See README Day 7: shared-token access (not production authentication), no sorting/comparison/export, empty session-level recommendation for real data, Python-side distribution.

### Final audit (after the first Day 7 write-up)
- Fixed: the detail response passed the whole stored NLP object to the browser (including internal error text and model names); it is now cut down by `public_nlp` (tested). Header "Sign out" button raised to the 44 px touch-target minimum.
- Regression: compared with the Day 6 archive, the only existing files changed are `README.md`, `docs/*`, `main.tsx`, `global.css` (append only), `app/main.py` (router registration), `routes/reports.py` (generic 401/503 wording) and `reporting/loader.py` (split into two functions). No migration, no existing test file changed or deleted.
- Day 1-6 suites that can run here still pass (see counts above); the DB/API suites of every day remain blocked in this sandbox, so their regression status is "not re-run".
- Screenshots were not regenerated; the two small visual fixes were retested in the browser check (24/24).

---

## Day 8 — Rubric configuration and question bank

**Status:** implemented. Day 9 not started.

### Findings before changing anything
The Day 4 rubric system already satisfied the validation requirements (strict models, weight sum 1.0, gap/overlap-free score bands, safe YAML, clear located errors, pipeline failure codes). It was verified and **left unchanged**. The `questions` table had text/type/rubric_key/position/time limit but no category, difficulty or skills, and there was no way to create interviews or questions except seed data.

### Implemented
- Rubric tooling: `services/rubrics/catalog.py`, CLI `python -m app.scripts.validate_rubrics`.
- Migration `0004_question_bank_fields` (3 nullable columns + category index on `questions`; migrations 0001-0003 untouched).
- `schemas/question_bank.py`, `services/question_bank.py`, `routes/question_bank.py` (6 token-protected endpoints), registered in `main.py`.
- Docs: `docs/RUBRICS_AND_QUESTION_BANK.md`, README Day 8, ARCHITECTURE additions.

### Tests (written / executed / result)
| | |
|---|---|
| Written (new) | `test_rubric_catalog.py` (13), `test_question_bank_schemas.py` (58), `test_question_bank_migration_static.py` (5), `test_question_bank_api.py` (DB/API cases), 1 new case in `test_migrations.py` |
| **Executed, pytest** | **655 passed, 0 failed, 2 skipped** (`--noconftest -W error`, stand-in `pydantic_settings`, env vars exported by hand): 579 earlier + 76 new |
| Skipped | 2 (no spaCy; real OpenAI by design) |
| **Blocked** | `test_question_bank_api.py`, the new `test_migrations.py` case and the 16 earlier DB/API files (17 collection errors: SQLAlchemy/FastAPI/Alembic not installable offline). **Not run, so not reported as passed.** |
| Frontend | unchanged in Day 8; Day 7 frontend results above still apply and were not re-run |

**NOT verified:** SQL in `services/question_bank.py` (including the JSON-text `skill` filter on SQLite/PostgreSQL and the duplicate-race IntegrityError path), migration 0004 upgrade/downgrade, the real route responses (401/503/404/409/422), CORS.

### Deliberate edit to an existing test
`tests/test_migrations.py`: expected Alembic head changed from `0003_evaluation_fields` to `0004_question_bank_fields` (the 0003/0002 chain assertions are kept). No test deleted or weakened.

### Known limitations / out of scope
Shared-token access (not per-user auth); no edit/delete of questions or interviews; no question-bank UI; stored evaluations are not re-scored after rubric edits.


---

## Day 9 — End-to-end testing, security review and bias review

**Status: completed, awaiting independent approval. Day 10 not started. No application source changed.**

Added: `tests/test_day9_e2e_chain.py`, `test_day9_bias_fairness.py`, `test_day9_security.py`, `test_day9_workflow_e2e.py`; `docs/BIAS_AND_FAIRNESS_REVIEW.md`; `docs/DAY9_TESTING_REPORT.md`. Modified: README, this file. Removed: nothing. No existing test or migration touched.

| Day 9 category | Written | Executed | Passed | Failed | Blocked |
|---|---|---|---|---|---|
| End-to-end (offline simulated chain, mock providers) | 17 | 17 | 17 | 0 | 0 |
| End-to-end (database-backed workflow) | 6 | 0 | 0 | 0 | **6** (never run) |
| Bias and fairness | 39 | 39 | 39 | 0 | 0 |
| Security (static/AST, settings, validators) | 36 | 36 | 36 | 0 | 0 |

Whole suite, single run: 749 collected; 748 passed; 0 failed; 2 skipped; 18 files blocked at collection (about 246 test functions, a lower bound).
Environment limits: no SQLAlchemy, FastAPI, Celery, Alembic, redis/psycopg clients, Whisper, OpenAI credentials, spaCy/VADER or node_modules; PostgreSQL and Redis not running; sandbox pydantic/reportlab are newer than pinned. Migrations 0001–0004 upgrade/downgrade have **not** been executed.
Findings and recommendations: see the two Day 9 documents. Real-world validation of model and Whisper fairness is outstanding.

## Day 10 — Deployment preparation, documentation and final report

**Status: completed, awaiting independent approval. No further phase started.**

Deployment status: **Deployment-ready, but external deployment blocked** (no Docker daemon, no provider credentials, no network; no URL exists).

Added: `frontend/Dockerfile`, `frontend/nginx.conf`, `frontend/.dockerignore`, `docs/DEPLOYMENT_GUIDE.md`, `docs/USER_GUIDE.md`, `docs/DEMO_SCRIPT.md`, `docs/FINAL_PROJECT_REPORT.md`. Modified: `README.md`, `docs/ARCHITECTURE.md`, `docs/PROGRESS.md`, `docker-compose.yml`, `.env.example`, `.github/workflows/ci.yml`. Removed: none. No application source, test or migration changed.

Executed: `docker compose config -q` (valid); static env-variable and migration-chain checks; the full backend run (749 collected, 748 passed, 0 failed, 2 skipped, 18 files blocked at collection); the Day 9 modules and `test_repo_files.py` individually.
Blocked: frontend typecheck/build/vitest (`TS2688` for `vite/client`; no `node_modules`, no network), Docker image builds and `compose up` (no daemon), PostgreSQL/Redis/Celery/Alembic execution, real Whisper/OpenAI/spaCy/VADER.
Doc fixes found while verifying commands against the code: the completion button is "Finish interview"; the browser keeps only the session id in sessionStorage; Celery uses the default queue.
Full details: `docs/FINAL_PROJECT_REPORT.md`.
