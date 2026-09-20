class PixivError(Exception):
    """Base class for all pixiv client errors."""


class AuthError(PixivError):
    """Refresh token missing/invalid or token exchange failed."""


class NetworkError(PixivError):
    """Transient transport failure. Safe to retry."""


class NotFoundError(PixivError):
    """Illust deleted or inaccessible. Do not retry."""


class RateLimited(PixivError):
    """Server asked us to slow down."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after
