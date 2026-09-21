"""Maintenance operations that reconcile the DB with the works directory."""

from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.db.models import Bookmark, Illust, IllustPage, IllustTag
from pixiv_archive.media.storage import file_size

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".gif", ".webp")


def _work_files(works: Path, pid: int) -> tuple[list[Path], Path, Path, Path]:
    work = works / str(pid)
    original = work / "original"
    originals = (
        sorted(path for path in original.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES)
        if original.is_dir()
        else []
    )
    return originals, work / "thumb.webp", work / "animation.mp4", work / "source.zip"


async def rebuild_storage_stats(session: AsyncSession, works: Path) -> dict[str, int]:
    """Recompute byte_size / thumb_ready / animation_ready for every illust."""
    pids = list((await session.execute(select(Illust.pid))).scalars().all())
    total_bytes = 0
    for pid in pids:
        originals, thumb, animation, zip_path = _work_files(works, pid)
        size = sum(file_size(path) for path in (*originals, thumb, animation, zip_path))
        total_bytes += size
        await session.execute(
            update(Illust)
            .where(Illust.pid == pid)
            .values(
                byte_size=size,
                thumb_ready=thumb.is_file(),
                animation_ready=animation.is_file(),
            )
        )
    await session.commit()
    return {"works": len(pids), "total_bytes": total_bytes}


async def preview_repair_download_state(session: AsyncSession, works: Path) -> dict[str, int]:
    """Count what ``repair_download_state`` would change (no writes)."""
    pages_to_reset = 0
    works_to_fix = 0
    rows = (
        await session.execute(
            select(IllustPage.pid, IllustPage.page_index, IllustPage.download_state)
        )
    ).all()
    by_pid: dict[int, list[tuple[int, str]]] = {}
    for pid, page_index, state in rows:
        by_pid.setdefault(pid, []).append((page_index, state))
    for pid, pages in by_pid.items():
        originals, *_ = _work_files(works, pid)
        present = {path.name.split("_", 1)[0] for path in originals}
        changed = 0
        for page_index, state in pages:
            exists = f"{page_index:03d}" in present
            if (state == "done" and not exists) or (state != "done" and exists):
                changed += 1
        if changed:
            pages_to_reset += changed
            works_to_fix += 1
    return {"pages_to_reset": pages_to_reset, "works_to_fix": works_to_fix}


async def repair_download_state(session: AsyncSession, works: Path) -> dict[str, int]:
    """Reconcile page download_state / counts / has_original with the disk."""
    fixed_pages = 0
    touched_works = 0
    rows = (
        await session.execute(
            select(IllustPage.pid, IllustPage.page_index, IllustPage.download_state)
        )
    ).all()
    by_pid: dict[int, list[tuple[int, str]]] = {}
    for pid, page_index, state in rows:
        by_pid.setdefault(pid, []).append((page_index, state))
    for pid, pages in by_pid.items():
        originals, *_ = _work_files(works, pid)
        present = {path.name.split("_", 1)[0] for path in originals}
        for page_index, state in pages:
            exists = f"{page_index:03d}" in present
            if state == "done" and not exists:
                await session.execute(
                    update(IllustPage)
                    .where(IllustPage.pid == pid, IllustPage.page_index == page_index)
                    .values(download_state="pending", last_error="file missing on disk")
                )
                fixed_pages += 1
            elif state != "done" and exists:
                await session.execute(
                    update(IllustPage)
                    .where(IllustPage.pid == pid, IllustPage.page_index == page_index)
                    .values(download_state="done", last_error=None)
                )
                fixed_pages += 1
        total = len(pages)
        done = len(present)
        await session.execute(
            update(Illust)
            .where(Illust.pid == pid)
            .values(page_downloaded_count=done, has_original=(done == total and total > 0))
        )
        touched_works += 1
    await session.commit()
    return {"pages_fixed": fixed_pages, "works_fixed": touched_works}


async def db_check(session: AsyncSession, works: Path) -> dict[str, Any]:
    """Read-only integrity report: DB internals plus DB/disk mismatches."""
    issues: list[dict[str, Any]] = []

    integrity = (await session.execute(text("PRAGMA integrity_check"))).scalar_one()
    if integrity != "ok":
        issues.append({"kind": "integrity", "count": 1, "samples": [str(integrity)]})

    for name, stmt in (
        (
            "orphan_bookmark",
            select(Bookmark.pid).where(~Bookmark.pid.in_(select(Illust.pid))),
        ),
        (
            "orphan_page",
            select(IllustPage.pid).where(~IllustPage.pid.in_(select(Illust.pid))),
        ),
        (
            "orphan_illust_tag",
            select(IllustTag.pid).where(~IllustTag.pid.in_(select(Illust.pid))),
        ),
    ):
        rows = (await session.execute(stmt)).all()
        if rows:
            issues.append(
                {"kind": name, "count": len(rows), "samples": [int(row[0]) for row in rows[:5]]}
            )

    duplicate_rank = (
        await session.execute(
            select(Bookmark.rank, func.count())
            .where(Bookmark.state == "active")
            .group_by(Bookmark.rank)
            .having(func.count() > 1)
        )
    ).all()
    if duplicate_rank:
        issues.append(
            {
                "kind": "duplicate_rank",
                "count": len(duplicate_rank),
                "samples": [int(rank) for rank, _ in duplicate_rank[:5]],
            }
        )

    missing_files = 0
    missing_samples: list[int] = []
    mismatch_rows = (
        (await session.execute(select(Illust.pid).where(Illust.has_original.is_(True))))
        .scalars()
        .all()
    )
    for pid in mismatch_rows:
        originals, *_ = _work_files(works, pid)
        if not originals:
            missing_files += 1
            if len(missing_samples) < 5:
                missing_samples.append(int(pid))
    if missing_files:
        issues.append({"kind": "missing_files", "count": missing_files, "samples": missing_samples})

    return {"ok": not issues, "issues": issues}
