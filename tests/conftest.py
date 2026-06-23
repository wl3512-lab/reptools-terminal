"""Test config — runs before any test module imports app/database.

Forces a throwaway local SQLite DB (no DATABASE_URL) so tests never touch the
real Postgres, and starts from a clean slate.
"""
import os
import tempfile

os.environ.pop("DATABASE_URL", None)
_db = os.path.join(tempfile.gettempdir(), "_pytest_reptools.db")
if os.path.exists(_db):
    try:
        os.remove(_db)
    except OSError:
        pass
os.environ["REPTOOLS_DB_PATH"] = _db
