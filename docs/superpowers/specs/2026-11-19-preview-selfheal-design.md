# 封面/动图元数据自愈设计文档

日期：2026-11-19
状态：设计已确认，实施计划见 `docs/superpowers/plans/2026-11-19-preview-selfheal.md`
关联：`docs/superpowers/specs/2026-09-20-pixiv-collection-archive-design.md`（基线设计）

## 1. 背景与根因

现象：定时增量同步拉到新收藏后，Web 画廊偶尔出现 `#pid` 占位符；重跑一次全量同步即可恢复。

排查结论（已用 fake client/downloader 复现）：

1. 封面来自阶段 A 下载的 `$DATA_DIR/works/{pid}/preview.jpg`；`thumb.webp` 只在阶段 B 生成。`/api/illust/{pid}/thumb` 在两者都不存在时返回占位 SVG（`web/files.py:63-82`）。
2. 自动调度只跑 `run_incremental`（`SYNC_INTERVAL`，默认 6h），`SYNC_FULL_CRON` 默认不配置。
3. `run_incremental` 只在「新发现」或「deleted → active」时把作品加进 `preview_targets`；已知作品直接跳过（`sync/orchestrator.py:112-118`、`144-164`、`178-193`）。
4. `_fetch_previews` 是**一次性 best-effort**：失败只累加 `previews_failed`，不记录 pid、不落盘、不重试（`orchestrator.py:352-368`）。网络抖动超过重试窗口（约 1.8s）即永久失败。
5. 全量同步会重新把每个列出的作品加入 `preview_targets`（`orchestrator.py:287`），所以只有全量能自愈。

动图元数据有同样缺陷：`ugoira_targets` 只覆盖新增作品（`orchestrator.py:370-392`）；缺少 `UgoiraMeta` 行时阶段 B 根本不会生成 zip/mp4 任务（`download/scope.py:175-177`）。

## 2. 目标与非目标

### 目标

- 增量同步每轮自动补拉「未就绪」的封面与缺失的动图元数据，失败可重试且可观测。
- 升级后的第一次增量同步即可修复历史遗留的占位符，不需要重跑全量。
- 提供手动修复入口（Web 任务 + CLI），可重置失败计数并立即补拉。
- 统计页与任务详情能看到失败/待补数量。

### 明确不做

- 不改阶段 B 下载流程（原图、缩略图、ugoira 转码）。
- 不把全量同步作为常规修复手段，也不改 rank/取消收藏逻辑。
- 不做历史预览文件的解码体检（回填只按文件存在性判定）；损坏文件留给后续维护需求。
- 不加多进程/多实例锁（当前部署为单容器单进程）。

## 3. 已确认决策

| 主题 | 决策 |
| --- | --- |
| 状态载体 | 列式状态，与 `IllustPage.download_state/attempts/last_error` 现有模式一致 |
| 封面状态列 | `illust.preview_state`（`pending`/`ready`/`failed`）、`preview_attempts`、`preview_error` |
| 动图状态列 | `ugoira_meta.meta_attempts`、`meta_error`；`zip_url` 非空且 `frame_count > 0` 视为就绪 |
| 重试节奏 | 跟随增量同步，每轮最多一次；`preview_attempts` 达到 5 后转 `failed`，停止自动重试 |
| 手动修复 | 重置 `failed → pending`、`attempts = 0`，并核对 `ready` 作品的文件是否还在（丢失的重新入队），随后立即执行一轮补拉 |
| 校验 | 预览字节必须通过 `is_valid_image()` 才落盘并置 `ready` |
| 可见性 | `/api/stats` + 同步任务详情 + CLI 汇总 |

## 4. 架构与数据

### 4.1 迁移 0005

`src/pixiv_archive/db/migrations/versions/0005_preview_state.py`

```text
illust:
  preview_state     VARCHAR(16) NOT NULL DEFAULT 'pending'
  preview_attempts  INTEGER     NOT NULL DEFAULT 0
  preview_error     TEXT        NULL
ugoira_meta:
  meta_attempts     INTEGER     NOT NULL DEFAULT 0
  meta_error        TEXT        NULL
```

- 不回填：默认 `pending` 的语义是「下次同步先检查文件」。第一次增量同步会对所有作品做一次 `preview.jpg` 存在性检查（只 stat，不发请求），存在的立即标 `ready`，缺失的才补拉。
- `downgrade` 对应删除这些列。

### 4.2 状态机（封面）

```text
            upsert 新作品
                 │
                 ▼
             pending ──文件已存在─────────────► ready
                 │
                 ├──下载成功且 is_valid_image ─► ready
                 │
                 ├──失败且 attempts < 5 ───────► pending（attempts+1, error 记录）
                 │
                 └──失败且 attempts >= 5 ──────► failed
                                                   │
                              手动修复 / 维护任务 ──┘
                                      │
                                      ▼
                                   pending
```

`state='deleted'` 的作品不参与补拉，也不计入统计分母。

### 4.3 补拉队列

在 `MetadataSyncService._finalize()` 中，用统一的资产补拉替换现有 `preview_targets` 收集：

1. 查询 `illust` 中满足 `state='active' and preview_state != 'ready' and preview_attempts < 5` 的 `(pid, meta_json, preview_attempts)`。
2. 逐个处理：
   - `preview.jpg` 已存在 → `ready`（修复进程崩溃、迁移回填）。
   - 否则从 `meta_json["image_urls"]` 取 `square_medium`，退化到 `medium`；没有 URL 记为失败。
   - `ImageDownloader.fetch_bytes(url)` → `is_valid_image(data)` → `atomic_write_bytes` → `ready`，并清空 `preview_error`。
   - 失败（None / 非法图片 / 写盘 OSError）→ `attempts+1` 并写 `preview_error`；达到上限转 `failed`。
3. 每 50 个目标提交一次，单个目标异常不中断整批（`logger.warning` 带 pid）。
4. 新作品在 `upsert_illust` 插入时显式 `preview_state='pending'`，冲突更新时不动状态列（沿用现有 set_ 机制），因此同一轮就能被队列抓到。
5. `download_previews=False`（CLI `--no-previews`）时整段跳过。

`SyncResult` 增加 `previews_pending`（本轮结束时 active 且非 ready 的数量），`previews_fetched`/`previews_failed` 语义不变（本轮成功/失败次数，含补拉）。

### 4.4 动图元数据队列

1. 查询 `state='active' and type='ugoira'` 且（无 `ugoira_meta` 行，或 `zip_url=''`，或 `frame_count=0`）且 `coalesce(meta_attempts,0) < 5` 的作品。
2. 成功：`upsert_ugoira_meta()` 写入 zip/frames，并把 `meta_attempts=0`、`meta_error=NULL`。
3. 失败：`record_ugoira_meta_failure(pid, error)` 创建/更新一行（保留已有 zip_url），`meta_attempts+1`，达到上限后不再入队。
4. `download/scope.py` 的 `ugoira_pids` 只选择 `zip_url != '' and frame_count > 0` 的行，避免为失败占位行生成注定失败的 zip/mp4 任务。

### 4.5 下载器可观测性

- `ImageDownloader.on_error` 目前在 `media/downloader.py` 定义但从未调用（死代码）。改为在候选 URL 全部失败后调用一次，参数 `(url, reason)`；默认回调直接 `logger.warning`，失败因此进入容器日志（factory 无需额外传参）。

## 5. 对外接口

### 5.1 统计

`StatsOut` 增加：

- `previews_ready`：`preview_state='ready'` 的 active 作品数
- `previews_missing`：active 且 `preview_state != 'ready'` 的作品数
- `ugoira_meta_missing`：active 动图中元数据未就绪的数量

`/api/stats` 用 SQL 聚合计算，不扫盘、不读文件。

### 5.2 维护

- `POST /api/maintenance/repair-previews`：任务形式（`TaskManager`/SSE），返回 `TaskOut`。
  - 步骤：`repair_assets(reset_failed=True)` —— 先把 `failed → pending`、`attempts=0`，再用 `get_ready_preview_pids()` + `has_preview()` 核对「状态 ready 但文件丢失」的作品并重置为 `pending`；随后执行一轮补拉；返回 `{reset, previews_fetched, previews_failed, previews_pending, ugoira_fetched, ugoira_failed}`。
  - 与 sync 任务互斥：sync 正在跑时返回 409（沿用 `TaskManager.start` 的 RuntimeError 处理）。
- CLI：`uv run python -m pixiv_archive maintain repair-previews [-y]`，行为同上并打印汇总。
- 设置页新增「补拉缺失封面」按钮，沿用现有维护按钮的任务/进度展示。

### 5.3 同步任务详情

`web/routers/tasks.py` 的 sync detail 增加 `previews_pending`；前端 `TaskPanel` 同步行展示为
`新增 X · 页 Y · 预览 Z（失败 F，待补 P）`。CLI `_report_sync` 同步补充。

## 6. 涉及文件

| 文件 | 变更 |
| --- | --- |
| `db/migrations/versions/0005_preview_state.py` | 新增迁移 |
| `db/models.py` | Illust / UgoiraMeta 新列 |
| `db/repo/illusts.py` | upsert 显式 pending、预览队列/状态/重置查询、ugoira 失败记录 |
| `sync/orchestrator.py` | 移除 `preview_targets`/`ugoira_targets` 收集，新增统一补拉与 `repair_assets()` |
| `media/downloader.py` | 失败原因回传并默认记 warning 日志 |
| `download/scope.py` | ugoira 任务只针对就绪元数据 |
| `web/routers/maintenance.py` | repair-previews 任务 |
| `web/routers/stats.py`、`web/schemas.py` | 新统计字段 |
| `cli.py` | `maintain repair-previews`、同步汇总 |
| `frontend/src/pages/StatsPage.tsx`、`SettingsPage.tsx`、`components/TaskPanel.tsx`、`api/types.ts`、`api/client.ts` | 统计行、按钮、任务文案 |
| `AGENTS.md` | 迁移 0005 与自愈行为说明 |
| `tests/*` | 见第 7 节 |

前端改动后必须执行 `npm run build` 并提交 `web/static/` 产物。

## 7. 测试计划

- **同步自愈**：第一轮预览失败（`FakeDownloader(fail_urls=...)`）→ 第二轮增量自动重试并成功，文件出现、状态 `ready`（直接复现本次 bug）。
- **尝试上限**：连续失败 5 轮后 `preview_state='failed'`，第 6 轮不再发起请求；`reset_failed_previews()` 后重新入队。
- **无效图片**：`fetch_bytes` 返回 `b""`/HTML 字节 → 不写文件、不置 `ready`、attempts+1。
- **迁移回填**：升级后已存在 `preview.jpg` 的作品只 stat 不下载，直接 `ready`。
- **动图**：元数据失败 → 下一轮重试；失败占位行不生成下载任务；成功行把 attempts 归零。
- **下载器回调**：`on_error` 在最终失败时被调用一次。
- **统计/维护/CLI**：`/api/stats` 新字段、`repair-previews` 端点返回、`maintain repair-previews` 退出码与输出。
- **迁移**：`0005` 在空库与已有数据库上 upgrade/downgrade（`tests/test_migrations.py`）。

## 8. 风险与取舍

- **首次运行成本**：迁移后第一次增量会对全部作品 stat 一次（万级作品通常 <1s，本地磁盘）；只对缺失的发请求。
- **永久 404 的封面**：最多重试 5 次后停在 `failed`，避免每 6h 打一次 pixiv；用户可在维护面板重置。
- **元数据过期**：`meta_json` 里的 `image_urls` 在元数据刷新时更新；若 URL 失效，失败会记录在 `preview_error` 中，重新全量同步刷新元数据后仍可恢复。
- **失败隔离**：补拉批次内单个目标异常只影响自身；写盘 OSError 不再中断整轮同步。
