"""Seed the application database (realthor.db) from users.csv.

Builds the ``users`` table with a credential column the CSV never had, giving
every seeded user the shared development password. Idempotent: re-running
replaces existing rows. Run as part of ``generate_all.py`` and by ``ops.sh``
before the evaluation, and lazily on first app startup if the database is empty.
"""

from pathlib import Path

from realthor.auth import DEV_PASSWORD, hash_password
from realthor.sessions import seed_users_from_csv

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
APP_DB = ROOT / "realthor.db"


def main():
    users_csv = DATA_DIR / "users.csv"
    password_hash = hash_password(DEV_PASSWORD)
    n = seed_users_from_csv(str(APP_DB), str(users_csv), password_hash)
    print(f"  realthor.db ({n} users seeded; dev password '{DEV_PASSWORD}')")


if __name__ == "__main__":
    main()
