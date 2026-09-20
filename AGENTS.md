# AGENTS.md

Self-hosted pixiv bookmark sync/archive. Python 3.12 (`uv`, src layout) backend + React 19 frontend built into the backend package. SQLite + Alembic; single Docker container.

## Commands

Backend (repo root, venv `.venv` managed by `uv`):

```powershell
uv sync
uv run pytest -q                          # unit tests; integration excluded by default
uv run pytest tests/test_config.py::test_x -q   # single test
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy                               # strict, only checks src/ (configured in pyproject.toml)
```

CI order is lint -> format check -> mypy -> pytest. `ruff format` is authoritative (no prettier/black).

Frontend (run from `frontend/`, Node 22):

```powershell
npm ci
npm run lint; npm run typecheck; npm test; npm run build
npm test -- src/api/client.test.ts       # single test file
```

`npm run build` = `tsc -b && vite build`, outputs to `../src/pixiv_archive/web/static/` (**this build output is committed to git** so a fresh clone serves the UI without npm). After any frontend source change, re-run `npm run build` or the Python server keeps serving the stale bundle. Do not delete `web/static/`.

Integration tests hit the real pixiv API (need real credentials, proxy, existing archive):

```powershell
$env:PIXIV_PROXY = "http://127.0.0.1:7897"
uv run pytest tests/test_integration_live.py -m integration -v -s
```

DB migrations live in `src/pixiv_archive/db/migrations/versions/`; apply with `alembic upgrade head`. `_ensure_schema` in `sync/factory.py` runs it automatically at app/CLI startup.

## Architecture

- Entrypoint: `uv run python -m pixiv_archive` (no subcommand: uvicorn web server on :8000; `sync` / `download` subcommands in `cli.py`).
- `pixiv/` = raw API client (auth, rate limit, retries). Only stage A (sync) uses it.
- `sync/` = stage A metadata sync. Bookmark order is modeled as sparse `Bookmark.rank` (smaller = newer) + position snapshots; there is no per-bookmark timestamp in the API. Incremental places new pids in front of existing ranks; full walk rebuilds ranks and marks absent pids `unbookmarked`.
- `sync/unavailable.py` = pure detector for pixiv's deleted/private placeholder stubs (`s.pximg.net/common/images/limit_*` or `user.id == 0`). Full sync checks every listed work; incremental only checks the pages it actually fetched; a detected stub becomes `Illust.state="deleted"` **without** overwriting metadata/URLs/files (new stubs get a bare row with `author_id=0`, `page_count=0`), and a later read with real data auto-restores it to `active`. Download 404s are **not** treated as deletion.
- `download/` = stage B download worker. **It never calls the pixiv API** — all URLs come from stage A rows in the DB. `reset_running_jobs` gives crash recovery/resume; `--retry-failed` resets failed jobs.
- `media/` = file layout under `$DATA_DIR/works/{pid}/` (`meta.json`, `preview.jpg`, `original/`, `thumb.webp`, `source.zip`, `animation.mp4`) and ugoira ffmpeg transcode.
- `web/` = FastAPI app. Routers query the DB directly; they do not go through a service layer. Task cancellation is cooperative and only applies between sync pages (via `TaskContext.progress`).
- `sync/factory.py` builds/tears down `Database`, `httpx.AsyncClient`, `PixivClient`, storage, downloader, service/worker.

## Gotchas

- `Settings` hard-requires `PIXIV_REFRESH_TOKEN` and `PIXIV_USER_ID`; almost everything fails to start without them. `AUTH_TOKEN` is optional at startup, but `/api/auth/login` returns 503 when unset.
- `.env` loading differs: the CLI reads `.env` from CWD (`Settings` default), but `create_app` uses `Settings(_env_file=None)` — the web app only sees real environment variables (docker-compose supplies them).
- `DATA_DIR` defaults to `/data`; set it explicitly for local runs. `alembic/env.py` also reads `Settings(_env_file=None)` with no env fallback, so `DATA_DIR` must be set for manual alembic commands. `session.secret` is generated into `DATA_DIR` on first use; cookies invalidate if it changes.
- `tests/conftest.py` autouse fixture deletes all `PIXIV_*`, `DATA_DIR`, `AUTH_TOKEN` env vars for non-integration tests, so they can never hit real credentials. Integration tests opt out via the marker.
- Tests import helpers from `tests/` directly (`from fakes import ...`) because `pythonpath = ["tests"]`; unit tests create their own temp DB and call `create_all()` instead of Alembic.
- Rate limiting (`API_MIN_INTERVAL_MS`, default 800 ms) serializes all API requests globally; image downloads use a separate `IMAGE_CONCURRENCY` path.
- `Illust.state` is `active`/`deleted` (deleted = pixiv stub or placeholder); gallery filters default to hiding deleted, `only_deleted`/`include_deleted` expose them, and `/api/export` deliberately includes every row (no `state` filter).
- Docker: `.dockerignore` intentionally excludes `frontend/dist` (the image's frontend stage builds into `web/static`; only `frontend/node_modules` is needed off). `docker-entrypoint.sh` runs as root, fixes `$DATA_DIR` ownership, then `exec gosu appuser "$@"`; keep it LF-only (`.gitattributes` enforces this) and remember a root bind-mount hides the image's `/data` chown.
- Frontend UI copy is Chinese (`zh-CN`); keep labels in Chinese. Tailwind 4 is CSS-first (tokens in `src/index.css` `@theme`, no `tailwind.config.js`). API calls go through `apiFetch` in `src/api/client.ts` (relative paths, session cookie); a frontend `npm run dev` server does not update the committed build.
