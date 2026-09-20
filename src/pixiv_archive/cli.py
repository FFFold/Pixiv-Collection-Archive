import argparse
import asyncio
import logging
import sys

from pixiv_archive.config import Settings
from pixiv_archive.download.scope import DownloadScope
from pixiv_archive.download.worker import DownloadReport
from pixiv_archive.sync.factory import open_download_worker, open_sync_service
from pixiv_archive.sync.orchestrator import SyncResult


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pixiv_archive")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync = subparsers.add_parser("sync", help="run a metadata sync (stage A)")
    sync.add_argument(
        "--mode",
        choices=("incremental", "full"),
        default="incremental",
        help="incremental (default) or full bookmark walk",
    )
    sync.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="stop after N pages (debug/backfill testing)",
    )
    sync.add_argument(
        "--no-previews",
        action="store_true",
        help="skip preview image downloads for this run",
    )

    download = subparsers.add_parser("download", help="download originals (stage B)")
    download.add_argument(
        "--scope",
        choices=("all-missing", "author", "selected", "rank-range", "filter"),
        default="all-missing",
        help="which illusts to download",
    )
    download.add_argument("--author", type=int, default=None, help="author id for --scope author")
    download.add_argument("--pids", default=None, help="comma separated pids for --scope selected")
    download.add_argument("--start", type=int, default=None, help="rank range start (0-based)")
    download.add_argument("--limit", type=int, default=None, help="max number of illusts")
    download.add_argument("--x-restrict", type=int, choices=(0, 1, 2), default=None)
    download.add_argument("--type", choices=("illust", "ugoira"), default=None)
    download.add_argument("--no-thumbs", action="store_true", help="skip thumbnail jobs")
    download.add_argument("--retry-failed", action="store_true", help="re-run failed jobs first")
    return parser


def _scope_from_args(args: argparse.Namespace) -> DownloadScope:
    if args.scope == "author":
        return DownloadScope(kind="author", author_id=args.author)
    if args.scope == "selected":
        pids = [int(part) for part in (args.pids or "").split(",") if part.strip()]
        return DownloadScope(kind="selected", pids=pids)
    if args.scope == "rank-range":
        return DownloadScope(kind="rank_range", start=args.start or 0, count=args.limit)
    if args.scope == "filter":
        return DownloadScope(
            kind="filter", x_restrict=args.x_restrict, type=args.type, author_id=args.author
        )
    return DownloadScope(kind="all_missing")


async def run_sync(argv: list[str], settings: Settings | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = settings or Settings()
    settings.ensure_dirs()

    async with open_sync_service(settings) as service:
        if args.no_previews:
            service.set_download_previews(False)
        if args.mode == "full":
            result = await service.run_full(max_pages=args.max_pages)
        else:
            result = await service.run_incremental(max_pages=args.max_pages)
    _report_sync(result)
    return 0 if result.status == "completed" else 1


async def run_download(argv: list[str], settings: Settings | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = settings or Settings()
    settings.ensure_dirs()
    scope = _scope_from_args(args)

    async with open_download_worker(settings) as worker:
        if args.no_thumbs:
            worker.set_thumb_enabled(False)
        if args.retry_failed:
            await worker.retry_failed()
        report = await worker.run_scope(scope)
    _report_download(report)
    return 0 if report.status in ("completed", "completed_with_failures") else 1


def _report_sync(result: SyncResult) -> None:
    print(
        f"[{result.kind}] {result.status}: "
        f"新增 {result.new_count}，取消 {result.unbookmarked_count}，"
        f"失效 {result.deleted_count}，"
        f"rank 修正 {result.rank_rebuilt_count}，"
        f"页数 {result.pages_fetched}，"
        f"预览图 {result.previews_fetched}（失败 {result.previews_failed}），"
        f"ugoira {result.ugoira_meta_fetched}，"
        f"其它失败 {result.failed_count}"
    )
    for warning in result.warnings:
        print(f"  ! {warning}", file=sys.stderr)
    if result.error:
        print(f"  错误: {result.error}", file=sys.stderr)


def _report_download(report: DownloadReport) -> None:
    print(
        f"[download] {report.status}: "
        f"页码 {report.pages_done}（失败 {report.pages_failed}），"
        f"缩略图 {report.thumbs_done}，"
        f"ugoira {report.ugoira_done}，"
        f"作业失败 {report.failed}"
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        import uvicorn

        from pixiv_archive.web.app import create_app

        uvicorn.run(create_app(), host="0.0.0.0", port=8000)
        return 0
    if argv[0] not in ("sync", "download"):
        build_parser().error(f"unknown command: {argv[0]}")
    if argv[0] == "download":
        return asyncio.run(run_download(argv))
    return asyncio.run(run_sync(argv))
