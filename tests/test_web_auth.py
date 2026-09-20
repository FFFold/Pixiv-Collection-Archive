import httpx
import pytest
from fastapi import Depends, FastAPI

from pixiv_archive.config import Settings
from pixiv_archive.web.auth import SessionSigner, require_auth


@pytest.fixture
def signer(tmp_path):
    return SessionSigner("test-secret", max_age_seconds=60)


def test_signer_roundtrip(signer):
    token = signer.sign("ok")
    assert signer.verify(token) is True


def test_signer_rejects_tampered_token(signer):
    token = signer.sign("ok")
    assert signer.verify(token + "x") is False
    assert signer.verify("garbage") is False


def test_signer_rejects_expired(monkeypatch):
    signer = SessionSigner("test-secret", max_age_seconds=-1)
    token = signer.sign("ok")
    assert signer.verify(token) is False


def _make_app(signer: SessionSigner) -> FastAPI:
    app = FastAPI()

    @app.get("/protected")
    async def protected(_: str = Depends(require_auth)):
        return {"ok": True}

    app.state.session_signer = signer
    return app


async def test_require_auth_rejects_without_cookie(signer):
    app = _make_app(signer)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        assert (await client.get("/protected")).status_code == 401


async def test_require_auth_accepts_valid_cookie(signer):
    app = _make_app(signer)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        client.cookies.set("session", signer.sign("ok"))
        assert (await client.get("/protected")).status_code == 200


async def test_require_auth_rejects_invalid_cookie(signer):
    app = _make_app(signer)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        client.cookies.set("session", "bad")
        assert (await client.get("/protected")).status_code == 401


def test_session_secret_generated_when_missing(tmp_path):
    settings = Settings(
        _env_file=None,
        PIXIV_REFRESH_TOKEN="t",
        PIXIV_USER_ID=1,
        DATA_DIR=tmp_path,
    )
    secret = settings.session_secret
    assert secret
    assert (tmp_path / "session.secret").exists()
    again = Settings(_env_file=None, PIXIV_REFRESH_TOKEN="t", PIXIV_USER_ID=1, DATA_DIR=tmp_path)
    assert again.session_secret == secret
