"""Check every rubric YAML file.  Run:  python -m app.scripts.validate_rubrics [folder]

Uses the same loader and rules as the evaluation pipeline. Exit code 0 = all valid, 1 = at least one problem,
2 = folder missing or empty. Run it after editing a rubric and before deploying."""

import sys
from pathlib import Path

from app.core.config import DEFAULT_RUBRICS_DIR
from app.services.rubrics.catalog import validate_rubrics_dir


def main(argv: list[str]) -> int:
    folder = Path(argv[1]) if len(argv) > 1 else DEFAULT_RUBRICS_DIR
    reports = validate_rubrics_dir(folder)
    if not reports:
        print(f"No rubric files (*.yaml) found in {folder}")
        return 2
    for report in reports:
        if report.valid and report.rubric is not None:
            rubric = report.rubric
            keys = ", ".join(f"{k} ({len(rubric.question_types[k].criteria)} criteria)" for k in rubric.keys)
            print(f"OK       {report.name}  v{rubric.version}  scale {rubric.score_scale.min}-{rubric.score_scale.max}  keys: {keys}")
        else:
            print(f"INVALID  {report.name}\n{report.error}")
    bad = sum(1 for r in reports if not r.valid)
    print(f"{len(reports) - bad} valid, {bad} invalid")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
