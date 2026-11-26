# Rubrics and the question bank (Day 8)

How interview scoring rules and interview questions are configured, validated and managed. Everything here describes
code that exists in this repository; see `docs/PROGRESS.md` for what has and has not been executed.

## 1. Rubric YAML

A rubric is one file `backend/config/rubrics/<name>.yaml` (or `<RUBRICS_DIR>/<name>.yaml`). `Interview.rubric_name` selects
the file; `Question.rubric_key` selects one block inside it (empty = the question type, `technical` or `behavioral`).
**All scoring rules live in YAML; changing a weight, a criterion or a score band needs no code change.**

```yaml
name: backend-engineer          # must equal the file name
version: 1
description: Rubric for backend engineers.
score_scale: { min: 0, max: 10 }          # every criterion is scored on this scale (max <= 100)

question_types:                           # the keys here are the rubric_key values a question may use
  databases:
    description: SQL and data-modelling questions.
    criteria:                             # 1-12 criteria; weights MUST sum to 1.0 (never normalised)
      - key: query_correctness            # lowercase identifier, unique inside the block
        name: Query correctness
        description: Whether the SQL or the reasoning about queries is correct.
        weight: 0.6
        strong_examples: ["Explains why a composite index (a, b) helps WHERE a=? AND b=? but not WHERE b=?."]   # 1-5
        weak_examples:   ["Says 'add an index' without saying on what or why."]                                # 1-5
        score_ranges:                     # bands must cover the scale exactly: no gap, no overlap
          - { min: 0, max: 3, label: Weak,    description: "Mostly incorrect." }
          - { min: 4, max: 7, label: Good,    description: "Correct with minor gaps." }
          - { min: 8, max: 10, label: Strong, description: "Correct, precise, notes edge cases." }
      - key: trade_offs
        name: Trade-offs
        description: Whether costs and alternatives are discussed.
        weight: 0.4
        strong_examples: ["Mentions write amplification and index size."]
        weak_examples: ["Treats indexes as free."]
        score_ranges:
          - { min: 0, max: 3, label: Weak,    description: "No trade-offs." }
          - { min: 4, max: 7, label: Good,    description: "Some trade-offs." }
          - { min: 8, max: 10, label: Strong, description: "Balanced, concrete trade-offs." }
```
`backend/config/rubrics/default.yaml` is the complete reference example (technical and behavioral blocks, 0-10 scale).

### Validation rules (enforced by the Day 4 loader; Day 8 did not change them)
| Rule | Result when broken |
|---|---|
| Unknown or misspelled field, wrong type (a quoted `"0.5"` is not a weight), missing field | error naming the exact location, e.g. `question_types.technical.criteria.0.weight` |
| Weight not in (0, 1], or weights of a block not summing to 1.0 (tolerance 1e-6) | error with the actual sum and a list of the weights; never auto-normalised |
| Duplicate criterion key, key/name pattern, empty or blank text/examples | rejected |
| `score_scale.max <= min`, band outside the scale, `min > max`, first band not at scale min, last not at scale max, gap or overlap between bands | rejected |
| Duplicate YAML keys, Python object tags (`!!python/...`), invalid YAML, not a mapping, file > 256 KiB, not UTF-8 | rejected (YAML parsed with a safe loader) |
| Name unsafe (`../x`, upper case) or different from the file name | rejected before any file is read |
| All problems of a file are reported together (first 20 shown); error text never repeats file content | |

At run time the evaluation pipeline loads the interview's rubric for every answer; a missing/invalid file or unknown key
fails that answer with a clear code (`rubric_missing`, `rubric_invalid`, `rubric_key_unsupported`) instead of guessing.

### Adding or changing a rubric
1. Copy `default.yaml` to `<new-name>.yaml`, set `name:` to the same name, edit criteria / weights / bands.
2. Check it: `cd backend && python -m app.scripts.validate_rubrics` (all files in `config/rubrics`) or
   `python -m app.scripts.validate_rubrics /path/to/folder`. Exit code 0 = all valid, 1 = a problem (listed), 2 = no files.
3. Create an interview that uses it (section 2) or change `rubric_name` of an existing one. Existing evaluations keep the
   rubric name/version they were scored with.
To change weights only, edit the `weight:` values so each block still sums to 1.0.
Rubric files are read at evaluation time, so a changed file applies to answers evaluated afterwards (restart workers if your deployment caches the image).

## 2. Question bank

Questions live in the existing `questions` table (one row belongs to one interview, which already represents the role).
Day 8 added three **optional** columns (migration `0004_question_bank_fields`, additive; existing questions have NULL):

| Field | Meaning | Rules |
|---|---|---|
| `text` | the question | 10-2000 characters after trimming, no control characters |
| `question_type` | `technical` or `behavioral` | an interview of type `technical`/`behavioral` accepts only that type, `mixed` accepts both |
| `rubric_key` | block of the rubric that scores it | default = `question_type`; must exist in the interview's rubric file |
| `category` | grouping slug, e.g. `databases` | lowercase letters, digits, `-`/`_`, starts with a letter, <= 50; stored normalised |
| `difficulty` | `easy`, `medium`, `hard` | optional; **never used for scoring** |
| `expected_skills` | e.g. `["sql", "indexing"]` | <= 10 distinct entries, 1-60 characters, lower-cased, de-duplicated; not shown to candidates |
| `time_limit_seconds` | per-question limit | 10-3600 |
| `position` | order in the interview | default = after the last; must be unused |

Other rules: no duplicate question text inside one interview (case-insensitive); at most 50 questions per interview;
**questions can only be added while the interview has no sessions** (candidates may already be answering; adding a question
would change what "complete" means), create a new interview instead; a new interview is created **inactive** and can be
activated only when it has at least one question and every question's rubric key exists.

## 3. API (all manager-only)

Every route needs `Authorization: Bearer <REPORT_ACCESS_TOKEN>` (the same shared token as the PDF and dashboard routes;
unset token = 503, wrong/missing = 401, checked before anything else). This is **not** per-user authentication.
The public candidate endpoints are unchanged and do not show rubric details or the new metadata.

| Method and path | Purpose | Errors |
|---|---|---|
| `GET /api/question-bank/rubrics` | rubric files: keys, criteria names and weights, scale; invalid files listed as invalid | 401 503 |
| `POST /api/question-bank/interviews` | create an interview (inactive). Body: `title`, `rubric_name`, optional `description`, `interview_type` (default `mixed`), `total_time_limit_seconds` (60-14400) | 409 broken rubric, 422 invalid/unknown rubric |
| `PUT /api/question-bank/interviews/{id}/active` | `{"active": true|false}` shows/hides it for candidates | 404, 409 no questions / unscorable question |
| `POST /api/question-bank/interviews/{id}/questions` | add a question (fields above) | 404, 409 (sessions exist, duplicate, position used, limit), 422 |
| `GET /api/question-bank/questions` | list; filters `interview_id`, `question_type`, `category`, `difficulty`, `skill` (one whole entry), `search` (text contains), `page`, `page_size` (<= 100) | 422 |
| `GET /api/question-bank/questions/{id}` | one question | 404, 422 |

Filters combine with AND; results are ordered by interview title, then position. `%` and `_` in search/filter text are literal.

```bash
export T=<REPORT_ACCESS_TOKEN>  H="Authorization: Bearer $T"  API=http://localhost:8000/api/question-bank
curl -s -H "$H" $API/rubrics
IID=$(curl -s -H "$H" -H 'Content-Type: application/json' -d '{"title":"Backend Engineer","rubric_name":"backend-engineer","interview_type":"technical"}' $API/interviews | python -c 'import sys,json;print(json.load(sys.stdin)["id"])')
curl -s -H "$H" -H 'Content-Type: application/json' -d '{"text":"Explain how database indexes speed up queries.","question_type":"technical","rubric_key":"databases","category":"databases","difficulty":"medium","expected_skills":["sql","indexing"],"time_limit_seconds":120}' $API/interviews/$IID/questions
curl -s -X PUT -H "$H" -H 'Content-Type: application/json' -d '{"active":true}' $API/interviews/$IID/active
curl -s -H "$H" "$API/questions?category=databases&difficulty=medium&skill=sql&page=1&page_size=20"
```

## 4. Running the tests
```bash
cd backend
pytest tests/test_rubric_validation.py tests/test_rubric_loader.py tests/test_rubric_catalog.py   # rubrics, no database needed
pytest tests/test_question_bank_schemas.py tests/test_question_bank_migration_static.py          # question rules, no database needed
pytest tests/test_question_bank_api.py tests/test_migrations.py                                  # need the project dependencies (SQLAlchemy, FastAPI, Alembic)
```

## 5. Known limitations
- One shared token for all managers; no per-user accounts, audit trail or rate limiting.
- Questions cannot be edited or deleted through the API, and interviews cannot be edited after creation (create a new one); rubric files are edited on disk and there is no rubric editor UI.
- No frontend screen for the question bank (Day 8 did not change the frontend).
- A rubric changed on disk applies to answers evaluated afterwards; stored evaluations are not re-scored.
- The `skill` filter matches the JSON text of `expected_skills` (portable between SQLite and PostgreSQL); it relies on the normalisation above.
