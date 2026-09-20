from fastapi import FastAPI

from pixiv_archive import __version__
from pixiv_archive.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings(_env_file=None)
    settings.ensure_dirs()

    app = FastAPI(title="Pixiv Archive", version=__version__)
    app.state.settings = settings

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
