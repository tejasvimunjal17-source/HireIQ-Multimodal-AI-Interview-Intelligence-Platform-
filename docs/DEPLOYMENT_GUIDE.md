# HireIQ deployment guide

**Deployment status: NOT DEPLOYED.** No cloud account, deployment credentials or Docker daemon were available when this guide was written, so no
URL exists and nothing here has been run as a live deployment. The configuration is *deployment-ready*: `docker compose config` validated the
Compose file (executed), everything else below is reproducible instructions that you must execute yourself. Statements marked
**[not executed]** describe steps that were never run by the author.

## 1. Prerequisites
| Need | For |
|---|---|
| Docker Engine + Docker Compose v2 | the container route (recommended) |
| Python 3.12, Node.js 20, PostgreSQL 16, Redis 7, ffmpeg | the no-Docker route |
| An OpenAI API key | only for real transcription (`openai`) or real evaluation (`openai`); **not needed for the mock demo** |
| A host with HTTPS (reverse proxy / platform TLS) | any real deployment; browsers allow the microphone only on `https://` or `localhost` |

## 2. What the Compose stack contains
| Service | Image / build | Port | Notes |
|---|---|---|---|
| `postgres` | `postgres:16-alpine` | not published | data in the `postgres_data` volume; health check `pg_isready` |
| `redis` | `redis:7-alpine` (append-only file) | not published | data in `redis_data`; health check `redis-cli ping` |
| `backend` | root `Dockerfile` (python:3.12-slim, ffmpeg, spaCy model, non-root user) | 8000 | runs `alembic upgrade head` then `uvicorn`; health check `GET /health`; waits for healthy postgres and redis |
| `worker` | same image | none | Celery worker (transcription and evaluation tasks); waits for a healthy backend; **no health check** |
| `frontend` | `frontend/Dockerfile` (node:20 build, `nginx-unprivileged` serve) | 3000 → 8080 | static files; health check `wget`; waits for a healthy backend |
Services talk over the private `hireiq_net` network using the service names `postgres` and `redis`. Temporary audio lives in the `audio_tmp` volume shared by backend and worker.
Only the frontend and the API ports are published.

## 3. Environment configuration
```bash
cp .env.example .env          # .env is git-ignored and excluded from the archive: never commit it
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # SECRET_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # REPORT_ACCESS_TOKEN (>= 16 chars)
python3 -c "import secrets; print(secrets.token_urlsafe(24))"   # POSTGRES_PASSWORD
```
| Variable | Required | Meaning / rule |
|---|---|---|
| `ENVIRONMENT` | no (`development`) | `development`, `test` or `production`. **`production` refuses**: a `SECRET_KEY` shorter than 32 characters or starting with `change-me`; `TRANSCRIPTION_PROVIDER=mock`; `EVALUATION_PROVIDER=mock`. |
| `LOG_LEVEL` | no (`INFO`) | standard level names |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | **yes (Compose)** | database container credentials; Compose builds `DATABASE_URL` from them |
| `DATABASE_URL` | yes (no Docker) | `postgresql+psycopg://USER:PASSWORD@HOST:5432/DB`; ignored by Compose (it builds its own) |
| `REDIS_URL` | no (`redis://localhost:6379/0`) | Celery broker and result backend; Compose forces `redis://redis:6379/0` |
| `SECRET_KEY` | **yes** | random string; Compose refuses to start without it |
| `TRANSCRIPTION_PROVIDER` | no (`mock`) | `mock` (fake placeholder text), `openai` (Whisper API), `local` (open-source Whisper, needs `requirements-whisper-local.txt`) |
| `EVALUATION_PROVIDER` | no (`mock`) | `mock` (placeholder scores) or `openai`. **`gemini` is not implemented** (the `GEMINI_API_KEY` setting is reserved and unused). |
| `OPENAI_API_KEY` | only for `openai` providers | server-side only; leave blank otherwise. `GEMINI_API_KEY`: unused. |
| `EVALUATION_MODEL`, `EVALUATION_TIMEOUT_SECONDS`, `EVALUATION_MAX_RETRIES`, `EVALUATION_RETRY_BACKOFF_SECONDS` | no | defaults `gpt-4o`, 60, 3, 5 |
| `OPENAI_TRANSCRIPTION_MODEL`, `LOCAL_WHISPER_MODEL`, `TRANSCRIPTION_LANGUAGE` | no | defaults `whisper-1`, `base`, blank = automatic language detection |
| `AUDIO_MAX_UPLOAD_MB`, `AUDIO_MAX_DURATION_SECONDS` | no | 25 MB, 600 s |
| `NLP_ENABLED`, `NLP_SPACY_MODEL` | no | `true`, `en_core_web_sm` (installed at image build time; the app never downloads models) |
| `REPORT_ACCESS_TOKEN` | no | shared secret (>= 16 chars) for the PDF, dashboard and question-bank routes. **Blank disables them (HTTP 503).** |
| `RUBRICS_DIR` | no | folder with YAML rubrics; blank = `backend/config/rubrics` |
| `CORS_ORIGINS` | no | comma-separated **exact** origins of the frontend, e.g. `https://hireiq.example.com`. Never use `*` in production (the app does not forbid it). |
| `VITE_API_BASE_URL` | no (`http://localhost:8000`) | address the **browser** uses to reach the API; baked into the frontend at build time: rebuild after changing it. Public value only. |
| `FRONTEND_PORT` | no (`3000`) | host port of the frontend container; its origin must appear in `CORS_ORIGINS` |
Frontend-only variables (`VITE_DEMO_MODE`, `VITE_UPLOAD_TIMEOUT_MS`) are in `frontend/.env.example`. **No secret may ever be put in a `VITE_*` variable**: they are readable in the browser.
Other tuning settings (audio sample rate, stale-audio hours, transcription retry limits, `OPENAI_BASE_URL`, `APP_NAME`) have safe defaults; to change them under Compose add them to the `x-backend-env` block of `docker-compose.yml`.

## 4. Start with Docker
```bash
docker compose config -q                       # validates the file and your .env (this check WAS executed by the author)
docker compose up --build -d                   # [not executed] builds 3 images, starts 5 services
docker compose ps                              # backend, frontend, postgres, redis should be "healthy"
curl -fsS http://localhost:8000/health         # {"status":"ok",...}
curl -fsS http://localhost:8000/health/db      # 200 only if PostgreSQL answers, else 503
curl -fsS http://localhost:8000/health/redis   # 200 only if Redis answers, else 503
docker compose exec backend python -m app.scripts.seed_demo      # creates the sample interview
curl -fsS http://localhost:8000/api/interviews
```
Open http://localhost:3000 (candidate) and http://localhost:3000/#/dashboard (manager; enter `REPORT_ACCESS_TOKEN`). API docs: http://localhost:8000/docs.
Stop: `docker compose down` (data stays). `docker compose down -v` **deletes the database**.
The repository's CI job `docker-compose-smoke` performs the same start-up and the four curl checks plus the frontend page; **it has not been run** (needs GitHub).

## 5. Database setup and migrations
Compose creates the database named in `POSTGRES_DB` on first start (the data volume keeps it afterwards; changing `POSTGRES_PASSWORD` later does **not** change an existing volume).
Migrations (Alembic, `backend/alembic/versions`): `0001_initial_schema` → `0002_transcription_fields` → `0003_evaluation_fields` → `0004_question_bank_fields` (single head `0004`). The chain was checked statically; **no migration has ever been executed against a real database by the author.**
```bash
docker compose exec backend alembic current          # shows the applied revision ("(head)" when up to date)
docker compose exec backend alembic upgrade head     # the backend container already does this at every start
docker compose exec backend alembic history          # lists 0001..0004
docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c '\dt'     # tables: candidates, interviews, questions, interview_sessions, candidate_responses, evaluations, reports
docker compose exec backend alembic downgrade -1     # only on a COPY of the data; 0004 drops three question columns
```
Manual database without Docker: `createdb hireiq` (or `CREATE DATABASE hireiq;`), set `DATABASE_URL`, run `alembic upgrade head` from `backend/`.
Do not edit historical migrations; add a new revision instead.
### Troubleshooting database errors
| Symptom | Likely cause and fix |
|---|---|
| `password authentication failed` | `.env` password differs from the one the existing volume was created with. Use the old password, or (data loss!) `docker compose down -v`. |
| `could not translate host name "postgres"` / connection refused | running the app outside Docker with the Compose URL; use `localhost` in `DATABASE_URL`, or the DB is not up yet (`docker compose ps`). |
| backend restarts in a loop | `docker compose logs backend`: usually a settings error (missing `SECRET_KEY`, too-short token, mock provider with `production`) or a failed migration. |
| `Can't locate revision` / multiple heads | the database was migrated by different code; compare `alembic current` with `alembic history`. |
| `/health/db` returns 503 | PostgreSQL unreachable or wrong URL; the response body names the failure class only. |
| `relation "..." does not exist` | migrations not applied: `alembic upgrade head`. |

## 6. Switching to real transcription and evaluation
Set in `.env`: `OPENAI_API_KEY=...`, `TRANSCRIPTION_PROVIDER=openai`, `EVALUATION_PROVIDER=openai`, then `docker compose up -d --force-recreate backend worker`. The OpenAI paths have **never been run** against the real API by the author; run `RUN_REAL_WHISPER=1 OPENAI_API_KEY=... pytest tests/test_openai_real.py` (generates a tone, costs a few cents) as a first check. Audio and transcripts are sent to OpenAI when these are enabled: tell candidates and check your legal obligations.

## 7. Production considerations (nothing here is optional for real use)
1. **Authentication.** Manager routes use one shared bearer token. It is not per-user authentication: no identities, no audit trail, no revocation per person, **no rate limiting or lockout**. Put the API behind a gateway that adds rate limiting, or add real accounts before real use. Candidate endpoints are protected only by the unguessable session id.
2. **HTTPS.** Terminate TLS in front of both the frontend and the API (the bundled nginx and uvicorn speak plain HTTP). Set `VITE_API_BASE_URL` to the public `https://` API address and `CORS_ORIGINS` to the public frontend origin only.
3. **Environment.** Use `ENVIRONMENT=production` (it blocks mock providers and weak secrets). That means a real `OPENAI_API_KEY` is required; a mock-only public demo must run with `development` and is not a production configuration.
4. **Secrets.** Inject them from the platform's secret store; do not bake them into images (`.dockerignore` already excludes `.env`). Rotate the token by changing `REPORT_ACCESS_TOKEN` and restarting.
5. **Headers and docs.** The nginx config sets `nosniff`, `X-Frame-Options`, `Referrer-Policy` and `Permissions-Policy`; it sets **no** Content-Security-Policy or HSTS (add HSTS at the TLS layer). The API exposes `/docs`, `/redoc` and `/openapi.json` in every environment; restrict them at the proxy if you do not want the API surface public.
6. **Data protection.** Transcripts, candidate names and e-mails are stored in plain text with no retention or deletion workflow; audio is temporary (deleted after processing, stale files purged at start-up). Decide a retention period, back up PostgreSQL (`pg_dump`), encrypt disks, and obtain candidate consent. Automated assessment of candidates is regulated in some jurisdictions.
7. **Scaling.** One backend and one worker (concurrency 2) are configured. Run more workers with `docker compose up -d --scale worker=3` only after testing; the stale-audio purge runs at backend start-up only.
8. **Logging.** Logs avoid transcripts, e-mails and tokens (static test), but `LOG_LEVEL=DEBUG` was not reviewed for third-party libraries. Ship logs somewhere persistent.
9. **Frontend build is not reproducible.** The repository has no `package-lock.json`, so `npm install` resolves new versions at build time. Generate and commit a lockfile (`cd frontend && npm install`) and switch the Dockerfile to `npm ci`.
10. **Not covered at all:** monitoring/alerting, automated backups, CI-built image publishing, blue/green releases, load testing, penetration testing.

## 8. Choosing a hosting approach (manual steps remaining)
The project contains no provider-specific files (no `render.yaml`, `fly.toml`, Kubernetes manifests), and no credentials were available, so no deployment was attempted. The simplest supported approach is **one VM with Docker Compose**:
1. Create a VM (2 vCPU / 4 GB RAM minimum; the spaCy model and optional local Whisper need memory), install Docker, clone/unpack the project.
2. Create `.env` with production values (section 3), set `ENVIRONMENT=production`, real OpenAI key, public `CORS_ORIGINS`, public `VITE_API_BASE_URL`.
3. Put a TLS reverse proxy (Caddy, nginx or the cloud load balancer) in front: `app.example.com → frontend:3000`, `api.example.com → backend:8000`.
4. `docker compose up --build -d`, then run the checks in section 4 against the public URLs, seed or create interviews (`/api/question-bank`), and record the real URL in `docs/FINAL_PROJECT_REPORT.md` only after verifying it.
Managed alternatives (a container platform + managed PostgreSQL + managed Redis) work the same way: one image for API and worker (different start commands), one for the frontend, the same environment variables.

## 9. General troubleshooting
| Symptom | Check |
|---|---|
| Browser shows "network error" | `VITE_API_BASE_URL` wrong or `CORS_ORIGINS` missing the page's exact origin (scheme, host, port). Rebuild the frontend after changing the URL. |
| Microphone does not start | page not on `https://` or `localhost`; browser permission denied. |
| Dashboard says token not accepted / 503 | wrong token; or `REPORT_ACCESS_TOKEN` is blank on the server (503 means disabled). |
| Answers stay "pending" | the worker is not running or cannot reach Redis: `docker compose logs worker`, `/health/redis`. |
| Transcript text starts with "[MOCK TRANSCRIPT]" / scores identical | mock providers are selected (default). |
| Evaluation "failed" with `provider_*` codes | OpenAI key/network/quota; see the code table in README Day 4. |
| Upload rejected | file larger than `AUDIO_MAX_UPLOAD_MB` or longer than `AUDIO_MAX_DURATION_SECONDS`; unsupported type. |
| Frontend build fails in Docker | TypeScript errors (the build type-checks) or no network for `npm install`. |
