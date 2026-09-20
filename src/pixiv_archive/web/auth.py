from fastapi import Depends, HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

SESSION_COOKIE = "session"
_TOKEN_SALT = "pixiv-archive-session"
_DEFAULT_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


class SessionSigner:
    """Signs and verifies session cookies with a persistent secret."""

    def __init__(self, secret: str, *, max_age_seconds: int = _DEFAULT_MAX_AGE) -> None:
        self._serializer = URLSafeTimedSerializer(secret, salt=_TOKEN_SALT)
        self._max_age = max_age_seconds

    def sign(self, value: str) -> str:
        return self._serializer.dumps(value)

    def verify(self, token: str | None) -> bool:
        if not token:
            return False
        try:
            self._serializer.loads(token, max_age=self._max_age)
        except (BadSignature, SignatureExpired):
            return False
        return True


def get_signer(request: Request) -> SessionSigner:
    signer: SessionSigner | None = getattr(request.app.state, "session_signer", None)
    if signer is None:
        raise HTTPException(status_code=500, detail="session signer not configured")
    return signer


async def require_auth(request: Request, signer: SessionSigner = Depends(get_signer)) -> str:  # noqa: B008
    """Dependency that rejects unauthenticated requests with 401."""
    token = request.cookies.get(SESSION_COOKIE)
    if not signer.verify(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
        )
    return "ok"


def set_session_cookie(response: Response, signer: SessionSigner) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        signer.sign("ok"),
        httponly=True,
        samesite="lax",
        max_age=_DEFAULT_MAX_AGE,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
