import argparse
import asyncio
import logging
import sys

from pixiv_archive.config import Settings
from pixiv_archive.sync.factory import open_sync_service
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
    return parser


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
    _report(result)
    return 0 if result.status == "completed" else 1


def _report(result: SyncResult) -> None:
    print(
        f"[{result.kind}] {result.status}: "
        f"新增 {result.new_count}，取消 {result.unbookmarked_count}，"
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


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        import uvicorn

        from pixiv_archive.web.app import create_app

        uvicorn.run(create_app(), host="0.0.0.0", port=8000)
        return 0
    if argv[0] != "sync":
        build_parser().error(f"unknown command: {argv[0]}")
    return asyncio.run(run_sync(argv))
