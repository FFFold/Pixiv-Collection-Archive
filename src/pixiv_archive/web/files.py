import hashlib
from collections.abc import Iterator
from pathlib import Path

from fastapi import HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse

CHUNK_SIZE = 256 * 1024

_EXT_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".zip": "application/zip",
    ".json": "application/json",
    ".svg": "image/svg+xml",
}


def content_type_for(path: Path) -> str:
    return _EXT_CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Parse a single-range ``bytes=`` header into inclusive bounds."""
    if not header or not header.startswith("bytes="):
        return None
    spec = header[len("bytes=") :].strip()
    if "," in spec or "-" not in spec:
        return None
    start_text, _, end_text = spec.partition("-")
    try:
        if start_text == "":
            length = int(end_text)
            if length <= 0:
                return None
            start = max(0, size - length)
            end = size - 1
        else:
            start = int(start_text)
            end = int(end_text) if end_text else size - 1
    except ValueError:
        return None
    if start < 0 or start >= size or end < start:
        return None
    return start, min(end, size - 1)


def build_etag(path: Path) -> str:
    stat = path.stat()
    signature = f"{stat.st_mtime_ns:x}-{stat.st_size:x}"
    digest = hashlib.sha1(signature.encode()).hexdigest()[:16]
    return f'"{digest}"'


def file_not_modified(if_none_match: str | None, etag: str) -> bool:
    return bool(if_none_match) and if_none_match == etag


def resolve_thumb(works_root: Path, pid: int) -> Path | None:
    """Prefer the locally generated thumbnail, then pixiv's preview image."""
    work = works_root / str(pid)
    for candidate in (work / "thumb.webp", work / "preview.jpg"):
        if candidate.is_file():
            return candidate
    return None


def placeholder_svg(pid: int) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="400">'
        '<rect width="100%" height="100%" fill="#1f2937"/>'
        f'<text x="50%" y="50%" fill="#6b7280" font-family="sans-serif" '
        f'font-size="20" text-anchor="middle">#{pid}</text></svg>'
    )


def placeholder_response(pid: int) -> Response:
    return Response(content=placeholder_svg(pid), media_type="image/svg+xml")


def file_response(request: Request, path: Path, *, download_name: str | None = None) -> Response:
    """Serve a local file with ETag and optional Range support."""
    if not path.is_file():
        raise HTTPException(status_code=404, detail="file not found")

    etag = build_etag(path)
    if file_not_modified(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers={"ETag": etag})

    size = path.stat().st_size
    content_type = content_type_for(path)
    headers = {"ETag": etag, "Accept-Ranges": "bytes"}
    if download_name:
        headers["Content-Disposition"] = f'attachment; filename="{download_name}"'

    bounds = parse_range(request.headers.get("range"), size)
    if bounds is None:
        return FileResponse(path, media_type=content_type, headers=headers)

    start, end = bounds
    length = end - start + 1

    def _iter() -> Iterator[bytes]:
        with open(path, "rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining > 0:
                chunk = handle.read(min(CHUNK_SIZE, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    range_headers = dict(headers)
    range_headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    range_headers["Content-Length"] = str(length)
    return StreamingResponse(
        _iter(), status_code=206, media_type=content_type, headers=range_headers
    )
