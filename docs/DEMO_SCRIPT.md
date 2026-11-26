# HireIQ demo script (about 6½ minutes)

**Honesty rule for the demo.** Say clearly, at the start, which mode you are in. With the default configuration the transcripts are fixed placeholder text and the scores come from a **mock** evaluator: the demo shows the *workflow and safeguards*, not real speech recognition or real AI judgement. Do not call it "AI scoring this candidate". If you have a valid `OPENAI_API_KEY` and have set `TRANSCRIPTION_PROVIDER=openai` and `EVALUATION_PROVIDER=openai`, you may demo real behaviour, but those paths have never been run by the author, so rehearse first. Do not claim the application is deployed (it is not) or that anything not listed in "Features that actually work" is finished.

## Preparation (before the audience arrives)
```bash
cp .env.example .env     # set POSTGRES_PASSWORD, SECRET_KEY, REPORT_ACCESS_TOKEN (>= 16 chars); keep mock providers
docker compose up --build -d
docker compose exec backend python -m app.scripts.seed_demo
curl -fsS localhost:8000/health/db && curl -fsS localhost:8000/health/redis
```
Open two tabs: `http://localhost:3000` (candidate) and `http://localhost:3000/#/dashboard`. Have `REPORT_ACCESS_TOKEN` ready (do not show it on screen). Use a laptop with a microphone on `localhost`. **Rehearse the whole run once**: the Compose start-up and the full candidate → dashboard path were never executed by the author, so a dry run is mandatory. Fallback if the stack does not start: say so, and show the code, `docs/` and the executed test results instead; do not fake a screen.
Backup option without a backend: `VITE_DEMO_MODE=true npm run dev` in `frontend/` shows the candidate UI with built-in sample data (clearly labelled demo mode; nothing is sent to a server).

## Script
| Time | Say | Show |
|---|---|---|
| 0:00 – 0:40 **1. Introduction** | "HireIQ is a multimodal interview intelligence platform built for the CODE-A-NOVA internship. Candidates answer interview questions by voice, the system transcribes and scores the answers against a written rubric, and hiring managers review the results. It *assists* human reviewers; it never decides. Today I'm running it with mock AI providers, so the transcripts and scores are placeholders." | title slide or README top |
| 0:40 – 1:20 **2. Problem** | "First-round interviews are slow, inconsistent and hard to compare. The idea: same questions for everyone, one written rubric, quoted evidence for each score, and one place for a reviewer to see it." | one slide, three bullets |
| 1:20 – 2:20 **3. Architecture and stack** | "React and TypeScript front end; FastAPI back end; PostgreSQL for data; Redis and Celery for background work, because transcription and evaluation take time; Whisper for speech; an LLM for evaluation; spaCy and VADER for NLP; ReportLab for the PDF; all in Docker Compose." Point at each box. "Everything the AI returns is validated before it is stored." | Mermaid diagram from `docs/ARCHITECTURE.md` |
| 2:20 – 3:30 **4. Interview workflow** | "A candidate opens the page, enters name and e-mail and consents. Each question has a time limit. I press record, answer, listen to the preview and submit. The audio is queued; the page shows transcription status." Submit one answer. "Here the transcript is the mock placeholder." Answer the remaining questions and press **Finish interview**. | candidate tab: welcome → question → recorder → transcription panel → "Interview submitted" |
| 3:30 – 4:30 **5. AI evaluation** | "In the background the worker loads the interview's YAML rubric, builds the prompt, and the model must return strict JSON: a 0–10 score per criterion with a quote from the transcript. We reject anything malformed, out of range, or with quotes that are not in the transcript. The final score is computed by our code from the YAML weights, not taken from the model." Open `backend/config/rubrics/default.yaml`: weights and bands. | rubric file; dashboard detail (next) |
| 4:30 – 5:05 **6. NLP enrichment** | "Next to the score we show keywords, entities, sentiment and a confidence indicator. They are labelled experimental and advisory, and they cannot change the score. They are weak signals and can be biased, so reviewers are told not to judge suitability by them." | "NLP insights · Experimental · advisory" panel |
| 5:05 – 5:35 **7. PDF report** | "From the session detail, one click downloads a PDF: candidate, interview, scores, a criteria chart, the quoted evidence, and an advisory notice. It is generated from stored data only." Open the downloaded PDF. | Download PDF report button, PDF page 1–2 |
| 5:35 – 6:05 **8. Hiring manager dashboard** | "Managers open the dashboard route and enter an access token; wrong token, clear error. They see totals, average score, can search and filter by status and recommendation, page through sessions and open one. Transcripts, e-mails and audio paths are not shown." Show the filter and the detail. | dashboard tab |
| 6:05 – 6:35 **9. Security and fairness** | "Be honest about limits: manager access is one shared token, not user accounts, and there is no rate limiting. We wrote security and bias tests and a bias review: for example the recommendation is not checked against the score, missing information can lower a score, and the rubric contains style assumptions. Nothing has been validated with real candidates or real models. A human must always decide." | `docs/BIAS_AND_FAIRNESS_REVIEW.md` summary table |
| 6:35 – 7:00 **10. Closing** | "HireIQ shows a complete, configurable, documented pipeline from voice answer to reviewer report, with safeguards and an honest list of what remains: real-service verification, deployment, per-user authentication and fairness validation. Thank you — questions?" | `docs/FINAL_PROJECT_REPORT.md` limitations |

## Features that actually work in this demo (when the stack starts)
Candidate UI and recording · upload and (mock) transcription · mock evaluation with the real rubric, validation and weighted scoring · advisory NLP block (spaCy/VADER are installed in the image; if they were unavailable the block shows a partial status) · PDF download · dashboard with token gate, search, filters, paging and details.
## Do NOT claim
Real speech recognition or real AI scoring (unless you configured and tested it) · Gemini support · deployment or a public URL · per-user login · that the bias review proves fairness · that every test passed (many database/API/service tests have never run).

## Likely questions (short answers)
- *Is the score objective?* No. It depends on the model, the rubric text and the transcript quality; the bias review lists the risks.
- *Where do candidate data go?* PostgreSQL (name, e-mail, transcript, scores). With OpenAI providers the audio and text are sent to OpenAI. There is no retention policy yet.
- *Why a shared token?* The project has no user accounts; it protects the manager routes minimally and is documented as not production authentication.
- *Can I add questions or a new rubric?* Yes: a YAML file validated by `python -m app.scripts.validate_rubrics`, and the token-protected question-bank API (no UI).
