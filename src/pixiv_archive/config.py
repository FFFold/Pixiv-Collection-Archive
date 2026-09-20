from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    pixiv_refresh_token: str = Field(validation_alias="PIXIV_REFRESH_TOKEN")
    pixiv_user_id: int = Field(validation_alias="PIXIV_USER_ID")
    pixiv_proxy: str | None = Field(default=None, validation_alias="PIXIV_PROXY")
    pixiv_image_mirror: str | None = Field(default=None, validation_alias="PIXIV_IMAGE_MIRROR")

    data_dir: Path = Field(default=Path("/data"), validation_alias="DATA_DIR")
    auth_token: str | None = Field(default=None, validation_alias="AUTH_TOKEN")

    sync_interval: str = Field(default="6h", validation_alias="SYNC_INTERVAL")
    sync_full_cron: str | None = Field(default=None, validation_alias="SYNC_FULL_CRON")
    api_min_interval_ms: int = Field(default=800, validation_alias="API_MIN_INTERVAL_MS")
    image_concurrency: int = Field(default=4, validation_alias="IMAGE_CONCURRENCY")
    download_previews: bool = Field(default=True, validation_alias="DOWNLOAD_PREVIEWS")
    ffmpeg_bin: str = Field(default="ffmpeg", validation_alias="FFMPEG_BIN")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "archive.db"

    @property
    def works_dir(self) -> Path:
        return self.data_dir / "works"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.works_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
