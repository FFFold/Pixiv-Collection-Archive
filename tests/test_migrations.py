import os
import subprocess
import sys


def test_migrations_create_schema(tmp_path):
    db_file = tmp_path / "archive.db"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ["PATH"],
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "DATA_DIR": str(tmp_path),
            "PIXIV_REFRESH_TOKEN": "tok",
            "PIXIV_USER_ID": "1",
        },
    )
    assert result.returncode == 0, result.stderr

    names = _table_names(db_file)
    assert {"illust", "author", "bookmark", "app_setting"} <= names
    assert "alembic_version" in names


def _table_names(db_file) -> set[str]:
    import sqlite3

    conn = sqlite3.connect(db_file)
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    finally:
        conn.close()
    return {r[0] for r in rows}
