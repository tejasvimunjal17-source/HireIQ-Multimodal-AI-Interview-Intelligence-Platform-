"""Create the sample interview.  Run:  python -m app.scripts.seed_demo"""

from app.core.database import dispose_engine, get_session_factory
from app.services.demo_seed import seed_demo_interview


def main() -> None:
    with get_session_factory()() as db:
        interview, created = seed_demo_interview(db)
        print(f"{'Created' if created else 'Already exists'}: {interview.title} (id={interview.id})")
    dispose_engine()


if __name__ == "__main__":
    main()
