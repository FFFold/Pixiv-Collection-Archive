# Pixiv Collection Archive

自托管的 pixiv 个人收藏同步与备份服务。

[![CI](https://img.shields.io/github/actions/workflow/status/FFFold/Pixiv-Collection-Archive/ci.yml?label=CI&logo=githubactions&logoColor=white)](https://github.com/FFFold/Pixiv-Collection-Archive/actions/workflows/ci.yml)
[![Docker](https://img.shields.io/github/actions/workflow/status/FFFold/Pixiv-Collection-Archive/docker.yml?label=docker&logo=docker&logoColor=white)](https://github.com/FFFold/Pixiv-Collection-Archive/actions/workflows/docker.yml)
[![Version](https://img.shields.io/github/v/tag/FFFold/Pixiv-Collection-Archive?label=version&sort=semver)](https://github.com/FFFold/Pixiv-Collection-Archive/releases)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=white)
[![License](https://img.shields.io/badge/License-AGPL--3.0-blue)](LICENSE)

> pixiv 的收藏 API 不返回单条收藏的时间戳。本项目用**稀疏 rank + 位置快照**重建顺序，并把"取消收藏""作品失效"作为一等状态来跟踪。

<!-- 截图占位：把图片放到 docs/screenshots/ 后取消注释
## 界面预览

| 画廊 | 作品详情 |
| :---: | :---: |
| ![画廊](docs/screenshots/gallery.png) | ![详情](docs/screenshots/detail.png) |

| 任务与实时进度 | 统计 |
| :---: | :---: |
| ![任务](docs/screenshots/tasks.png) | ![统计](docs/screenshots/stats.png) |
-->

## ✨ 特性

| 能力 | 说明 |
| --- | --- |
| **收藏顺序** | 稀疏 `Bookmark.rank`（越小越新）+ 位置快照；增量把新收藏插到最前，全量重建 rank 并标记消失的 pid 为已取消收藏 |
| **失效检测** | 识别 pixiv 的删除/私有占位图（`limit_*` 或 `user.id == 0`）→ `state=deleted`，**不覆盖**已有元数据与文件；作品恢复后自动还原为 `active` |
| **两阶段解耦** | 阶段 A 快速建索引（元数据 + 预览图）→ 阶段 B 按范围分批下载原图；下载阶段**完全不调用 pixiv API** |
| **断点续传** | 作业持久化在 `download_job` 表，中断或进程崩溃后重跑自动续传（含遗留的 `running` 作业） |
| **ugoira 动图** | 保留原始帧 `source.zip`，并用 ffmpeg 转码为 `animation.mp4`（无 ffmpeg 时保留 zip 并标记 skipped） |
| **画廊检索** | 多标签 AND、多作者、页数/收藏数/浏览数区间、R-18、下载状态、已取消、已失效；支持多种排序与展示序号 |
| **导出** | 打包 JSON 元数据 / 原图为 zip，可按选中、按筛选、按作者分组 |
| **运维** | 存储统计重建、DB 与 `works/` 目录对账修复、数据库体检；单容器 + SQLite，内置定时增量同步 |

## 📦 快速开始（Docker）

镜像由 GitHub Actions 构建并推送至 GHCR，支持 `linux/amd64` 与 `linux/arm64`。

```bash
# 1. 准备配置（至少填写 PIXIV_REFRESH_TOKEN / PIXIV_USER_ID / AUTH_TOKEN）
cp .env.example .env

# 2. 启动
docker compose up -d

# 3. 打开 http://<主机>:8000，用 AUTH_TOKEN 登录
```

需要代理时填写 `PIXIV_PROXY`（容器内可用 `host.docker.internal:7897`）。
本地构建镜像（不拉 GHCR）用 `docker compose up -d --build`。

镜像内已包含 ffmpeg 与构建好的前端，数据全部保存在 `./data`（SQLite + 原图 + 缩略图 + 转码结果 + 导出包），
升级镜像不影响数据。容器以 root 启动，先把 `DATA_DIR` 属主修正给 `appuser`（uid 1000）再降权运行，
因此宿主机 `./data` 里的文件属主是你自己；若需固定新文件属主，让容器 uid 与宿主机用户一致即可。

```bash
docker compose logs -f app                     # 查看日志
docker compose pull && docker compose up -d    # 升级到最新镜像
```

> 发布流程：推送 `v*` tag 后 `docker.yml` 自动构建多架构镜像（`vX.Y.Z`、`major.minor`、`latest`）并执行冒烟测试
> （健康检查 / 前端外壳 / 登录 / 画廊）。

## ⚙️ 配置

完整列表见 `.env.example`，关键项：

| 变量 | 说明 | 默认 |
| --- | --- | --- |
| `PIXIV_REFRESH_TOKEN` | pixiv refresh token（**必填**） | — |
| `PIXIV_USER_ID` | pixiv 用户 ID（**必填**） | — |
| `AUTH_TOKEN` | WebUI 登录令牌 | 未设置时 `/api/auth/login` 返回 503 |
| `PIXIV_PROXY` | 代理（API 与图片共用） | 空 |
| `PIXIV_IMAGE_MIRROR` | 图片镜像站（改写 pximg 主机，失败回退官方地址） | 空 |
| `DATA_DIR` | 数据目录 | `/data` |
| `SYNC_INTERVAL` | 增量同步间隔，支持 `30m` / `6h` / `1d` | `6h` |
| `SYNC_FULL_CRON` | 额外的全量同步 crontab（如 `0 4 * * 0`） | 空 |
| `API_MIN_INTERVAL_MS` | API 串行最小间隔（防风控） | `800` |
| `IMAGE_CONCURRENCY` | 图片下载并发 | `4` |
| `DOWNLOAD_PREVIEWS` | 同步时抓取预览图 | `true` |
| `FFMPEG_BIN` | ffmpeg 可执行文件 | `ffmpeg` |

`.env` 的加载方式并不一致：CLI 从 CWD 读取 `.env`，而 Web 应用使用 `Settings(_env_file=None)`，
**只认真实环境变量**（docker-compose 通过 `env_file` 注入）。

## 🧭 工作方式

**阶段 A · 元数据同步**（唯一会调用 pixiv API 的阶段）

- 增量模式在稳定态下通常只请求前 1~2 页，新收藏插入到已有 rank 之前；
- 全量模式重建 rank、标记被取消收藏的 pid，并逐个检查作品是否为占位图；
- 每个作品落一份 `meta.json` 原始快照，即便 DB 丢失也可离线重建。

**阶段 B · 图片下载** 只消费阶段 A 已落库的 URL，按范围解析出具体作业后并发下载，可随时中断续传。

```
$DATA_DIR/works/{pid}/
    meta.json         # 作品元数据快照（pixiv 原始字段，可离线重建 DB）
    preview.jpg       # 收藏列表预览图（约 16KB）
    original/000_p0.jpg   # 原图，页序号前缀保证页序
    source.zip        # ugoira 原始帧
    animation.mp4     # ugoira 转码结果
    thumb.webp        # 本地 400px 缩略图
```

## 🖥️ 本地开发

后端（Python 3.12 + uv，src layout）：

```powershell
uv sync
uv run pytest -q                                # 默认排除集成测试
uv run ruff check src tests && uv run mypy      # lint + 严格类型检查
$env:DATA_DIR = ".\data"                        # 本地运行务必显式设置
uv run python -m pixiv_archive                  # 启动 Web 服务 :8000
```

前端（Node 22，在 `frontend/` 下）：

```bash
npm ci
npm run dev       # http://localhost:5173，/api 自动代理到 8000
npm run build     # 产物输出到 src/pixiv_archive/web/static/（该产物已提交到 git）
```

> 修改前端源码后必须重新 `npm run build`，否则 Python 服务仍托管旧产物；请勿删除 `web/static/`。

集成测试会真实访问 pixiv API（需要凭据、代理与已有归档）：

```powershell
$env:PIXIV_PROXY = "http://127.0.0.1:7897"
uv run pytest tests/test_integration_live.py -m integration -v -s
```

## ⌨️ CLI

WebUI 之外，同一套能力也可通过命令行使用（`_ensure_schema` 会在启动时自动执行 Alembic 迁移）：

```bash
# 阶段 A：同步（默认增量；首次同步或需要重建顺序时用 full）
uv run python -m pixiv_archive sync --mode incremental
uv run python -m pixiv_archive sync --mode full

# 阶段 B：下载
uv run python -m pixiv_archive download                                  # 全部未下载
uv run python -m pixiv_archive download --scope rank-range --start 0 --limit 20
uv run python -m pixiv_archive download --scope author --author 12345
uv run python -m pixiv_archive download --scope selected --pids 111,222,333
uv run python -m pixiv_archive download --scope filter --x-restrict 1
uv run python -m pixiv_archive download --retry-failed --no-thumbs

# 维护：DB 与 works/ 对账
uv run python -m pixiv_archive maintain rebuild-stats
uv run python -m pixiv_archive maintain db-check
uv run python -m pixiv_archive maintain repair-download-state --yes
```

> 升级到带体积统计列的版本后，旧的 `/api/stats` 体积显示为 0 属正常现象，
> 执行一次 `maintain rebuild-stats`（或 WebUI「设置 → 维护 → 重建存储统计」）即可回填；
> `stats_stale` 字段指示是否尚未回填。

## 🔌 API

所有 `/api/*`（`/api/health` 与 `/api/auth/login` 除外）都需要 session cookie。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/auth/login` · `/api/auth/logout` | 用 `AUTH_TOKEN` 换取 / 清除 session cookie |
| GET | `/api/auth/me` | 当前登录状态 |
| GET | `/api/gallery` | 画廊分页（筛选 / 排序 / 展示序号；`tag` 与 `author_id` 可重复传参实现 AND 与多作者） |
| GET | `/api/illust/{pid}` | 作品详情（页状态、标签、动图信息） |
| GET | `/api/illust/{pid}/file/{page_index}` | 原图（支持 Range 与 ETag） |
| GET | `/api/illust/{pid}/thumb` | 缩略图（本地 WebP 优先，回退预览图 / 占位） |
| GET | `/api/illust/{pid}/animation` · `/api/illust/{pid}/ugoira.zip` | ugoira 转码 mp4 / 原始帧 zip |
| POST | `/api/sync` | 触发阶段 A（`mode=incremental\|full`） |
| POST | `/api/downloads` | 触发阶段 B（scope：`all_missing` / `author` / `selected` / `rank-range` / `filter`） |
| GET | `/api/tasks` · `/api/tasks/{task_id}` | 任务列表与状态 |
| POST | `/api/tasks/{task_id}/cancel` | 取消任务（协作式，在同步分页之间生效） |
| GET | `/api/events` | SSE 实时进度事件流 |
| GET | `/api/stats` | 数量 / 页状态 / 体积分布 |
| GET | `/api/authors` · `/api/tags` | 作者 / 标签候选（含作品数，供筛选器使用） |
| POST | `/api/export` | 导出 zip（元数据 / 原图；按 pids、按筛选或按作者分组） |
| GET | `/api/export/{task_id}/download` | 下载导出包 |
| POST | `/api/maintenance/rebuild-stats` | 重建存储统计（后台任务） |
| GET | `/api/maintenance/repair-download-state/preview` | 预览下载状态修复（只读） |
| POST | `/api/maintenance/repair-download-state` | 执行下载状态修复（后台任务） |
| POST | `/api/maintenance/db-check` | 数据库体检（只读报告） |
| GET | `/api/health` | 健康检查（供容器探针使用） |

## 🏗️ 架构

```
src/pixiv_archive/
├── pixiv/        原始 API 客户端（认证 / 限流 / 重试）——仅阶段 A 使用
├── sync/         阶段 A：增量与全量同步、rank 演进、失效检测、调度器
├── download/     阶段 B：持久化作业队列、范围解析、并发下载 worker
├── media/        文件布局、缩略图生成、ugoira ffmpeg 转码
├── db/           SQLAlchemy 模型与仓库、共享筛选核心 query.py、Alembic 迁移
├── web/          FastAPI 应用：路由、SSE 事件流、任务管理、SPA 托管
└── maintenance/  DB 与 works/ 目录对账（体积统计 / 下载状态 / 体检）
frontend/         React 19 + Tailwind 4，构建产物提交到 web/static/
```

几处刻意的设计：

- **顺序即数据**：`Bookmark.rank` 稀疏分配，全量走查按列表位置重排；页面级 API 不提供收藏时间，因此顺序由本项目自行维护。
- **筛选只有一份实现**：`db/query.py` 的 `IllustFilters` + `build_illust_query` / `build_filtered_pids` 被画廊、下载范围与导出共用，`web/gallery_query.py` 仅追加排序与展示序号窗口。
- **下载不碰 API**：阶段 B 的所有 URL 都来自阶段 A 的行，因此可以离线重跑、批量重试。
- **Web 路由直查 DB**，不引入 service 层；任务取消是协作式的，只在同步分页之间生效。

## 📚 文档与许可

- 设计文档：`docs/superpowers/specs/2026-09-20-pixiv-collection-archive-design.md`
- 实施计划：`docs/superpowers/plans/`
- 开发约定与环境细节：`AGENTS.md`
- 许可证：[AGPL-3.0](LICENSE)

本项目仅供个人备份自己的 pixiv 收藏使用，请遵守 pixiv 的服务条款并合理控制请求频率。
