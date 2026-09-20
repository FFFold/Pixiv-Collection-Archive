import os
import subprocess
import sys

from sqlalchemy import text

from pixiv_archive.db.engine import Database


async def test_migrations_create_schema(tmp_path):
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

    db = Database(db_file)
    async with db.session() as session:
        rows = await session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        )
        names = {r[0] for r in rows}
    await db.dispose()
    assert {"illust", "author", "bookmark", "app_setting"} <= names
    assert "alembic_version" in names
