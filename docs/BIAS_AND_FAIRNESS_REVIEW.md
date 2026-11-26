# HireIQ — AI evaluation bias and fairness review (Day 9)

**Status of this document:** a structured engineering review of the code, prompts, rubric and tests in this repository.
It is **not** a fairness audit and it does **not** show that HireIQ is unbiased or scientifically fair. Passing tests only shows that
the platform's own safeguards behave as written. Whether a real language model and a real speech recogniser treat different
candidates equally has not been measured (section 7).

Every finding says how it was established:

| Label | Meaning |
|---|---|
| **[S] source** | seen by reading the code, prompt or YAML; no test needed or possible |
| **[T] tested** | a controlled test in `backend/tests/test_day9_bias_fairness.py` or `test_day9_security.py` executed and passed (these tests use the deterministic MOCK provider and injected fake NLP objects, never a real model) |
| **[R] real-world** | can only be confirmed with real candidates, a real model or real audio; **not verified** |

**Verdict in one paragraph.** HireIQ's own code contains real safeguards (identity never reaches the model, scores computed from YAML weights, verbatim evidence required,
NLP kept out of the score, advisory wording). It also has documented weaknesses (recommendation not reconciled with score, weak evidence check, minimum score for missing information,
no transcription-quality signal for reviewers, style assumptions inside the rubric, English-only NLP heuristics, no enforced human review). **HireIQ must not be used for fully automated hiring decisions.** Its output is advice
for a trained human reviewer, who must read the transcript and quotes, and who stays responsible for the decision.

## 1. Methodology
1. Read the whole evaluation path: `prompt_builder.py` (system + user prompt), `config/rubrics/default.yaml`, `schemas/evaluation.py`
   (parser and evidence check), `scoring.py`, `persistence.py`, `engine.py`, `services/nlp/*`, the transcription service and
   providers, the dashboard/report schemas, the PDF wording and the candidate-facing schemas.
2. For each risk area in the Day 9 brief, asked: where could this enter, what stops it, what is left, who sees the result.
3. Wrote controlled tests for what code can show deterministically (safeguards that must hold; "known weakness" tests that
   pin down a limitation so it cannot silently change). Tests named `test_known_weakness_*` assert **current** behaviour of a documented limitation; they pass
   because the limitation exists, and must be changed deliberately when it is fixed.
4. Classified everything else as needing real-world validation. No real model, Whisper model, audio or candidate data was used.

## 2. Areas inspected
Evaluation prompts · YAML rubric criteria, weights and bands · LLM output parsing and evidence extraction · weighted scoring ·
recommendations · NLP enrichment (keywords, entities, sentiment, confidence heuristic) · transcription settings · what candidates see ·
what hiring managers see (dashboard, PDF).

## 3. How an answer is judged (what exists)
`audio → Whisper transcript → LLM scores each rubric criterion (0–10) with verbatim quotes → platform checks quotes and scale → platform computes the
weighted score from the YAML weights → stored with the model's recommendation → NLP context stored beside it → manager sees score,
criteria, quotes and an "advisory" recommendation.` The model's own `overall_score` is stored for reference but **not used**.

## 4. Existing safeguards
| # | Safeguard | Evidence |
|---|---|---|
| G1 | System prompt tells the model to ignore accent, pronunciation, dialect, native language, grammar slips, pace, filler words, gender, age, ethnicity, nationality, religion, disability and not to assume identity/background/experience | [S] + [T] wording asserted (`test_safeguard_prompt_*`) — whether a model obeys is **[R]** |
| G2 | Prompt says the transcript is ASR output and apparent recognition mistakes must not be penalised; missing ≠ incorrect | [S][T] wording |
| G3 | The prompt builder can only receive question text, transcript and rubric: the candidate's name and e-mail never reach the model | [T] `test_safeguard_the_prompt_builder_cannot_receive_candidate_identity`, engine source check |
| G4 | The score is the YAML-weighted mean of criterion scores; model overall score, summary wording and recommendation cannot move it | [T] |
| G5 | Strict output validation: unknown/extra fields, out-of-range scores, missing criteria, invented or too-short quotes are rejected; a score above the minimum needs evidence; nothing is repaired | [T] |
| G6 | Evidence matching ignores case, punctuation and spacing, so ASR formatting differences do not invalidate honest quotes | [T] |
| G7 | NLP enrichment runs after scoring, is stored in a separate field, is not imported by the scoring code, and its confidence block carries `affects_evaluation: false` and a disclaimer | [S][T] |
| G8 | NORP entities (nationalities, religious and political groups) are dropped from NLP output | [T] |
| G9 | No column or response field is named after a protected characteristic; the system stores name and e-mail only (no age, gender, etc.) and never infers them | [T] name scan — an inference inside free text is **[R]** |
| G10 | Recommendations are labelled advisory in the PDF ("not a hiring decision; the final decision stays with people") and in the dashboard | [S][T] (PDF text) |
| G11 | Candidates never see scores, recommendations or rubric details | [T] schema check |
| G12 | Transcription language defaults to automatic detection (not forced English) | [T] |
| G13 | No-speech/silence is a system outcome ("skipped"), never a zero score | [S] (existing Day 4 tests) |
| G14 | A prompt-injection attempt inside a transcript is delimited as data, the delimiter cannot be forged, and obedient-but-invented output is rejected | [T] — resistance of a real model is **[R]** |

## 5. Risks and identified weaknesses
Severity is my judgement of potential impact if the weakness is real; none was a code defect needing a Day 9 fix.

### A. Language and communication
| ID | Finding | Basis |
|---|---|---|
| F9 | **The rubric itself carries style assumptions.** *Communication clarity* is 20 % of every technical score; its top band is "concise, structured and easy to follow" and the weak example is "rambles, repeats itself". The YAML says "content, not accent or fluency", which helps, but concision/structure are culturally and educationally shaped. Behavioural rubric: *Ownership* (30 %) asks what the candidate "personally did, as opposed to what the team did" (disadvantages candidates who speak in "we" for cultural reasons); *Situation and structure* (20 %) expects an STAR-style story (advantages coached candidates); *Results and impact* (25 %) rewards "measurable effect" (disadvantages early-career candidates with little to measure). Technical accuracy's top band wants "precise terminology" (self-taught candidates may explain correctly in other words). | [S] — effect size **[R]** |
| F6 | The confidence heuristic lowers a candidate for hedging phrases ("maybe", "I think", "kind of"); the same content hedged scores lower. The phrase list is English only (a Spanish "quizás no estoy seguro" is not detected), so behaviour differs by language and politeness style. Advisory only. | [T] |
| F5 | Filler words ("um", "you know") are counted as words and **raise** the completeness signal, although the module comment says filler words are "deliberately not used". Documentation and behaviour disagree. Advisory only. | [T] |
| — | Sentiment (VADER) reads English tone; the note on the field says it is not a measure of competence. The dashboard shows its label. Not tested against non-English text. | [S] |

### B. Education and background
| ID | Finding | Basis |
|---|---|---|
| F9 | See above: STAR structure, quantified results and formal terminology favour coached, experienced or formally trained candidates. Technical and non-technical candidates share the same two blocks (`technical`, `behavioral`); a non-technical role needs its own rubric file (Day 8 makes that possible; none ships). | [S] |
| — | No question or score is adjusted for experience level (by design, to avoid inferring it). Entry-level and senior candidates get identical bands. | [S] |

### C. Audio and transcription
| ID | Finding | Basis |
|---|---|---|
| F4 | The only transcription-quality signal stored is "no speech". There is **no per-answer ASR confidence, noise or low-quality flag**, so a reviewer cannot tell a poor transcript from a poor answer. Accent-related recognition errors, background noise and omitted words go straight into the evaluation. The prompt asks the model not to penalise apparent ASR mistakes, but it cannot know what was omitted. | [S][T] (model has no such column) — error rates by accent **[R]** |
| F3 | When the transcript has no evidence for a criterion the prompt instructs the model to give the scale **minimum**, and the validator accepts it. Omissions (a short answer, an ASR gap) can therefore become a 0 on that criterion — "missing information" is not scored as incompetent *wording*, but it is scored as lowest. This sits in tension with safeguard "missing information is not incompetence". | [T] |
| — | Answers over 20 000 characters are refused, not truncated (fair to long speakers, but they fail evaluation and need manual handling). | [S] |
| — | An English-language prompt and English NLP are used even when Whisper auto-detects another language; behaviour on non-English answers is untested. | [S] **[R]** |

### D. Scoring
| ID | Finding | Basis |
|---|---|---|
| F1 | **Recommendation is not reconciled with the score.** The model's `proceed/hold/reject` is stored as given; a 100 % weighted score with `reject` (and the reverse) is accepted. It is labelled advisory but nothing checks consistency, so an unjustified recommendation can reach the reviewer. The dashboard shows only counts of per-answer advice and the PDF shows both; a reviewer can spot the mismatch, the system will not. | [T] |
| F2 | **Evidence proves the words were said, not that they support the score.** A quote of 3 words is enough, the same quote can back every criterion, and no relevance check exists. "Hallucinated evidence" is blocked; "irrelevant evidence" is not. | [T] |
| F7 | **Keyword reliance in the confidence heuristic:** a list of technical terms scores higher on *supporting detail* than a correct sentence (advisory signal, tested). The LLM's own keyword sensitivity is **[R]**. | [T] |
| F10 | No repeated-run or variance measurement exists: an LLM may score the same answer differently on another day. The score is shown with one decimal place and no uncertainty. | [S] **[R]** |
| — | Short correct answers receive a lower confidence label than long ones (completeness saturates at 40 words). Advisory only. | [T] |

### E. Fairness safeguards — checklist from the brief
| Requirement | Result |
|---|---|
| Scores grounded in the configured rubric | Yes for the arithmetic (G4, tested); whether the model's criterion scores follow the rubric text is **[R]** |
| Evidence supports the score | Partly: verbatim, but not relevance-checked (F2) |
| Missing information not read as incompetence | Prompt says so (G2) but the minimum-score rule works against it (F3) |
| NLP sentiment/confidence do not decide suitability | Yes, by construction (G7, tested); their *display* next to the score can still anchor a human (**[R]**) |
| No inference of protected characteristics | No such fields or code (G9); the model's free-text summary could still mention them (**[R]**, not filtered) |
| Recommendations advisory | Wording yes (G10); **no workflow enforces human review** — there is no reviewer sign-off, audit trail or override record |
| Human review remains necessary | Stated in documents; not enforced by the system |
| PERSON/place entities | Kept and shown to managers (F8): they can correlate with origin or gender. Context only, but worth removing from the manager view |

## 6. Recommended improvements (not implemented in Day 9)
Ordered by value for effort; each would be a separate, reviewed change.
1. **Reconcile recommendation and score** in code: derive the displayed advice from the weighted score and thresholds in the YAML, or reject/flag mismatches (F1).
2. **Show the transcript quality** to reviewers: store Whisper segment confidence/no-speech probability and flag low-quality answers; let a reviewer mark "re-record" (F4).
3. **Review the rubric text with domain and diversity reviewers**: make the ownership criterion accept "we" statements that describe the candidate's role, accept non-STAR structures, remove "precise terminology" as a band requirement, and add role-specific rubrics (F9, B).
4. **Do not let missing evidence be the minimum automatically**: add a "not enough evidence" outcome that is excluded from the weighted mean and flagged for a human (F3).
5. **Evidence quality**: require relevance (e.g. a longer minimum quote, or a second-pass check) and disallow one quote backing every criterion (F2).
6. **Remove or relabel NLP items** that add risk without value: drop PERSON/GPE from the manager view, count filler words out of the completeness signal, and fix the contradicting comment (F5, F8). Consider hiding the confidence label by default.
7. **Human-in-the-loop record:** reviewer name, decision and reason stored with each session; the dashboard shows "advice (not decision)".
8. **Validation study** (section 7) before any real use, plus periodic re-checks after model or prompt changes (`PROMPT_VERSION` is stored with every evaluation to support this).
9. **Repeat scoring** (e.g. three runs) and show disagreement (F10).

## 7. Needs real-world validation (not done, cannot be done offline)
- Paired answers with the same content in different accents/proficiency levels/styles, scored by the real model: compare score gaps.
- Word-error-rate of the chosen Whisper model across accents, microphones and noise levels; effect of transcription errors on scores.
- Agreement with trained human raters (per criterion), and run-to-run variance of the model.
- Outcome differences between demographic groups. The system deliberately stores no demographic data, so such an audit needs a separate, consented process.
- Prompt-injection red-team against the real model; adversarial candidates who read the rubric.
- Behaviour on non-English answers and code-switching.
- Legal review: automated assessment of candidates is regulated in several jurisdictions (notice, consent, human review, explanation rights). Not assessed here.

## 8. Coverage of the topics required by the Day 9 brief
| Topic | Where | Evidence classes used |
|---|---|---|
| Language and communication bias | 5A (F5, F6, F9) | S, T |
| Educational and professional background bias | 5B (F9) | S (effect: R) |
| Accent and transcription risks | 5C (F3, F4), section 7 | S, T, R |
| Scoring consistency | 5D (F10), G4 | T (determinism of our code only), R |
| Evidence-grounded evaluation | G5, G6, F2 | T |
| Keyword over-reliance | F7 | T (heuristic only), R (model) |
| Unsupported deductions / unjustified recommendations | F1, F3 | T |
| NLP sentiment/confidence misuse | G7, F5–F8 | S, T |
| Human oversight | 5E table, recommendation 7 | S (not enforced by the system) |
| Limitations of the review | section 9 | — |

## 9. Limitations of this review
One reviewer, one pass, source reading plus deterministic tests; no real model, audio, candidate data or demographic data was used; the mock provider
returns fixed scores, so controlled "equivalent answer" tests of the model could not be run; severity labels are judgement; only the shipped
`default.yaml` rubric was reviewed; third-party model behaviour and future model changes are outside the review. A clean result here would not mean the platform is fair.
