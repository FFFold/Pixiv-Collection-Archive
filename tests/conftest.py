import os

import pytest


@pytest.fixture(autouse=True)
def _clean_env(request, monkeypatch):
    """Ensure tests never read real credentials from the host environment.

    Integration tests opt out: they intentionally read real credentials.
    """
    if request.node.get_closest_marker("integration"):
        return
    for key in list(os.environ):
        if key.startswith("PIXIV_") or key in {"DATA_DIR", "AUTH_TOKEN"}:
            monkeypatch.delenv(key, raising=False)
