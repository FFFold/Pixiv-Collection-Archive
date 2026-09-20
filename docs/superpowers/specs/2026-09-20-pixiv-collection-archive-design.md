# Pixiv 收藏归档（Pixiv Collection Archive）设计文档

日期：2026-09-20
状态：已与用户逐节确认

## 1. 背景与目标

在空仓库 `Pixiv-Collection-Archive` 中创建一个用于**同步与备份个人 pixiv 图片收藏**的自托管服务。参考项目 `D:\Projects\Pixiv-Archive` 具备收藏备份能力，但结构混乱、且无法保持收藏顺序。本项目从零构建，核心目标是解决顺序问题并具备良好的工程结构。

### 1.1 核心目标

1. **收藏顺序不被打乱**：本地可见的顺序与 pixiv 收藏夹顺序一致，且可验证。
2. **uv 管理依赖**：`pyproject.toml` + `uv.lock`，可复现安装。
3. **容器化 + GH Actions 云端构建镜像**：多阶段 Dockerfile，推送 GHCR。
4. **现代化 WebUI**：React + TypeScript SPA，功能完整（画廊、搜索、详情、任务、统计、导出）。
5. **良好的项目结构**：分层清晰、模块可独立测试。

### 1.2 备份范围（已确认）

- pixiv 账号的**公开收藏**与**私密收藏**（单账号）。
- 收藏的 **illust 与 manga**（插画/漫画）。
- 收藏中的 **ugoira 动图**（含 zip 原始帧 + mp4 转码）。
- 不包含：关注的画师新作、他人收藏夹订阅、小说收藏、多账号。

### 1.3 明确不做

- 从参考项目 `Pixiv-Archive` 导入旧数据（用户选择从零开始）。
- 本地标签 / 自定义收藏集（未勾选）。
- 未勾选的 UI 模块（作者页作为聚合视图不做独立页面，只作为画廊的跳转与过滤）。

## 2. API 事实（已实测验证，2026-09-20）

使用给定账号（user_id 56269851）与 refresh token 实测：

| 项 | 结论 |
| --- | --- |
| 认证 | `POST https://oauth.secure.pixiv.net/auth/token`，`grant_type=refresh_token` + 公开 client_id/secret 可正常换 access_token；实测响应回传的 refresh_token 与请求相同（不轮换），但实现须在响应返回新值时写回配置 |
| access_token 有效期 | `expires_in=3600` |
| 必要请求头 | `User-Agent: PixivIOSApp/7.13.1 (iOS 14.6; iPhone13,2)`、`App-OS: ios`、`App-OS-Version: 14.6`、`App-Version: 7.13.1`；缺失时 app API 返回 400 |
| 收藏列表端点 | `GET https://app-api.pixiv.net/v1/user/bookmarks/illust?user_id=&restrict=public\|private` |
| 页大小 | 30 条/页 |
| 翻页 | 响应 `next_url`，其查询串含 `max_bookmark_id`，作为下一页请求参数；`illusts` 为空即结束 |
| 顺序 | 返回顺序为收藏时间倒序；**illust id 完全不单调**（同一页 id 大小交错），因此按 PID 排序必然打乱收藏顺序 |
| 单条收藏时间 | app API 列表项**不含** `bookmark_data`；Web AJAX 端点 `/ajax/user/{id}/illusts/bookmarks` 需要网页会话 cookie，仅有 refresh token 会返回 401/400。因此无法获得单条收藏的精确时间戳 |
| 账号数据 | `total_illust_bookmarks_public = 2047`；私密收藏接口正常但当前为 0 条 |
| ugoira 元数据 | `GET /v1/ugoira/metadata?illust_id=` 返回 `ugoira_metadata.zip_urls.medium`（600x600 帧压缩包）与 `frames[]`（每帧 `file` + `delay`）；**`zip_urls.original` 为空**，API 层面拿不到 ugoira 原尺寸 |
| ugoira 静态封面 | 列表项的 `meta_single_page.original_image_url` 为 `..._ugoira0.jpg` |
| 缩略图 URL | 列表项自带 `image_urls.square_medium` / `medium` / `large` |
| 图片域名 | `i.pximg.net`；下载需要 `Referer: https://www.pixiv.net/` |
| 网络 | 本机直连 pixiv 超时（被墙），经 `http://127.0.0.1:7897` 代理正常，故必须支持 `PIXIV_PROXY` |

## 3. 技术选型（已确认）

| 层 | 选型 | 理由 |
| --- | --- | --- |
| 后端 | FastAPI + uvicorn | 异步原生、OpenAPI 自动文档、生态成熟 |
| HTTP 客户端 | 自写 async httpx 客户端 | 精确控制 OAuth、分页游标、限速与重试；pixivpy3 为同步库且异常包装混乱，参考项目为此打了大量补丁 |
| ORM / 迁移 | SQLAlchemy 2.x (async) + Alembic | 类型化模型、可控迁移 |
| 数据库 | SQLite（WAL） | 单容器部署，单用户规模足够 |
| 图片处理 | Pillow（缩略图）、ffmpeg（ugoira 转码） | 标准方案 |
| 前端 | Vite + React + TypeScript + TanStack Query + Tailwind + shadcn/ui | 生态最大，适合虚拟滚动瀑布流 |
| 实时推送 | SSE | 单向进度推送，简单可靠 |
| 依赖管理 | uv（`pyproject.toml` + `uv.lock`） | 用户要求 |
| 容器化 | 多阶段 Dockerfile + docker-compose，GHCR 推送 | 用户要求 |

## 4. 收藏顺序模型（核心设计）

### 4.1 问题本质

pixiv 不提供单条收藏的时间戳（app API），因此顺序只能来自「当前收藏列表快照中的位置」。同时收藏是可变集合：新收藏插到最前、取消收藏造成空洞、历史收藏可能被重新添加。

### 4.2 rank 设计

`bookmark` 表使用整数 `rank` 字段承载顺序（越小越新，即列表越靠前）。

- **全量对账**：按列表位置重建，`rank = position * 1000`（position 为 0 开始的全局序号，覆盖 public 在前、private 在后）。
- **增量插入**：本轮新发现的收藏，按列表顺序依次取 `rank = min(rank) - 1024`（递减），使新收藏排在最前且相互之间保持列表顺序。
- **显示序号**：由查询时的 `ROW_NUMBER() OVER (ORDER BY rank)` 实时计算，取消收藏不回填、不重排，序号自然连续，无空洞。

稀疏分配保证插入永远 O(1)，不需要 `UPDATE` 已有行，避免 2000+ 行的全表重排。

### 4.3 同步策略

**增量同步（默认，高频）**：

1. 从第 1 页起顺序请求收藏列表（public，然后 private）。
2. 记录每个作品的位置序号。
3. 遇到「整页作品都已在本地」停止翻页（稳态下新收藏必在最前几页，通常只请求 1–2 页）。
4. 新出现的作品按 4.2 插入 rank；已存在作品的 rank 不动。
5. 本轮**不**判定取消收藏（避免误判）。
6. 终止条件只有两个：遇到「整页已知」或列表耗尽。**不设人为页数上限**——一次性新增 300+ 收藏的极端情况会被完整同步，代价仅是本次多请求若干页。
7. 每次同步记录实际请求页数，UI 可见；若某次请求页数异常大（如 > 20 页），提示用户考虑执行全量对账。

**全量对账（低频/手动）**：

1. 翻完全部收藏列表（2047 条约 69 页）。
2. 重建所有 rank。
3. 本轮未出现的已有收藏标记 `state = unbookmarked`（保留文件与元数据，默认从画廊隐藏，可切换到「已取消收藏」视图查看；若再次收藏则恢复 `active` 并重新插入 rank）。
4. 报告：新增 N、取消 M、rank 修正 K。

触发方式：WebUI 按钮手动触发；可配置周期间隔或 cron 自动触发（默认关闭）。

### 4.4 边界情况

| 情况 | 处理 |
| --- | --- |
| 取消收藏 | 全量对账检出 → `unbookmarked` 标记，文件与元数据保留 |
| 取消后又重新收藏 | 增量同步发现该 pid 的 bookmark 行状态为 `unbookmarked` → 恢复 `active` 并按新位置插入 rank |
| 同步过程中顺序变化 | 本轮读到的列表快照即为权威；下次增量读到的新收藏插到最前 |
| 收藏量超过预期 | 不设人为页数上限，继续翻页直到遇到「整页已知」或列表耗尽 |
| 作品在 pixiv 被删除 | 详情/下载返回 404 → `illust.state = deleted`，文件保留，UI 标注 |
| 同一作品同时存在于公开与私密 | `bookmark` 唯一键为 pid（一个作品在画廊中只出现一次，避免重复下载）。存 `restrict` 表示当前归属，检测到两个 restrict 时以最新一次同步实际见到的为准并记录警告 |

## 5. 存储布局

```
/data/                              # 单一挂载卷
  archive.db                        # SQLite（WAL）
  works/{pid}/
      meta.json                     # 元数据快照（可读，可离线重建 DB）
      original/000_p0.jpg           # 原图（页序号前缀保证页序）
      original/000_p0.zip           # ugoira 原始帧 zip
      animation.mp4                 # ugoira 转码结果
      thumb.webp                    # 400px 缩略图
  logs/app.log
```

- 文件按 PID 命名，顺序完全由 DB 的 `rank` 承载，可自由重排而不动文件。
- `meta.json` 使数据可逆：即使 DB 丢失，也可从文件重建。

## 6. 数据库模型

- `illust` — 作品元数据：pid PK、title、description、author_id、create_date、page_count、width、height、type(illust/ugoira)、x_restrict、sanity_level、total_view、total_bookmarks、state(active/deleted)、meta_json
- `author` — 作者：id PK、name、account、avatar_url
- `tag` / `illust_tag` — 标签与多对多关联
- `illust_page` — 每页：pid + page_index、original_url、ext、width/height、downloaded
- `bookmark` — pid 唯一：restrict(public/private)、rank BIGINT、state(active/unbookmarked)、first_seen_at、last_seen_at、unbookmarked_at
- `download_job` — 持久化队列：id、pid、kind(image/ugoira_zip/ugoira_mp4/thumb)、status(pending/running/done/failed)、attempts、last_error、page_progress
- `sync_run` — 同步记录：id、kind(incremental/reconcile)、started_at、finished_at、new_count、unbookmarked_count、failed_count、status
- `app_setting` — 键值设置（如 refresh_token 回写、调度配置）

## 7. API 客户端与网络层

### 7.1 认证（`pixiv/auth.py`）

- `POST /auth/token`，`grant_type=refresh_token`，公开 client_id/secret。
- access_token 缓存 3600s，提前 300s 刷新。
- 若响应返回新的 refresh_token（即使实测相同）→ 写回 `app_setting` 与日志提示。
- 认证失败抛 `AuthError`，由编排层中断整批并提示用户检查 token。

### 7.2 限速与重试（`pixiv/ratelimit.py`）

- API 请求全串行，默认最小间隔 800ms + 随机抖动。
- 图片下载并发 4（独立信号量，与 API 限速解耦）。
- 重试：指数退避 + 抖动，仅对 5xx / 429 / 连接错误 / 超时；429 尊重 `Retry-After`。
- 401 → 重新认证一次后重试；403/404 → 不重试，判定 `NotFoundError`。

### 7.3 代理与镜像

- `PIXIV_PROXY`：httpx 原生 proxy，作用于 API 与图片域。
- `PIXIV_IMAGE_MIRROR`（可选）：仅替换 `i.pximg.net` 域名，失败回退官方。

### 7.4 异常树

`PixivError` → `AuthError` / `NetworkError`（可重试）/ `NotFoundError` / `RateLimited`。

### 7.5 封号风险评估

请求特征与 pixiv 官方 iOS app、pixivpy3 完全一致（同一 client_id、UA、端点与参数），间隔更保守（800ms 串行）。风险不高于使用现成库。

## 8. 下载层

### 8.1 普通插画

- 多页：遍历 `meta_pages[].image_urls.original`；单页：`meta_single_page.original_image_url`。
- 每页独立重试 3 次，写 `.part` 后 `os.replace` 原子改名。
- 已存在且大小/图片完整性校验通过则跳过。

### 8.2 ugoira

- 拉取 `/v1/ugoira/metadata` 获取 `zip_urls.medium` 与 `frames[]`。
- 下载 zip → 解压到临时目录校验帧。
- 用 `frames` 的逐帧 `delay` 生成 ffmpeg concat 时间表 → 转码 `mp4 (H.264 + yuv420p, faststart)`。
- 保留 zip 作为原始数据。
- 容器无 ffmpeg 时：保留 zip，mp4 标记 `skipped_no_ffmpeg`，UI 降级为静态首帧 + 提示。
- **已知限制**：api 层无法获取 ugoira 原图，所有第三方备份工具均如此；在文档与 UI 中明确说明。

### 8.3 缩略图

- Pillow 生成 WebP 400px（长边），存 `works/{pid}/thumb.webp`。
- 生成失败时回退为服务原图；列表页 URL 兜底 `square_medium`。

## 9. Web API（FastAPI）

- `POST /api/auth/login` / `POST /api/auth/logout` / `GET /api/auth/me`
- `GET /api/gallery` — 分页、排序（收藏顺序/发布时间/热度）、过滤（restrict、R-18、type、标签、作者、日期范围）、搜索
- `GET /api/illust/{pid}` — 详情（含页列表、tags、author、job 状态）
- `GET /api/illust/{pid}/file/{page}` — 原图，支持 ETag / Range
- `GET /api/illust/{pid}/thumb` — 缩略图
- `GET /api/illust/{pid}/animation` — mp4
- `GET /api/authors` / `GET /api/tags`
- `POST /api/sync` — 触发增量同步；`POST /api/sync/reconcile` — 触发全量对账
- `GET /api/jobs` / `POST /api/jobs/retry` / `GET /api/jobs/stream`（SSE）
- `GET /api/stats`
- `POST /api/export`（后台任务）+ `GET /api/export/{id}/download`
- `GET /api/health`

认证：单用户 token（`AUTH_TOKEN` 环境变量）；登录后签发 HttpOnly cookie session，签名密钥持久化在数据卷，重启不失效。

## 10. 前端（React + TS）

- 布局：左侧常驻导航（可折叠为图标）+ 顶部工具栏 + 主内容区（用户选定方案 A）。
- 页面：画廊、已取消收藏、同步任务、统计、设置。
- 画廊：瀑布流 + 虚拟滚动，默认收藏顺序，卡片显示全局序号 `#1234`；缩略图 `IntersectionObserver` 懒加载。
- 详情：多页切换、原图缩放、ugoira 播放（`<video>`）、作者/标签跳转、pixiv 原始链接、文件信息。
- 同步面板：SSE 实时进度（阶段/已完成/总数/速率/当前作品）、历史记录、失败重试、日志流。
- 统计：总数/总大小/作者 Top/时间线/存储占用。
- 导出：按当前筛选导出 zip（可仅元数据），后台任务 + SSE 进度。
- 响应式：移动端可用（侧栏抽屉化）。

## 11. 配置（环境变量）

| 变量 | 说明 | 默认 |
| --- | --- | --- |
| `PIXIV_REFRESH_TOKEN` | 必填 | — |
| `PIXIV_USER_ID` | 必填 | — |
| `PIXIV_PROXY` | 代理（API 与图片共用） | 空 |
| `PIXIV_IMAGE_MIRROR` | 图片镜像域名 | 空 |
| `AUTH_TOKEN` | WebUI 登录令牌 | 随机生成并打印 |
| `DATA_DIR` | 数据目录 | `/data` |
| `SYNC_INTERVAL` | 增量同步间隔 | `6h` |
| `RECONCILE_CRON` | 全量对账 cron（空=关闭） | 空 |
| `API_MIN_INTERVAL_MS` | API 串行最小间隔 | `800` |
| `IMAGE_CONCURRENCY` | 图片并发 | `4` |
| `TZ` | 时区 | `Asia/Shanghai` |

## 12. 容器化与 CI

### 12.1 Dockerfile（多阶段）

1. `node:22-alpine`：`npm ci` + `vite build` → `dist/`
2. `python:3.12-slim`：`uv sync --frozen --no-dev` 到 `/app/.venv`，复制 `dist/` 与 ffmpeg
3. runtime：非 root 用户，仅拷贝 venv + 应用 + static

- `HEALTHCHECK` → `/api/health`
- 卷：`/data`
- 端口：8000

### 12.2 docker-compose.yml

单服务，映射 8000，挂载 `./data:/data`，注入环境变量，`restart: unless-stopped`。

### 12.3 GitHub Actions

- `ci.yml`：push/PR → `ruff check`、`ruff format --check`、`mypy`、`pytest`（单元 + mock）、`tsc --noEmit`、`eslint`、`vitest`
- `docker.yml`：tag `v*` 或手动 → buildx 多架构（amd64/arm64）推送 `ghcr.io/<owner>/pixiv-collection-archive:latest` 与 `:vX.Y.Z`

### 12.4 测试策略

- 单元测试：`respx` mock httpx，覆盖翻页游标解析、rank 插入/重建、取消收藏标记、ugoira delay→时间表、原子写。
- 集成测试（手动标记 `@pytest.mark.integration`）：真实 token 拉取前几页校验顺序单调性与分页正确性。

## 13. 项目结构

```
pixiv-collection-archive/
├─ pyproject.toml
├─ uv.lock
├─ Dockerfile
├─ docker-compose.yml
├─ .github/workflows/{ci.yml,docker.yml}
├─ src/pixiv_archive/
│    ├─ config.py
│    ├─ db/{engine.py,models.py,repo/,migrations/}
│    ├─ pixiv/{auth.py,client.py,models.py,ratelimit.py,errors.py}
│    ├─ media/{downloader.py,ugoira.py,thumbnails.py,storage.py}
│    ├─ sync/{orchestrator.py,bookmarks.py,reconcile.py,scheduler.py}
│    ├─ web/{app.py,deps.py,auth.py,sse.py,routers/}
│    └─ __main__.py
├─ frontend/
├─ tests/
└─ docs/
```

分层规则：`pixiv/` 只懂 API；`media/` 只懂文件与转码；`sync/` 编排；`web/` 只做 HTTP。每层可独立测试。

## 14. 里程碑

1. **M1 骨架** — uv 项目、配置、DB + 迁移、Dockerfile、CI
2. **M2 Pixiv 层** — auth + client + 限速重试（含真实 API 集成测试）
3. **M3 同步核心** — 增量同步 + rank 模型 + 全量对账
4. **M4 下载层** — 图片 / ugoira / 缩略图 + 持久化任务队列
5. **M5 API** — FastAPI 路由 + SSE + 认证
6. **M6 前端** — 画廊 / 详情 / 任务 / 统计 / 导出
7. **M7 发布** — compose、文档、GHCR 镜像、README

## 15. 开放风险

| 风险 | 缓解 |
| --- | --- |
| refresh_token 策略变更或被吊销 | 认证失败明确提示；实现 token 回写；文档说明如何重新获取 |
| pixiv 端点变更 | 客户端薄封装集中于 `pixiv/client.py`；集成测试可快速发现 |
| 增量同步在极端情况（一次新增数百条）下新收藏的组内相对顺序 | 增量按列表顺序递减分配，组内顺序正确；与历史收藏的相对位置可能偏移，由全量对账修正。UI 显示「上次对账时间」 |
| ffmpeg 转码耗时/CPU 占用 | 转码为独立低优先级任务，可配置开关与并发 |
| SQLite 并发写 | 单写者模型 + WAL；下载任务通过队列串行写库 |
