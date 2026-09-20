import json
import logging
import shutil
import subprocess
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_FFMPEG = "ffmpeg"


class UgoiraError(Exception):
    """ugoira zip is corrupt or does not match the frame list."""


def ffmpeg_available(ffmpeg_bin: str) -> bool:
    return shutil.which(ffmpeg_bin) is not None


def validate_frames(zip_path: Path, frames: list[dict], extract_dir: Path) -> list[str]:
    """Extract the zip and confirm every frame in ``frames`` exists.

    Returns the ordered list of member names. Raises UgoiraError on any
    mismatch so a truncated download is never treated as valid.
    """
    if not frames:
        raise UgoiraError("frame list is empty")
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = set(zf.namelist())
            missing = [frame["file"] for frame in frames if frame.get("file") not in names]
            if missing:
                raise UgoiraError(f"zip missing {len(missing)} frames (e.g. {missing[0]})")
            extract_dir.mkdir(parents=True, exist_ok=True)
            zf.extractall(extract_dir)
    except zipfile.BadZipFile as exc:
        raise UgoiraError(f"invalid zip: {exc}") from exc
    return [frame["file"] for frame in frames]


def build_concat_file(frames: list[dict], dest_dir: Path, name: str = "frames.txt") -> Path:
    """Write an ffmpeg concat script with per-frame durations.

    The final frame is listed twice because ffmpeg ignores the duration of
    the last entry in a concat list.
    """
    lines: list[str] = []
    for frame in frames:
        lines.append(f"file '{frame['file']}'")
        lines.append(f"duration {max(0.001, frame['delay'] / 1000.0):.3f}")
    if frames:
        lines.append(f"file '{frames[-1]['file']}'")
    path = dest_dir / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def transcode_to_mp4(
    *,
    zip_path: Path,
    frames_json: str,
    frames_dir: Path,
    dest: Path,
    ffmpeg_bin: str = DEFAULT_FFMPEG,
    timeout: int = 600,
) -> bool:
    """Validate the zip and transcode it to an H.264 mp4.

    Returns False (without raising) when ffmpeg is unavailable, the frame
    list is empty, or transcoding fails — the caller keeps the zip in that
    case and records a status.
    """
    if not ffmpeg_available(ffmpeg_bin):
        logger.warning("ffmpeg not available (%s); skipping transcode", ffmpeg_bin)
        return False
    try:
        frames = json.loads(frames_json)
    except ValueError:
        return False
    if not frames:
        return False

    try:
        validate_frames(zip_path, frames, frames_dir)
    except UgoiraError:
        logger.exception("ugoira validation failed for %s", zip_path)
        return False

    concat_path = build_concat_file(frames, frames_dir)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_dest = dest.with_name(dest.name + ".part")
    command = [
        ffmpeg_bin,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_path),
        "-vsync",
        "vfr",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-loglevel",
        "error",
        "-f",
        "mp4",
        str(tmp_dest),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=frames_dir,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("ffmpeg failed for %s: %s", zip_path, exc)
        return False
    if completed.returncode != 0:
        logger.warning(
            "ffmpeg returned %s for %s: %s",
            completed.returncode,
            zip_path,
            completed.stderr.decode("utf-8", "replace")[:500],
        )
        if tmp_dest.exists():
            tmp_dest.unlink()
        return False
    tmp_dest.replace(dest)
    return True
