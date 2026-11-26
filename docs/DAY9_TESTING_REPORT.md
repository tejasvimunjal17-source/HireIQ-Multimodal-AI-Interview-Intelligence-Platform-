# HireIQ — Day 9 testing report (end-to-end, regression, security, bias)

**Status: Day 9 completed, awaiting independent review and approval. Day 10 has not been started.**
Local test results only. Nothing here is deployment verification, a PostgreSQL/Redis/Celery/Whisper/LLM integration result, or a migration result.

## 1. Testing environment
| Item | Value |
|---|---|
| OS / Python | Linux 6.18, Python 3.13.18 |
| Node.js / npm | v22.23.4 / 10.9.9 (frontend tests **not run**: `node_modules` absent, no network) |
| Test runner | pytest 9.1.1 |
| Installed, used | pydantic 2.13.5, PyYAML 6.0.3, reportlab 5.0.1, pypdf 6.17.0, starlette 1.7.0, ffmpeg 6.1.1 |
| **Missing Python packages** | SQLAlchemy, FastAPI, Celery, Alembic, redis, psycopg, openai, vaderSentiment, spaCy, Whisper, pydantic-settings (a stand-in for `BaseSettings` kept **outside** the repository was used so configuration tests can run) |
| Version differences from `requirements.txt` | sandbox pydantic 2.13.5 (pinned 2.10.3) and reportlab 5.0.1 (pinned 4.2.5): PDF and schema tests ran on **newer versions than the project pins** |
| Services | PostgreSQL 16 client/server binaries present, cluster **down**; `redis-server` binary present, **not running**; I did not start them: even if running, the Python clients (psycopg, redis, SQLAlchemy, Celery) are missing, so every integration path stays blocked. No Whisper model, no OpenAI/Gemini credentials, no network. |
| `--noconftest` | needed because `conftest.py` imports SQLAlchemy; environment variables the conftest would set are exported by hand (command below) |

## 2. Commands executed (exact)
```
cd backend
export ENVIRONMENT=test DATABASE_URL=sqlite:// SECRET_KEY=test-only-secret-key-0123456789abcdef \
       REDIS_URL=redis://localhost:6379/0 PYTHONPATH=<out-of-repo stand-in for pydantic_settings>:.
python3 -B -m pytest --noconftest -W error -p no:cacheprovider -q --continue-on-collection-errors --collect-only tests   # collection
python3 -B -m pytest --noconftest -W error -p no:cacheprovider -q --continue-on-collection-errors tests --junitxml=...   # the ONE run used for all totals
python3 -B -m pytest --noconftest -W error -p no:cacheprovider -q tests/test_day9_<e2e_chain|bias_fairness|security>.py    # per-module recount
```
**Accounting rule:** every executed/passed/failed/skipped number below comes from the single full run (junit XML), not from adding overlapping runs; the per-module recount of
the Day 9 modules (17 / 39 / 36) matched that run. Blocked numbers are **test functions** counted from the source (`def test_*`), because blocked files cannot be collected; a
parametrised blocked test would be more cases than functions, so blocked totals are a lower bound.

## 3. Final accounting (one consistent method)
| Term | Meaning here | Number |
|---|---|---|
| Collected | pytest items collected without error | **749** |
| Executed | items that ran (passed + failed) | **748** |
| **Passed** | | **748** |
| **Failed** | | **0** |
| Skipped | skip outcomes (spaCy absent; real OpenAI call needs credentials) | **2** |
| **Blocked** | 18 test files that failed at **collection** (missing SQLAlchemy/FastAPI/Celery imports); reported as blocked, not failed, not passed | **18 files ≈ 246 test functions** |

(The run line reads "748 passed, 2 skipped, 18 errors"; collection lists 749 items because one skip is a module-level skip that is not an item.)

### By category (mutually exclusive; the Passed column sums to 748)
| Test category | Written | Executed | Passed | Failed | Blocked | Notes |
|---|---|---|---|---|---|---|
| Unit / offline, Day 1–8 (config, rubric, prompt, schema, pipeline, NLP, PDF render, repo files, Day 8 schemas/catalog/static) | 656 | 656 | 656 | 0 | 0 | pure Python; fake providers |
| API tests through FastAPI TestClient (Day 1–8 incl. dashboard, reports, question bank) | 118 fn | 0 | 0 | 0 | **118 fn** | need FastAPI, SQLAlchemy |
| Database / service / audio / Celery-task tests on SQLite stand-in (models, migrations, engine, transcription, audio) | 118 fn | 0 | 0 | 0 | **118 fn** | need SQLAlchemy (Alembic, Celery) |
| Live-service integration (PostgreSQL+Redis, real OpenAI, spaCy/VADER) | 9 fn | 0 | 0 | 0 | **4 fn** blocked; 5 fn skipped (2 skip outcomes) | need services/credentials/libs |
| **Day 9 end-to-end** (offline chain 17 + DB workflow 6) | 23 | 17 | 17 | 0 | **6 fn** | the 17 are an **in-process simulation with mock providers**, see 6 |
| **Day 9 bias and fairness** | 39 | 39 | 39 | 0 | 0 | 17 safeguard-style, 11 "known weakness" characterisations (function counts) |
| **Day 9 security** | 36 | 36 | 36 | 0 | 0 | static/AST + settings; 3 "known weakness" characterisations |
| **Total** | | **748** | **748** | **0** | **246 fn (18 files)** | + 2 skipped |

**Regression view (Day 1–8 = first four rows):** 656 executed and passed, 0 failed, 246 function-level tests blocked, 2 skipped. Day 9 added 92 executed-and-passed tests and 6 blocked ones.
The 92 was **independently recounted**: junit shows 17 + 39 + 36 = 92, matching the module runs.

## 4. Test modules (new in Day 9 and where the old ones fit)
| Module | Group | Status |
|---|---|---|
| `test_day9_e2e_chain.py` | end-to-end component chain (offline, mock provider, fake NLP objects, real PDF rendering, real pypdf extraction) | 17 executed, passed |
| `test_day9_bias_fairness.py` | bias/fairness safeguards and documented limitations | 39 executed, passed |
| `test_day9_security.py` | security/privacy (AST source checks, settings, prompt injection validators, secrets, frontend token storage) | 36 executed, passed |
| `test_day9_workflow_e2e.py` | DB-backed candidate → transcription task → evaluation task → complete → dashboard → PDF → question bank, through the real FastAPI app on SQLite with Task.apply | **written, blocked, NEVER RUN: may need adjustment on first run** |
Test-support files used by the new modules and preserved in the archive: `tests/__init__.py`, `conftest.py`, `evaluation_samples.py`, `report_samples.py`, `dashboard_builders.py`, `helpers_audio.py`, `builders.py`, `fake_openai.py`, `pytest.ini`, the rubric YAML under `backend/config/rubrics`.
No existing test was modified or removed in Day 9.

## 5. End-to-end workflow coverage (honest)
Legend: **E** executed here · **S** simulated (mock providers/fake objects, in process) · **B** written, blocked · **N** not covered.
| Workflow step | Coverage |
|---|---|
| A1 Candidate can access the interface; A2 questions load | B (`test_full_workflow...`); frontend component tests exist from Day 3–7 but were **not run** (no node_modules) |
| A3 Recording and submission; A4 processing and transcription | B (real WAV through audio intake, mock transcription provider). Whisper: **N** (no model); browser recording: **N** (needs a real browser) |
| A5–A7 Responses stored, status updated, evaluation triggered | B |
| B1–B4 Transcript to pipeline; YAML rubric; structured output; scores and evidence parsed | **E/S** (`test_day9_e2e_chain`, mock provider) |
| B5 Invalid provider responses handled safely | **E** (invalid JSON, fences, wrong shape, hallucinated evidence, extra fields) |
| B6 Persistence | B only (needs database) |
| B7 NLP advisory | **E** (score identical with NLP on/off/broken; only `nlp_enrichment` changes) |
| B8 Failed tasks and retries | B (existing `test_evaluation_engine`/`test_transcription_tasks`); not re-run |
| C1–C4 Report content and long text | **E** (real ReportLab PDF read back with pypdf; long and unbroken text) |
| C5 Unauthorised PDF rejected | **S** static route check executed; real HTTP 401: B |
| C6 Missing evaluation → error | B (409/404 asserted in `test_day9_workflow_e2e` and `test_report_api`) |
| D1–D7 Dashboard auth, stats, filters, pagination, detail, PDF link, hidden fields | schemas and `public_nlp` **E**; token/route protection **S** (static); queries, filters, pagination, HTTP behaviour: B |
| E1–E2 Rubrics discovered, invalid YAML rejected | **E** (Day 8 catalog/CLI, Day 4 loader tests) |
| E3–E8 Question creation, validation, filtering, keys, activation, compatibility | schema/validation rules **E**; API and DB behaviour (incl. the Day 8 wildcard fix): B |

**The complete workflow has NOT been verified end to end.** The executed "chain" test joins the pure components in one process; it does not touch HTTP, a database, Celery, Redis, Whisper or a real model.

## 6. Integration results (per pair requested)
| Pair | Result |
|---|---|
| React ↔ FastAPI | not run (no node_modules, no FastAPI); Day 7 mock-server smoke test from earlier milestones is not re-run |
| FastAPI ↔ PostgreSQL | **blocked** (no SQLAlchemy/psycopg, cluster down). Command: `docker compose up -d postgres redis && cd backend && RUN_INTEGRATION=1 pytest tests/test_integration_services.py` |
| FastAPI ↔ Celery, Celery ↔ Redis | **blocked** (no Celery/redis client, Redis down). Same command |
| Audio processing ↔ Whisper | **blocked** (no model/openai package/credentials). Command: `RUN_REAL_WHISPER=1 OPENAI_API_KEY=... pytest tests/test_openai_real.py` |
| Evaluation ↔ LLM provider | mock provider only (executed); real provider **not run** |
| Evaluation ↔ NLP enrichment | executed with **injected fakes**; real spaCy/VADER **not run** (skipped) |
| Evaluation records ↔ PDF | executed in memory (dict fields → PDF); database-loaded path blocked |
| Dashboard ↔ report APIs; question bank ↔ interview creation | blocked (`test_day9_workflow_e2e.py`, `test_dashboard_api.py`, `test_question_bank_api.py`) |
**Migrations:** the Alembic upgrade/downgrade of 0001–0004 has **not** been executed. Only static text checks of 0004 ran.

## 7. Regression results by milestone (executed, offline)
| Day | Executed and passed | Still blocked (needs DB/web stack) |
|---|---|---|
| 4 rubric + evaluation | rubric validation 67, loader 39, immutability 22, prompt builder 63, evaluation schema 144, pipeline 49, evaluation config 25 | evaluation engine (33 fn) |
| 5 NLP | analysis 42, service 20 | real spaCy/VADER (skipped) |
| 6 PDF | PDF rendering 40, report settings 3 | report API (15 fn) |
| 7 dashboard | dashboard schemas 10 | dashboard API (21 fn); frontend tests not run |
| 8 rubric + question bank | catalog 13, schemas 59, migration static 5 | question-bank API (31 fn), migration upgrade/downgrade |
No Day 4–8 behaviour changed (no application source file was modified in Day 9), so these results confirm that the tested logic still passes, not that the blocked paths work.

## 8. Security review
### 8.1 Source inspection (reading code; not a test result)
| ID | Finding | Severity (judgement) |
|---|---|---|
| SEC-1 | One shared bearer token protects all manager routes: no per-user identity, no audit trail, **no rate limiting or lockout anywhere in the backend** (searched), so a weak token could be guessed. Mitigations: ≥ 16 characters enforced, constant-time comparison, blank token disables the routes (503), checked before any lookup. | medium (documented since Day 6; not production-grade authentication) |
| SEC-2 | Candidate endpoints are protected only by the unguessable session UUID (a capability); anyone holding it can read that candidate's transcript status/text. | low–medium, by design |
| SEC-3 | `CORS_ORIGINS=*` is accepted even in production (credentials switched off in that case). Operators must set explicit origins. | low |
| SEC-4 | Validation errors use the framework default and echo the submitted value in the 422 body. | low |
| SEC-5 | No security headers (HSTS, CSP, frame options) or request throttling in the app; must come from the reverse proxy. Frontend hosting not reviewed. | medium for deployment |
| SEC-6 | Transcripts and candidate name/e-mail are stored in plain text in the database; no retention or deletion workflow exists for candidate data. Audio is processed from a temporary directory and stale files are purged (per configuration comments). | medium for privacy compliance |
| SEC-7 | Prompt injection is mitigated by delimiting and strict output validation; a real model persuaded to give high scores with genuine quotes would pass validation. | medium, needs real-model red-team |
| SEC-8 | Dependencies were not vulnerability-scanned (offline); sandbox ran newer pydantic/reportlab than pinned. | unknown |
| SEC-9 | Candidate free text (question bank text, transcripts) is never rendered as HTML by the backend; XSS handling in React relies on React's default escaping (not separately tested). | low |

### 8.2 Executed security tests (36 passed; static and settings level only)
Route protection of every manager module and that new route modules must be reviewed · constant-time comparison, `WWW-Authenticate`, 401/503 present in the dependency · token held as a secret and absent from `repr`/`model_dump` · short token refused, blank token disables access ·
frontend: no browser storage of the manager token, no token-like environment variable, no literal bearer token, the only storage is the candidate session id · no log statement contains transcript/e-mail/name/token/path identifiers and exceptions are not logged by message · constant 500 body ·
PDF file name uses the session id only · CORS configured from settings, no credentials with wildcard, defaults local-only · `.env.example` templates blank and no real `.env` · no key patterns in source · prompt-injection layout (data delimiters, forged delimiter, question injection) and rejection of obedient-but-invalid model output ·
input validation of the session start request · upload middleware and content-type allow-list present in source · mock provider refused in production.
These prove how the code is written. **Not executed:** real 401/503/404 HTTP responses, real CORS headers, real error bodies, TLS, rate limiting, database access control (blocked: FastAPI/SQLAlchemy). Counterpart tests exist in `test_report_api.py`, `test_dashboard_api.py`, `test_question_bank_api.py`, `test_day9_workflow_e2e.py`.

## 9. Bias and fairness summary
Full text: `docs/BIAS_AND_FAIRNESS_REVIEW.md`. 39 executed tests cover 17 safeguards and 11 pinned limitations. Key findings: recommendation not reconciled with the weighted score (F1); 3-word quotes accepted as evidence and relevance not checked (F2);
missing information can become the minimum score (F3); no transcription-quality signal for reviewers (F4); filler words raise and hedging lowers the confidence heuristic (F5, F6); keyword stuffing rewarded by that heuristic (F7); PERSON/place entities shown to managers (F8);
style/experience assumptions in the rubric text (F9); no run-to-run variance measurement (F10); no enforced human review. Whether real models or Whisper treat candidates equally is **unverified**; HireIQ is **not** claimed to be unbiased and is not for automated hiring decisions.

## 10. Source-code changes in Day 9
**None to application code.** No defect was demonstrated that justified a correction, so every weakness is documented instead of changed.
Added: four test modules, `docs/BIAS_AND_FAIRNESS_REVIEW.md`, this report. Modified: `README.md`, `docs/PROGRESS.md`. Removed: nothing.

## 11. Known limitations
Everything in sections 1, 5, 6 and 8; additionally: blocked counts are function counts; the DB-backed workflow test and the earlier DB/API suites have never run in this environment, so they may contain defects that only appear on first execution; the offline PDF/schema tests ran on newer library versions than pinned; the frontend test suite was not re-run; the review used the shipped `default.yaml` only.

## 12. Recommended next steps (for the project owner, not started)
1. Run the whole suite in a networked environment with the pinned dependencies: `cd backend && pip install -r requirements.txt -r requirements-dev.txt && pytest -v` (expect the blocked files to run; fix any first-run failures, starting with `test_day9_workflow_e2e.py`).
2. Run `RUN_INTEGRATION=1 pytest tests/test_integration_services.py` against `docker compose up postgres redis`, and `alembic upgrade head && alembic downgrade -1` on a copy of the database.
3. Run frontend tests: `cd frontend && npm ci && npm test`.
4. Act on bias recommendations 1–5 in the review and run the validation study described there before any real candidate use.
5. Before deployment: per-user authentication, rate limiting, security headers, explicit CORS origins, data-retention policy, dependency scan.
