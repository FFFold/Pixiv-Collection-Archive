# Pixiv Collection Archive

自托管的 pixiv 收藏同步与备份服务。**核心特性：完整保留收藏顺序。**

- 收藏顺序模型基于稀疏 rank + 位置快照（pixiv API 不提供单条收藏时间戳）
- 元数据同步与图片下载解耦：先快速建立索引，再按范围分批下载原图
- ugoira 动图保留原始 zip 并转码为 mp4
- React WebUI：画廊 / 详情 / 任务 / 统计 / 导出
- 单容器 + SQLite，GHCR 镜像

<!-- 截图占位：把图片放到 docs/screenshots/ 后取消注释对应行
## 界面预览

| 画廊 | 作品详情 |
| --- | --- |
| ![画廊](docs/screenshots/gallery.png) | ![详情](docs/screenshots/detail.png) |

| 任务与实时进度 | 统计 |
| --- | --- |
| ![任务](docs/screenshots/tasks.png) | ![统计](docs/screenshots/stats.png) |
-->

## 状态

- [x] 项目基础 + pixiv API 层
- [x] 阶段 A：元数据同步（增量 / 全量 + rank 顺序 + 预览图）
- [x] 阶段 B：图片下载（持久化队列 + 范围批次 + 原图 / ugoira / 缩略图）
- [x] Web API（认证 / 画廊 / 详情与文件 / 任务与 SSE / 统计 / 导出）
- [x] WebUI（React 画廊 / 详情 / 任务 / 统计 / 导出）
- [x] 发布（compose 文档、GHCR 多架构镜像）

## 快速开始（开发）

```bash
uv sync
cp .env.example .env   # 填写 PIXIV_REFRESH_TOKEN / PIXIV_USER_ID
uv run pytest
```

### 阶段 A：同步收藏元数据

```bash
# 增量（默认；稳定态只请求前 1-2 页）
uv run python -m pixiv_archive sync --mode incremental

# 全量（首次同步、或需要重建顺序 / 检出取消收藏时）
uv run python -m pixiv_archive sync --mode full

# 调试：只翻 N 页、跳过预览图
uv run python -m pixiv_archive sync --max-pages 2 --no-previews
```

数据落盘结构：

```
$DATA_DIR/works/{pid}/
    meta.json     # 作品元数据快照（pixiv 原始字段，可离线重建 DB）
    preview.jpg   # 收藏列表预览图（约 16KB）
```

收藏顺序由数据库 `bookmark.rank` 承载（稀疏分配，越小越新），可通过 `alembic upgrade head` 之外的独立迁移演进。

真实 API 集成测试（需要代理与凭据）：

```bash
# PowerShell
$env:PIXIV_PROXY="http://127.0.0.1:7897"
uv run pytest tests/test_integration_live.py tests/test_integration_sync.py tests/test_integration_download.py -m integration -v -s
```

### 阶段 B：下载图片

```bash
# 下载全部尚未下载的作品（分批、可中断续传）
uv run python -m pixiv_archive download

# 只下载 rank 区间（前 20 个收藏）
uv run python -m pixiv_archive download --scope rank-range --start 0 --limit 20

# 指定作者 / 指定作品 / 只看 R-18
uv run python -m pixiv_archive download --scope author --author 12345
uv run python -m pixiv_archive download --scope selected --pids 111,222,333
uv run python -m pixiv_archive download --scope filter --x-restrict 1

# 重试此前失败的项；跳过缩略图
uv run python -m pixiv_archive download --retry-failed
uv run python -m pixiv_archive download --no-thumbs
```

下载落盘：

```
$DATA_DIR/works/{pid}/
    original/000_p0.jpg   # 原图（页序号前缀保证页序）
    source.zip            # ugoira 原始帧
    animation.mp4         # ugoira 转码（需 ffmpeg；缺失时保留 zip 并标记 skipped）
    thumb.webp            # 本地 400px 缩略图
```

所有下载均使用阶段 A 已落库的原图 URL，**不调用 pixiv API**。下载作业持久化在 `download_job` 表中，中断后重跑会自动续传（含服务崩溃遗留的 `running` 作业）。

## Docker

镜像由 GitHub Actions 构建并推送至 GHCR，支持 `linux/amd64` 与 `linux/arm64`：

```bash
# 1. 准备配置
cp .env.example .env
#    至少填写：PIXIV_REFRESH_TOKEN / PIXIV_USER_ID / AUTH_TOKEN
#    需要代理时填写 PIXIV_PROXY（容器内可用 host.docker.internal:7897）

# 2. 启动（使用 GHCR 预构建镜像）
docker compose up -d

# 3. 打开 http://<主机>:8000，用 AUTH_TOKEN 登录
```

本地构建镜像（不拉 GHCR）：

```bash
docker compose up -d --build
```

镜像内已包含 ffmpeg（ugoira 转码）与构建好的前端。数据全部保存在 `./data`
（SQLite + 原图 + 缩略图 + 转码结果 + 导出包），升级镜像不会影响数据。

容器以 root 启动，先把 `DATA_DIR` 的属主修正给 `appuser`（uid 1000）再降权运行，
因此宿主机上 `./data` 里的文件属主是你自己，且删除 `./data` 后重新 `up -d` 也能直接启动。
若要固定新文件属主，让容器用户的 uid 与宿主机用户一致即可（本镜像固定 uid 1000）。

常用运维命令：

```bash
docker compose logs -f app          # 查看日志
docker compose restart app          # 重启
docker compose pull && docker compose up -d   # 升级到最新镜像
```

发布流程：推送 `v*` tag 后 `docker.yml` 会自动构建多架构镜像（tag `vX.Y.Z`、
`major.minor`、`latest`）并执行冒烟测试（健康检查 / 前端外壳 / 登录 / 画廊）。

## 配置

见 `.env.example`。关键项：

| 变量 | 说明 | 默认 |
| --- | --- | --- |
| `PIXIV_REFRESH_TOKEN` | pixiv refresh token（必填） | — |
| `PIXIV_USER_ID` | pixiv 用户 ID（必填） | — |
| `PIXIV_PROXY` | 代理（API 与图片共用） | 空 |
| `AUTH_TOKEN` | WebUI 登录令牌 | 随机生成并打印 |
| `DATA_DIR` | 数据目录 | `/data` |
| `SYNC_INTERVAL` | 元数据增量同步间隔 | `6h` |
| `API_MIN_INTERVAL_MS` | API 串行最小间隔（防风控） | `800` |
| `IMAGE_CONCURRENCY` | 图片下载并发 | `4` |


### 启动 Web 服务

```powershell
$env:AUTH_TOKEN = "your-token"   # 登录令牌，未设置时无法登录
$env:PIXIV_PROXY = "http://127.0.0.1:7897"   # 需要代理时
uv run python -m pixiv_archive
# 打开 http://localhost:8000，输入令牌登录
```

前端开发模式（热更新，`/api` 自动代理到 8000）：

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
```

前端生产构建（产物输出到 `src/pixiv_archive/web/static/`，由 FastAPI 托管；Docker 构建会自动执行）：

```bash
cd frontend
npm run build
```

主要接口：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/auth/login` | 用 `AUTH_TOKEN` 换取 session cookie |
| GET | `/api/gallery` | 画廊（排序 / 过滤 / 搜索 / 分页，含显示序号） |
| GET | `/api/illust/{pid}` | 作品详情（含页状态、标签、动图信息） |
| GET | `/api/illust/{pid}/file/{page}` | 原图（支持 Range 与 ETag） |
| GET | `/api/illust/{pid}/thumb` | 缩略图（本地 WebP 优先，回退预览图/占位） |
| GET | `/api/illust/{pid}/animation` | ugoira 转码后的 mp4 |
| POST | `/api/sync` | 触发阶段 A（`mode=incremental\|full`） |
| POST | `/api/downloads` | 触发阶段 B（scope: all_missing/author/selected/rank-range/filter） |
| GET | `/api/tasks` | 任务列表与状态（可取消） |
| GET | `/api/events` | SSE 实时进度事件流 |
| GET | `/api/stats` | 统计（数量 / 页状态 / 体积） |
| POST | `/api/export` | 导出 zip（JSON 元数据 / 原图） |

定时同步由服务内置调度器负责（`SYNC_INTERVAL`，可选 `SYNC_FULL_CRON`）。
## 文档

- 设计文档：`docs/superpowers/specs/2026-09-20-pixiv-collection-archive-design.md`
- 实施计划：`docs/superpowers/plans/`

