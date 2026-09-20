import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from pixiv_archive.media.ugoira import (
    UgoiraError,
    build_concat_file,
    ffmpeg_available,
    transcode_to_mp4,
    validate_frames,
)

FFMPEG = shutil.which("ffmpeg")


def _make_zip(path: Path, frames: list[str]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name in frames:
            img = Image.new("RGB", (16, 16), color=(10, 20, 30))
            buffer = path.parent / f"tmp_{name}"
            img.save(buffer, format="JPEG")
            zf.write(buffer, name)
            buffer.unlink()


def test_validate_frames_ok(tmp_path):
    zip_path = tmp_path / "u.zip"
    names = [f"{i:06d}.jpg" for i in range(3)]
    _make_zip(zip_path, names)
    frames = [{"file": name, "delay": 100} for name in names]
    extract_dir = tmp_path / "frames"
    result = validate_frames(zip_path, frames, extract_dir)
    assert result == ["000000.jpg", "000001.jpg", "000002.jpg"]
    assert (extract_dir / "000000.jpg").exists()


def test_validate_frames_missing_member(tmp_path):
    zip_path = tmp_path / "u.zip"
    _make_zip(zip_path, ["000000.jpg"])
    frames = [
        {"file": "000000.jpg", "delay": 100},
        {"file": "000001.jpg", "delay": 100},
    ]
    with pytest.raises(UgoiraError):
        validate_frames(zip_path, frames, tmp_path / "frames")


def test_validate_frames_empty_list(tmp_path):
    zip_path = tmp_path / "u.zip"
    _make_zip(zip_path, ["000000.jpg"])
    with pytest.raises(UgoiraError):
        validate_frames(zip_path, [], tmp_path / "frames")


def test_validate_frames_bad_zip(tmp_path):
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip")
    with pytest.raises(UgoiraError):
        validate_frames(bad, [{"file": "a.jpg", "delay": 1}], tmp_path / "frames")


def test_build_concat_file_format(tmp_path):
    frames = [
        {"file": "000000.jpg", "delay": 100},
        {"file": "000001.jpg", "delay": 50},
        {"file": "000002.jpg", "delay": 33},
    ]
    concat = build_concat_file(frames, tmp_path)
    text = concat.read_text("utf-8")
    assert "file '000000.jpg'" in text
    assert "duration 0.100" in text
    assert "duration 0.050" in text
    assert "duration 0.033" in text
    # last frame is repeated so its duration is honoured
    assert text.rstrip().endswith("file '000002.jpg'")


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_transcode_to_mp4_real_ffmpeg(tmp_path):
    zip_path = tmp_path / "u.zip"
    names = [f"{i:06d}.jpg" for i in range(4)]
    _make_zip(zip_path, names)
    frames = [{"file": name, "delay": 100} for name in names]
    frames_json = json.dumps(frames)
    out = tmp_path / "animation.mp4"
    result = transcode_to_mp4(
        zip_path=zip_path,
        frames_json=frames_json,
        frames_dir=tmp_path / "frames",
        dest=out,
        ffmpeg_bin=str(FFMPEG),
    )
    assert result is True
    assert out.exists() and out.stat().st_size > 0
    probe = subprocess.run(
        [str(FFMPEG), "-v", "error", "-i", str(out), "-f", "null", "-"],
        capture_output=True,
    )
    assert probe.returncode == 0


def test_ffmpeg_available_false_for_missing_binary():
    assert ffmpeg_available("/definitely/not/ffmpeg") is False


def test_transcode_returns_false_without_ffmpeg(tmp_path):
    zip_path = tmp_path / "u.zip"
    _make_zip(zip_path, ["000000.jpg"])
    frames_json = json.dumps([{"file": "000000.jpg", "delay": 100}])
    assert (
        transcode_to_mp4(
            zip_path=zip_path,
            frames_json=frames_json,
            frames_dir=tmp_path / "frames",
            dest=tmp_path / "a.mp4",
            ffmpeg_bin="/definitely/not/ffmpeg",
        )
        is False
    )


def test_transcode_refuses_empty_frames(tmp_path):
    zip_path = tmp_path / "u.zip"
    _make_zip(zip_path, ["000000.jpg"])
    assert (
        transcode_to_mp4(
            zip_path=zip_path,
            frames_json="[]",
            frames_dir=tmp_path / "frames",
            dest=tmp_path / "a.mp4",
            ffmpeg_bin=str(FFMPEG) if FFMPEG else "ffmpeg",
        )
        is False
    )
