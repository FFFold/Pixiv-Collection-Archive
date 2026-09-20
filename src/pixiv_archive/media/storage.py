import json
import os
from pathlib import Path
from typing import Any


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write bytes to ``path`` atomically (temp file + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    try:
        with open(tmp, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                os.remove(tmp)
            except OSError:
                pass


class WorksStorage:
    """Manages the on-disk layout of ``DATA_DIR/works/{pid}``."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def work_dir(self, pid: int) -> Path:
        return self.root / str(pid)

    def preview_path(self, pid: int) -> Path:
        return self.work_dir(pid) / "preview.jpg"

    def thumb_path(self, pid: int) -> Path:
        return self.work_dir(pid) / "thumb.webp"

    def original_dir(self, pid: int) -> Path:
        return self.work_dir(pid) / "original"

    def meta_path(self, pid: int) -> Path:
        return self.work_dir(pid) / "meta.json"

    def animation_path(self, pid: int) -> Path:
        return self.work_dir(pid) / "animation.mp4"

    def has_preview(self, pid: int) -> bool:
        return self.preview_path(pid).exists()

    def save_preview(self, pid: int, data: bytes) -> None:
        atomic_write_bytes(self.preview_path(pid), data)

    def save_meta_json(self, pid: int, payload: dict[str, Any]) -> None:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        atomic_write_bytes(self.meta_path(pid), text.encode("utf-8"))
