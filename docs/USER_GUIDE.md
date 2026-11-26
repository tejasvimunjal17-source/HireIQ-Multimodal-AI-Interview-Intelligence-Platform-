# HireIQ user guide

Who this is for: **candidates** taking an interview and **hiring managers** reviewing results. For installation see `docs/DEPLOYMENT_GUIDE.md`.

Legend: **Available** = implemented in the code. **Needs setup** = implemented but only works with extra configuration. **Not available** = not built. "Verified" statements say what was actually run by the author; most runtime behaviour was **not** run against real services (see `docs/FINAL_PROJECT_REPORT.md`).

> HireIQ's scores, quotes and recommendations are **advice for a human reviewer**. They are not a hiring decision and are not proof that a candidate is or is not suitable.

## Part 1 — Candidates

### 1. Open the interview (Available)
Open the candidate address (default `http://localhost:3000`). Use a current browser (Chrome, Edge, Firefox, Safari) on `https://` or `localhost`; browsers refuse the microphone elsewhere. The welcome page lists the active interviews.

### 2. Start (Available)
Choose an interview, enter your **full name and e-mail address**, tick the consent box and press the start button. The platform stores only your name, e-mail, answers and the results; it does not ask for age, gender, nationality or similar details. Your session id is kept in the browser tab's session storage, so a reload in the same tab continues where you were.

### 3. Answer each question by voice (Available)
1. Read the question. Each question has a time limit; recording stops automatically when it runs out.
2. Press **Start recording** and allow the microphone when the browser asks.
3. Stop, listen to the preview. **Record again** replaces it. You may submit **one** answer per question, so check first.
4. Press **Submit answer**. The audio is uploaded; the answer is marked as submitted.
Uploading a pre-recorded file is **not available**: only in-browser recording exists. Limits: 25 MB and 600 seconds per answer by default.

### 4. Transcription (Available; real speech recognition Needs setup)
After upload each answer shows a transcription status. With the default configuration the "transcript" is **fixed placeholder text** (mock mode) and no speech recognition happens. With `TRANSCRIPTION_PROVIDER=openai` or `local` your speech is transcribed; recognition errors, especially with accents or background noise, can happen. If transcription fails you can use the retry button. You can see your own transcript; you never see scores or recommendations.

### 5. Finish (Available)
When every question is answered, press **Finish interview**. The page says "Interview submitted"; the hiring team reviews your answers. Evaluation runs in the background and can take a little while. The session completes only when all questions are answered.

## Part 2 — Hiring managers

### 6. Open the dashboard (Available; needs `REPORT_ACCESS_TOKEN` on the server)
Go to `/#/dashboard` (for example `http://localhost:3000/#/dashboard`). Candidates are never shown a link to it. Enter the **access token** you were given. It is one shared secret for the whole team, held only in the page's memory (not stored in the browser, cleared on sign-out or reload). Wrong token: "not accepted". If the server has no token set the dashboard answers "disabled" (503). This is **shared-token access, not individual user accounts**: the system does not know who you are and keeps no audit trail.

### 7. Overview and session list (Available)
The overview shows interview sessions, completed interviews, sessions awaiting evaluation, evaluated sessions (with failed evaluations noted), the average score and the number of scored sessions per score range. The session table can be searched by candidate name, and filtered by interview, status and recommendation; it is paged. Sessions without scores say "Not scored", never 0.

### 8. Session details (Available)
Open a session to see: the overall score, status, and for each answer the question, the criterion scores with the model's **explanation and quoted evidence**, strengths and concerns, and the per-answer recommendation. Transcripts, audio paths and e-mail addresses are **not** shown on the dashboard.

### 9. Understanding scores (Available)
Each answer is scored 0–10 per criterion against the YAML rubric (`backend/config/rubrics/default.yaml`; technical and behavioural criteria with weights that sum to 1). The platform computes the weighted average and shows it as 0–100. The session score is the average of its evaluated answers. Quoted evidence must appear word for word in the transcript; the quotes show the words were said, not that they prove the score. Missing information in a short or poorly transcribed answer can lower a criterion. Read the transcript and quotes before relying on a number.

### 10. Understanding recommendations (Available, advisory)
Each answer carries `proceed`, `hold` or `reject` advice produced by the language model. **It is not checked against the score** (a high score with "reject" is possible) and it is not a decision. The session list can be filtered by recommendation and the detail view shows the advice for each answer; there is no final verdict for a candidate. A human must decide.

### 11. Understanding NLP insights (Available; real spaCy/VADER Needs setup)
Shown under "NLP insights · Experimental · advisory": keywords, named entities, sentiment (VADER, English) and a **confidence indicator** from simple rules (word count, hedging words, supporting detail). They **never change the score or recommendation**. They are weak signals: fluent hedging, fillers, short answers, non-English speech and keyword lists can distort them. Do not use sentiment or confidence to judge suitability.

### 12. PDF reports (Available; needs the token)
In a session's detail press **Download PDF report**. The PDF contains the candidate and interview, scores, a criteria chart, evidence, recommendation (marked advisory and confidential) and NLP context. It is disabled when nothing has been evaluated. The same endpoint (`GET /api/reports/{session_id}/pdf`, bearer token) can be called directly. Treat the file as confidential personal data.

### 13. Managing interviews and questions (Available through the API only)
There is no screen for this. Hiring managers or administrators use the token-protected question-bank API (`/api/question-bank/...`, see `docs/RUBRICS_AND_QUESTION_BANK.md`): create an interview, add questions with category, difficulty and expected skills, activate it. New interviews start inactive; questions cannot be edited, deleted or added once candidates have started. Rubrics are YAML files edited on the server and checked with `python -m app.scripts.validate_rubrics`.

## Not available
Per-user logins and roles · e-mail notifications · audio upload of existing files · editing/deleting questions · a question-bank or rubric screen · Gemini evaluation · automatic hiring decisions · re-scoring after a rubric change · candidate data deletion tools · languages other than English for the NLP indicators.

## If something looks wrong
| You see | Meaning |
|---|---|
| Transcript starts with "[MOCK TRANSCRIPT]" or all scores look alike | the server runs in mock mode (demo); no real speech recognition or AI judgement |
| Answer stays "pending" | the background worker or Redis is not running |
| Evaluation "failed" | the model call failed or returned something that did not pass the checks; see the admin; the answer is not scored as zero |
| "No speech detected" | silence or too little audio; record again if still possible |
