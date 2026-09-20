import os

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Ensure tests never read real credentials from the host environment."""
    for key in list(os.environ):
        if key.startswith("PIXIV_") or key in {"DATA_DIR", "AUTH_TOKEN"}:
            monkeypatch.delenv(key, raising=False)
