import pytest
from pydantic import ValidationError

from pixiv_archive.config import Settings


def test_settings_requires_refresh_token(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PIXIV_REFRESH_TOKEN", "tok")
    monkeypatch.setenv("PIXIV_USER_ID", "12345")
    s = Settings(_env_file=None)
    assert s.pixiv_refresh_token == "tok"
    assert s.pixiv_user_id == 12345
    assert s.api_min_interval_ms == 800
    assert s.image_concurrency == 4
    assert s.sync_interval == "6h"
    assert s.auth_token is None


def test_settings_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PIXIV_REFRESH_TOKEN", "tok")
    monkeypatch.setenv("PIXIV_USER_ID", "1")
    s = Settings(_env_file=None)
    assert s.data_dir == tmp_path
    assert s.db_path == tmp_path / "archive.db"
    assert s.works_dir == tmp_path / "works"
    assert s.logs_dir == tmp_path / "logs"


def test_settings_ensure_dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "nested"))
    monkeypatch.setenv("PIXIV_REFRESH_TOKEN", "tok")
    monkeypatch.setenv("PIXIV_USER_ID", "1")
    s = Settings(_env_file=None)
    s.ensure_dirs()
    assert (tmp_path / "nested" / "works").is_dir()
    assert (tmp_path / "nested" / "logs").is_dir()


def test_settings_user_id_must_be_int(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PIXIV_REFRESH_TOKEN", "tok")
    monkeypatch.setenv("PIXIV_USER_ID", "not-a-number")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
