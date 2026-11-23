# 首页封面按原图比例：medium 预览 + 一次性重抓（设计文档）

日期：2026-11-20
状态：已实施（2026-11-20），实施计划见 `docs/superpowers/plans/2026-11-20-preview-ratio.md`
关联：GitHub issue #2；`docs/superpowers/specs/2026-11-19-preview-selfheal-design.md`（封面自愈，PR #1 / v0.2.1）

## 1. 背景与目标

首页 `.masonry` 卡片高度由图片自身比例决定，但未下载作品的封面来自 pixiv 的 `square_medium`（540×540 中心裁剪），所以默认首页全部是正方形；已下载作品有本地 `thumb.webp`（原图比例，长边 400），因此只有它们参差。

实测（当前部署，仅作证据，不代表其他实例）：首页前 60 张全部 1:1、卡片高度均为 371px；`?downloaded=true` 时 20 种比例、高度 243–566px。规模：2178 个 active 作品，磁盘 2212 张 `preview.jpg`（2157 张 540×540），359 张 `thumb.webp`。

目标：

- 默认首页出现多种卡片高度，未下载作品的封面按原图比例、无中心裁剪。
- 已有方形封面通过一次性维护任务替换，任务可中断、可续跑，且中断后不会「假装完成」。
- `/api/stats` 与运维输出能看到剩余待重抓数量。

非目标：

- 不改前端瀑布流布局与 `resolve_thumb` 优先级（`thumb.webp` 仍优先）。
- 不新增数据库列、不新增迁移；不把旧方形封面另存为 `preview_ratio.jpg`（避免路径分叉）。
- 不动阶段 B 下载流程、原图/缩略图/ugoira 转码。
- 不主动删除任何已存在的 `preview.jpg`。

## 2. 方案选择

| 方案 | 说明 | 取舍 |
| --- | --- | --- |
| A｜全量标记 + 强制覆盖（**已选**） | 把所有待重抓作品标成「待重抓」，重抓时无条件覆盖写 | 实现最简单，语义直白；中断后重跑会重新拉取全部（2178 张、约 30–60MB），续跑靠状态标记避免重复 |
| B｜按文件比例精确筛选 | 用 Pillow 读 JPEG 头，只挑「DB 非正方形但封面 1:1」的作品重抓 | 中断续跑天然精确，但需额外的尺寸探针，且方形原作需靠 DB 宽高排除 |
| C｜旧图另存 `preview_square.jpg` | 保留方形旧图便于回滚 | 引入路径分叉，`resolve_thumb`/统计/维护都要兼容，issue 明确倾向不做 |

选 A。用户已确认，并特别提示风险：**远程图片已失效时不能把旧封面覆盖成占位符**。第 4 节给出防护与证据。

### 2.1 「待重抓」状态用 `preview_state='stale'`（评审后修订）

不能用「把所有作品重置为 `pending`」来表达待办：现有同步补拉对「`pending` 且 `preview.jpg` 已存在」的作品会**直接标 ready、不下载**（`sync/orchestrator.py:362-372`），于是重抓任务被取消后，下一轮定时同步就会把剩下的方形封面全部标成 `ready`，`previews_missing` 归零、面板显示「剩余 0」，实际仍有上千张方形。也不能只用外部进度文件：统计口径会与 `preview_state` 分裂。

修订为：给 `preview_state` 增加一个取值 **`stale`**（「有封面，但需要按新比例重抓」）。

- `illust.preview_state` 是 `String(16)`、无 CHECK 约束（`db/models.py:45`、`0005_preview_state.py:23`），**加取值不需要迁移**。
- `stale` 不属于同步补拉队列：`get_preview_backlog` 改为 `preview_state IN ('pending','failed')`，同步永远不会「吃掉」待重抓的作品。
- `stale` 不计入 `previews_missing`（真正缺封面的只有 `pending`/`failed`），单独统计为 `previews_stale`（剩余待重抓）。
- 队列本身就是 DB 里的 `stale` 行，**不再需要 `preview_refresh.json` 进度文件**；续跑 = 查询剩余 `stale` 行。

## 3. 预览 URL 优先级

- 新增 `src/pixiv_archive/media/preview.py`：
  - `preview_url_from_meta(meta_json: str | None) -> str | None`：解析 `image_urls`，优先级 **`medium` → `square_medium`**。
  - `PLACEHOLDER_MARKER = "s.pximg.net/common/images/limit_"`、`is_placeholder_url(url) -> bool`（与 `sync/unavailable.py` 的占位符判定同源）。
- `pixiv/models.py::Illust.preview_url` 改为 `medium` → `square_medium`。
- `sync/orchestrator.py::_preview_url` 删除，改为调用 `preview_url_from_meta`（保持单一实现）。
- 新收藏即时生效：`upsert_illust` 插入 `preview_state='pending'`，下一轮增量/全量的补拉队列就会用 `medium`。

`medium` 形如 `.../c/540x540_70/..._p0_master1200.jpg`（长边 540、保留比例），`square_medium` 是 `.../c/540x540_10_webp/..._p0_square1200.jpg`（1:1 裁剪）。

## 4. 失效封面覆盖风险（重点）

重抓只会**成功后才原子替换**，任何失败路径都保留旧图。逐条对应实现：

| 情形 | 现有机制 | 结果 |
| --- | --- | --- |
| HTTP 404/410/其它 ≥300 | `ImageDownloader._fetch_once` 返回 `(None, reason)`（`media/downloader.py:100-101`） | 不下发写入，旧图保留 |
| 网络错误 / 5xx / 429 | `retry_async` 3 次后 `NetworkError` → `fetch_bytes` 返回 `None` | 同上 |
| 200 但内容不是图片（HTML 错误页等） | `is_valid_image()` 全量 `load()` 解码（`media/thumbnails.py:13-24`） | 不写盘，记 `invalid image data` |
| 200 且是 pixiv 占位图（`limit_*`） | 新增：URL 命中 `PLACEHOLDER_MARKER` 时**直接判定失败、不发请求** | 旧图保留，`preview_error="placeholder url"` |
| 写入过程中崩溃/断电 | `atomic_write_bytes` 先写 `preview.jpg.part` 再 `os.replace`（`media/storage.py:8-19`） | 旧文件完整，残留 `.part` 被清理 |
| 作品已删除/私密（`state='deleted'`） | 重抓队列只选 `state='active'` | 不参与 |

补充约定：

- 旧文件从不先删后写，也从不移动；覆盖只发生在 `os.replace` 这一瞬间。
- 失败作品保留旧封面，**保持 `stale`**，记录 `preview_error` 并累加 `preview_attempts`，继续计入 `previews_stale`，运维可见。
- 重抓与同步在 Web 侧互斥（`kind="maintenance"` 与 `kind="sync"`）；CLI 与 Web 是不同进程，没有互斥，但同时运行只是重复下载（原子写 + 幂等），不会损坏文件。

## 5. 一次性重抓实现（方案 A）

### 5.1 模块

新增 `src/pixiv_archive/maintenance/preview_refresh.py`：

```text
REFRESH_BATCH = 50

@dataclass
class RefreshReport:
    total: int       # 本轮开始时 stale 行数
    fetched: int     # 本轮成功
    failed: int      # 本轮失败（仍为 stale）
    remaining: int   # 结束时仍为 stale 的行数
    skipped: int     # 已达 preview_attempts=5、本轮跳过的行数
    resumed: bool    # 本轮开始时已存在 stale 行（续跑）

class PreviewRefresher:          # 持有 db / storage / downloader
    async def run(self, *, restart: bool = False,
                  on_progress: ProgressCallback | None = None) -> RefreshReport
```

`sync/factory.py` 增加 `open_preview_refresher(settings)` 异步上下文管理器：`_ensure_schema()` + `Database` + `httpx.AsyncClient(proxy, timeout=60)` + `ImageDownloader(concurrency=settings.image_concurrency, mirror=...)` + `WorksStorage(settings.works_dir)`，退出时关闭客户端、`db.dispose()`。不创建 `PixivClient`（重抓完全不需要 API，也不受 API 限流影响）。

### 5.2 队列与状态转移

`db/repo/illusts.py` 新增：

- `mark_previews_stale(session, *, all_active: bool) -> int`
  - `all_active=True`（新开一轮或 `--restart`）：`UPDATE illust SET preview_state='stale', preview_attempts=0, preview_error=NULL WHERE state='active' AND thumb_ready=0 AND preview_state IN ('ready','stale')`。只接管**已经有封面**的作品；`pending`/`failed`（从未有过封面）留给同步补拉，避免 `previews_missing` 被吞掉。
  - `all_active=False`（收尾清理）：只把不再符合条件的行还原：`preview_state='stale' AND (state != 'active' OR thumb_ready=1)` → `ready`。
- `get_stale_preview_pids(session, *, max_attempts: int) -> list[int]`：`state='active' AND preview_state='stale' AND preview_attempts < 5 ORDER BY pid`。
- `count_previews_stale(session) -> int`：`state='active' AND preview_state='stale'`。
- `record_refresh_failure(session, pid, *, error)`：`preview_attempts + 1`、`preview_error=error[:500]`，**状态保持 `stale`**（不落到 `pending`/`failed`，避免被同步补拉接管）。
- `mark_previews_ready` 复用（清空 `preview_error`）。

运行逻辑：

1. `stale_now = count_previews_stale()`。
2. 若 `restart` 或 `stale_now == 0`：`mark_previews_stale(all_active=True)`，否则视为续跑（`resumed = stale_now > 0`）。
3. 先执行一次 `mark_previews_stale(all_active=False)`，把已删除/已有 `thumb.webp` 的残留 `stale` 还原为 `ready`。
4. 每批取 `get_stale_preview_pids(max_attempts=5)` 前 50 个，`asyncio.gather` 并发（`ImageDownloader` 内部信号量 = `IMAGE_CONCURRENCY`），逐个：
   - `preview_url_from_meta(meta_json)`；`None` → 失败 `"no preview url"`；命中占位符 → 失败 `"placeholder url"`（不发请求）。
   - `fetch_bytes` → `is_valid_image` → `atomic_write_bytes(storage.preview_path(pid))`。
   - 任何异常只记该 pid 失败，不中断批次。
5. 批次结束：`mark_previews_ready(成功 pids)`；失败者 `record_refresh_failure`；`session.commit()`；`on_progress("refresh-previews", done, total, f"重抓封面 {done}/{total}")`（`progress()` 在任务被取消时抛 `CancelledError`，因此取消在批次边界生效）。
6. 循环直到查不到 `preview_attempts < 5` 的 `stale` 行。结束时：
   - `remaining = count_previews_stale()`
   - `skipped = count(stale AND preview_attempts >= 5)`
7. 返回 `RefreshReport`。

### 5.3 中断、续跑与重试

- 中断（进程被杀 / 任务取消）：未处理的行仍是 `stale`，同步补拉不会碰它们；`previews_stale` 与 `/api/stats` 如实显示剩余。
- 再次执行：检测到 `stale > 0` → 续跑，只处理剩余（`resumed=True`），不重复下载已完成的。
- 失败行：每轮执行重试一次（`preview_attempts` 累加），达到 5 次后停在 `stale` 且被跳过，`skipped` 可见；此时需要人工 `--restart` 才会再次尝试。
- `--restart`：忽略已有 `stale`，把全部 `active && thumb_ready=0` 重新标记（`attempts=0`）并重抓。
- 同一批次内已成功但 DB 尚未写入的作品：重跑会再下载一次，结果幂等。

## 6. 对外接口

### 6.1 CLI

```powershell
uv run python -m pixiv_archive maintain refresh-previews [--restart]
```

- 输出：`封面重抓：总数 1819，成功 1802，失败 17，剩余 17（跳过 0，续跑）`。
- 退出码：任务正常跑完即 0；失败通过输出与 `previews_stale` 呈现（与 `maintain repair-previews` 的现有风格一致，不因个别图片 404 报错）。
- `--restart`：忽略已有 `stale` 标记重新全量重抓。
- 复用 `_ensure_schema`，不需要额外配置。

### 6.2 Web

`POST /api/maintenance/refresh-previews` → `202 TaskOut`，`kind="maintenance"`。

- 与 `repair-previews` 相同的互斥：有 `sync` 任务运行时 409；`TaskManager.start` 冲突时 409。
- 任务内调用 `open_preview_refresher(settings)`，`context.progress("refresh-previews", done, total, ...)`，返回 `asdict(RefreshReport)`。
- 请求体可带 `{"restart": false}`（默认 false）。

### 6.3 统计

`StatsOut` 增加 `previews_stale`：`state='active' AND preview_state='stale'`，即「剩余待重抓」。

同时把 `count_previews_missing` 的口径改为 `preview_state IN ('pending','failed')`（真正没有封面的作品），避免把「有方形封面」算成缺失。三个数互斥且覆盖全部 active 作品：`previews_ready` + `previews_missing` + `previews_stale` = `total_illusts`。

### 6.4 前端

- `api/types.ts`：`RefreshPreviewsResult`（`total/fetched/failed/remaining/skipped/resumed`）、`Stats` 增加 `previews_stale`。
- `api/mutations.ts`：`useRefreshPreviews()` → `POST /api/maintenance/refresh-previews`，成功后 invalidate `tasks`、`stats`。
- `components/MaintenanceCard.tsx`：新增按钮「重抓封面」与「全量重抓封面」，点击先 `window.confirm`，只说明动作与「可中断续跑」，不写死体积/张数/耗时等随部署而变的数字。
- `components/TaskPanel.tsx`：维护任务结果多一个分支 `"previews_stale_remaining" in detail` → `重抓封面 ${fetched}/${total} · 失败 ${failed} · 剩余 ${remaining}`。
- `pages/Stats.tsx`：统计行增加「待重抓封面 N」。
- `components/GalleryCard.tsx`：`<img>` 增加 `width={item.width}` / `height={item.height}`，让浏览器在图片加载前就知道比例，减少多列重排（CSS 仍是 `w-full` + `object-cover`，`h-auto` 已由 preflight 兜住）。
- 前端改动后执行 `npm run build` 并提交 `web/static/` 产物。

## 7. 涉及文件

| 文件 | 变更 |
| --- | --- |
| `media/preview.py` | 新增：`preview_url_from_meta`、占位符判定 |
| `pixiv/models.py` | `Illust.preview_url` 优先级改为 `medium` → `square_medium` |
| `sync/orchestrator.py` | `_preview_url` 改为调用共享函数 |
| `db/repo/illusts.py` | `stale` 状态：标记/查询/计数/失败记录；`get_preview_backlog`、`count_previews_missing` 口径调整 |
| `maintenance/preview_refresh.py` | 新增：批量重抓、`RefreshReport` |
| `sync/factory.py` | 新增 `open_preview_refresher` |
| `cli.py` | `maintain refresh-previews [--restart]` 与输出 |
| `web/routers/maintenance.py` | 新端点 |
| `web/routers/stats.py`、`web/schemas.py` | `previews_stale` 字段 |
| `frontend/src/api/{types,mutations}.ts`、`components/{MaintenanceCard,TaskPanel,GalleryCard}.tsx`、`pages/Stats.tsx` | 按钮、任务文案、统计行、img 尺寸 |
| `AGENTS.md` | 升级说明与命令 |
| `tests/*` | 见第 8 节 |

## 8. 测试计划

- **URL 优先级**：`Illust.preview_url` 与 `preview_url_from_meta` 在两者都存在时返回 `medium`；只有 `square_medium` 时退化；`meta_json` 缺失/损坏返回 `None`。
- **成功覆盖**：文件预置方形字节、`FakeDownloader` 返回新字节 → 文件内容被替换、`preview_state='ready'`、`preview_error` 清空。
- **失败保留旧图**：`fetch_bytes` 返回 `None`/非法图片/占位符 URL → 旧字节不变、仍为 `stale`、`preview_attempts` +1、`preview_error` 记录。
- **占位符不发请求**：`meta_json` 的 `medium` 指向 `limit_*` 时 downloader 调用次数为 0。
- **只重抓未下载作品**：`thumb_ready=True` 的作品不被标记 `stale`；运行中出现该情况会被还原为 `ready`。
- **同步不吞队列**：存在 `stale` 行时执行一轮增量同步，`stale` 行保持 `stale`、不产生下载、不被标 `ready`（回归评审指出的漏洞）。
- **可中断/续跑**：第一次运行预置部分 `stale` 行 → 只请求这些 pid、`resumed=True`；中断后剩余仍为 `stale`，再次运行处理剩余。
- **重试上限**：连续失败 5 轮后不再发请求，计入 `skipped`；`--restart` 后重新尝试。
- **统计口径**：`previews_ready + previews_missing + previews_stale == total_illusts`；`/api/stats` 新字段。
- **CLI**：输出格式、`--restart`、退出码（`tests/test_cli.py`）。
- **Web**：`POST /api/maintenance/refresh-previews` 返回 202/TaskOut，sync 运行中返回 409（`tests/test_web_maintenance.py`）。
- **前端**：`MaintenanceCard` 按钮确认后触发 mutation；`TaskPanel` 新分支文案；`Stats` 新行（`npm test`）。

## 9. 升级与回滚

- 升级后**必须**执行一次 `maintain refresh-previews`（或设置页按钮），历史方形封面才会被替换；不执行则行为与现在一致。
- 预估成本（本机实例的实测参考，不代表其他部署）：约 1800 张 × 几十 KB ≈ 30–60MB，4 并发下一到几分钟。
- 回滚：改回 URL 优先级后同样执行一次 `refresh-previews --restart` 即可回到方形封面；旧方形图不保留副本（这是方案 A 的取舍）。
- `stale` 只是 `preview_state` 的新取值，降级到旧版本时旧代码把它当作「非 ready」，会走补拉并因文件存在而标 `ready`（无害的自动收敛）。
