# 画廊筛选/批量操作与维护增强设计文档

日期：2026-09-21
状态：设计已确认，待生成实施计划
关联：`docs/superpowers/specs/2026-09-20-pixiv-collection-archive-design.md`（基线设计）

## 1. 背景与目标

基线版本已完整跑通同步 / 下载 / WebUI，但前端在批量操作与筛选上存在明显缺口：

1. **不能整页批量选择**：`useSelection` 只有逐个 `toggle`，没有全选/反选/仅选未下载。
2. **不能一次翻多页**：`Pagination` 只有上一页/下一页，`PAGE_SIZE` 固定 60。
3. **筛选状态易丢失**：`Gallery` 用 `useState` 保存 query，只有 `tag` 从 URL 读取；刷新、分享链接、`IllustDetail` 的 `/?author=` 链接都不生效。
4. **筛选能力弱**：不能按页数区间、多标签、多作者、收藏数/浏览数区间过滤。
5. **"下载全部未下载"不遵守筛选**：前端只传 `x_restrict/type`，`download/scope.py` 的 `filter` 分支也只支持少量字段；导出同样缺少筛选。
6. **统计慢且不可交互**：`/api/stats` 用 `rglob("*")` 全盘扫描体积与缩略图数量；失败页数没有重试入口。
7. **Docker 部署下的维护困难**：历史数据回填（体积等）若只提供 CLI，需要 `docker exec` 进入容器，不便。

本轮目标（已与用户确认）：

- **子项目 ①「画廊核心」**：跨页累积选择 + 页级批量操作、增强页码分页、全部筛选条件 URL 化、多标签（AND）/多作者/页数区间/收藏数与浏览数区间筛选、共享筛选核心使下载范围遵守筛选。
- **子项目 ②「导出与统计 + 维护」**：按选中/按当前筛选导出；统计改为 SQL 聚合并新增体积与页数分布、指标可点击跳转；WebUI 维护面板（重建存储统计 / 修复下载状态 / 数据库体检）。

### 1.1 明确不做（本轮）

- 无限滚动（已确认保留增强页码分页）。
- "全选筛选结果"的选择模式（整批操作走"下载全部未下载"与"按当前筛选导出"）。
- 选择状态跨刷新保留（sessionStorage）；仅跨路由保留。
- 多标签 OR 或 AND/OR 切换（固定 AND）。
- 发布日期区间、下载完整度筛选（本轮未选）。
- Lightbox / 瀑布流虚拟化等浏览体验优化（原调查的 E 组，另立项目）。

## 2. 已确认决策

| 主题 | 决策 |
| --- | --- |
| 选择语义 | 跨页累积勾选；页级操作：全选本页 / 取消本页 / 反选本页 / 仅选本页未下载 |
| 选择持久范围 | 提升到全局 Context，跨路由保留，刷新清空 |
| 分页 | 增强页码分页：每页 60/120/240、页码跳转、首页/末页、←/→ 键盘翻页、URL 同步 |
| 新增筛选 | 页数区间、多标签（AND）、多作者、收藏数区间、浏览数区间 |
| 筛选架构 | 共享筛选核心 `db/query.py`，画廊 / 下载 / 导出复用 |
| 导出 | 按选中、按当前筛选（保留原有全部/条件表单） |
| 统计 | 体积与页数分布、SQL 聚合性能优化、指标可点击跳转 |
| 维护 | WebUI 面板：重建存储统计、修复下载状态、数据库体检报告 |
| 体积回填 | 迁移只加列，不回填；由维护面板/CLI 显式触发 |

## 3. 架构总览

```
                 ┌────────────────────────────┐
                 │  db/query.py               │
                 │  IllustFilters             │
                 │  build_illust_query()      │
                 └──────┬──────┬──────┬───────┘
                        │      │      │
        ┌───────────────┘      │      └────────────────┐
        ▼                      ▼                       ▼
 web/gallery_query.py   download/scope.py      web/routers/export.py
 （+display_index 窗口）  （filter 分支）          （按筛选导出）
        │                      │                       │
        └──────────────────────┴───────────────────────┘
                               ▼
                    GET /api/gallery
                    POST /api/downloads
                    POST /api/export
```

维护面板（子项目 ②）复用现有 `TaskManager` + SSE，不引入新任务框架。

## 4. 共享筛选核心（后端）

新增 `src/pixiv_archive/db/query.py`：

```python
@dataclass
class IllustFilters:
    sort: str = "rank"                       # rank|create_date|bookmarks|views
    # 多值筛选
    tags: list[str] = field(default_factory=list)          # AND：每个 tag 一个 EXISTS
    author_ids: list[int] = field(default_factory=list)    # IN
    # 单值筛选（沿用现语义）
    q: str | None = None
    type: str | None = None
    x_restrict: int | None = None
    downloaded: bool | None = None
    restrict: str | None = None
    only_unbookmarked: bool = False
    include_unbookmarked: bool = False
    only_deleted: bool = False
    include_deleted: bool = False
    # 区间筛选
    page_min: int | None = None
    page_max: int | None = None
    bookmarks_min: int | None = None
    bookmarks_max: int | None = None
    views_min: int | None = None
    views_max: int | None = None
    # rank 窗口（沿用现语义）
    rank_start: int | None = None
    rank_count: int | None = None


def build_illust_query(filters: IllustFilters) -> Select[Any]:
    """base join（Illust+Bookmark+Author）+ 全部条件，不含排序/分页。"""
```

实现要点：

- 迁移现有 `gallery_query.py` 的 `_base_conditions` / `_build_base_select` 逻辑，行为保持不变（默认 `active` + `active bookmark`、`q` 匹配标题或画师名、rank 窗口子查询等）。
- 多标签 AND：对每个 tag 生成一个 `EXISTS (SELECT 1 FROM illust_tag JOIN tag ... WHERE illust_tag.pid = Illust.pid AND tag.name = :t)`，避免 JOIN + DISTINCT 与计数/分页冲突。
- 多作者：`Illust.author_id.in_(author_ids)`。
- 区间：`Illust.page_count >= page_min` 等，闭区间；`*_max` 为 `None` 时不加条件。
- `build_illust_query` 只构建条件；画廊侧再 `_order()` 并附加 `row_number() over(order_by=...)` 计算 `display_index`（保持现行为），下载/导出侧直接使用。
- 旧 `GalleryFilters` 类删除，`gallery_query.py` 只保留 `query_gallery()`（接收 `IllustFilters`），现有测试与调用点改为导入 `db.query.IllustFilters`；对外 HTTP API 行为不变。
- 排序：`_SORTS` 字典随构造器一起迁移到 `db/query.py`，下载/导出无需排序（或统一按 rank）。

## 5. Web API 变更

### 5.1 `GET /api/gallery`

新增可选参数（全部向后兼容）：

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `tag` | 可重复 `str` | 多个 `tag=` 为 AND；单个时行为同旧版 |
| `author_id` | 可重复 `int` | 多个为 OR（IN） |
| `page_min` / `page_max` | `int >= 1` | 页数区间 |
| `bookmarks_min` / `bookmarks_max` | `int >= 0` | 收藏数区间 |
| `views_min` / `views_max` | `int >= 0` | 浏览数区间 |

FastAPI 查询参数保持单数名：`tag: Annotated[list[str], Query()] = []`、`author_id: Annotated[list[int], Query()] = []`（`?tag=a&tag=b`）。**注意**：原 `author_id: int | None` 变为列表后，OpenAPI schema 变化属预期；行为上单值等价。请求体字段用 `tags` / `author_ids`（JSON 中避免与单数混用），由路由层映射。

`limit` 上限从 200 提升到 500（每页 240 需要）。

响应结构不变（`GalleryItem` 已含全部展示字段）。

### 5.2 `POST /api/downloads`

`DownloadRequest` 增加同一批筛选字段（`tags`、`author_ids`、`page_min/max`、`bookmarks_min/max`、`views_min/max`、`q`、`restrict`、`only_unbookmarked`、`downloaded`、`only_deleted` 等）。`download/scope.py` 的 `DownloadScope` 同步扩展，`filter` 分支改为调用 `build_illust_query`。

`empty_scope_matches_nothing` 的语义更新为：`filter` 且**没有任何筛选字段**时仍匹配空集（防止误触发全库下载）；前端"下载全部未下载"始终至少传 `downloaded=false`，因此不受影响。

前端"下载全部未下载"从此提交完整筛选条件，修复语义 bug（默认仍为 `active + bookmarked`）。`scope.kind` 的取值集合不变，仅 `filter` 分支的可用字段扩展。

### 5.3 `POST /api/export`

`ExportRequest` 增加同一批筛选字段。`_selected_pids` 改用 `build_illust_query`：

- 若传 `pids`，则按 pids 精确导出（保留旧行为：**包含已失效作品**；`x_restrict` / `only_downloaded` 继续生效，现有测试 `test_export_includes_deleted_works` 依赖此行为）。
- 新增 `use_filter` 布尔字段：为 `true` 时按筛选条件导出，语义与画廊一致（默认 `active`，不含已失效作品）。
- `pids` 与 `use_filter` 互斥，`pids` 优先；两者都为假时保持旧行为（导出全部行，含 deleted），前端旧的"全部/条件"表单走这条路径。

### 5.4 维护接口（子项目 ②）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/maintenance/rebuild-stats` | 后台任务：扫描 `works/` 回填 `byte_size` / `thumb_ready` / `animation_ready` |
| `GET` | `/api/maintenance/repair-download-state/preview` | 只读预览：按文件系统计算将要修正的页数与作品数，返回计数，不改库 |
| `POST` | `/api/maintenance/repair-download-state` | 后台任务：按文件系统修正 `has_original` / `page_downloaded_count` / `illust_page.download_state` |
| `POST` | `/api/maintenance/db-check` | 同步只读体检：`PRAGMA integrity_check`、孤立行、DB/文件不一致、重复 rank，返回结构化报告 |

`repair` 拆成 preview（GET，无副作用）+ 执行（POST）两个端点，避免一个端点混合返回两种语义；UI 先调 preview 展示计数，用户确认后再 POST 启动任务。任务走 `TaskManager`（新 kind `maintenance`），SSE 复用；`db-check` 返回 JSON 报告（不建任务，操作很快）。

## 6. 前端：画廊核心

### 6.1 筛选状态 URL 化

新增 `src/hooks/useGalleryQueryState.ts`：以 `useSearchParams` 为唯一状态源，读写全部筛选字段与分页字段。序列化规则：

- 多值用重复参数（`tag=a&tag=b`）。
- 空值 / 默认值不写入 URL。
- 变更筛选项时自动 `offset=0`。
- `Gallery` 与 `IllustDetail` 的链接统一使用新参数名（修复 `/?author=` 与 `/?tag=`）。

同时新增 `src/contexts/GalleryFiltersContext.tsx`（挂在 `App` 层）：保存"画廊最近一次生效的筛选条件"，由 `Gallery` 在筛选变更时写入，供 `Export` 页面读取（实现"按当前筛选导出"）；应用启动时初始化为空。

### 6.2 SelectionContext

新增 `src/contexts/SelectionContext.tsx`（挂在 `App` 层）：

```ts
interface SelectionValue {
  selected: Set<number>;
  count: number;
  toggle(pid: number): void;
  selectMany(pids: number[]): void;
  removeMany(pids: number[]): void;
  clear(): void;
}
```

- 跨页累积、跨路由保留、刷新清空。
- 工具栏显示"已选 N"，可展开面板查看并移除单个 pid、清空全部。
- 详情页加入"加入选择/从选择移除"按钮（复用同一 Context）。

### 6.3 Toolbar 增强

- 页级操作：`全选本页`、`取消本页`、`反选本页`、`仅选本页未下载`。
- 下载选中按钮遵循跨页 pids（`selected` scope），按钮文案提示"下载选中 (N)"。
- 新增筛选控件：
  - 页数区间：预设下拉（全部 / 1P / 2–5P / 6–10P / 11P+）+ 自定义 min/max。
  - 多标签：由 `/api/tags` 提供候选，多选 chip，AND 语义；详情页标签点击为"加入当前 tag 筛选"。
  - 多作者：由 `/api/authors` 提供候选（含本地搜索过滤），多选 chip。
  - 收藏数/浏览数区间：min/max 数字输入，失焦或回车应用。
- 工具栏随筛选数量显示"已启用 N 项筛选"与一键清空。

### 6.4 Pagination 增强

- 每页数量选择：60 / 120 / 240（上限与后端 `limit<=200` 冲突，需将后端上限提升或前端限制为 200；本设计取**提升后端上限到 500**，前端仍只提供 240）。
- 页码输入跳转 + 首页/末页按钮 + 当前页/总页数显示。
- `←`/`→` 键盘翻页（`input` / `textarea` / `select` 聚焦时不触发）。
- 分页状态（`offset`、`limit`）写入 URL，刷新保持。

### 6.5 画廊网格与卡片

- `GalleryGrid` 不接收整页 pid 列表；页级操作在 `Gallery.tsx` 内基于 `items` 直接调用 `SelectionContext` 的 `selectMany` / `removeMany`。
- `GalleryCard` 增加缩略图 `onError` 回退本地占位图（`/api/illust/{pid}/thumb` 已回退到 SVG 占位，但资源加载失败时前端仍需兜底）。

## 7. 导出增强（子项目 ②）

`Export.tsx` 增加范围选择（三种互斥）：

- **按选中**：使用 `SelectionContext.selected` 的 pids；为空时禁用并提示。
- **按当前筛选**：使用 `GalleryFiltersContext` 保存的"画廊最近筛选条件"（`Gallery` 页面每次筛选变更时同步写入，刷新后回落到默认）。未访问过画廊时该项禁用；UI 同时展示当前生效的筛选摘要（如"3 个筛选条件"）。
- **全部 / 条件**：保留现有表单（元数据 / 原图 / 仅已下载 / 分级），走旧导出路径。
- 导出时可勾选"按作者分组目录"（`{author_id}/{pid}/...`）。

## 8. 统计增强与维护面板（子项目 ②）

### 8.1 DB 迁移 `0004`

`Illust` 新增列（均带默认值，迁移不扫描文件系统）：

| 列 | 类型 | 默认 | 含义 |
| --- | --- | --- | --- |
| `byte_size` | `BigInteger` | 0 | 该作品本地文件总字节（原图 + 缩略图 + 动图 + zip） |
| `thumb_ready` | `Boolean` | false | `thumb.webp` 是否存在 |
| `animation_ready` | `Boolean` | false | `animation.mp4` 是否存在 |

### 8.2 下载 worker 埋点

`download/worker.py` 在写文件成功后维护上述列：

- `_handle_image` / `_ensure_first_original`：累加原图字节。
- `_handle_thumb`：置 `thumb_ready=true` 并累加字节。
- `_handle_ugoira_zip` / `_handle_ugoira_mp4`：累加字节，前者置 zip、后者置 `animation_ready=true`。
- 实现方式：`media/storage.py` 提供 `file_size(path)` 辅助；worker 在 `_mark_page_done` 等收尾处统一更新。

### 8.3 `/api/stats` 改为 SQL 聚合

- `total_bytes` = `SUM(Illust.byte_size)`；`thumbs_ready` = `COUNT(thumb_ready)`；`animation_ready` = `COUNT(animation_ready)`。
- 新增 `by_type_bytes: dict[str, int]`、`by_restrict_bytes: dict[str, int]`、`top_authors_bytes: list[{id, name, bytes, illust_count}]`（前 10）。
- 不再调用 `rglob`；`StatsOut` schema 增加上述字段与 `stats_stale`。
- 未回填的历史数据 `byte_size=0`，`stats_stale = EXISTS(has_original=true AND byte_size=0)`，UI 据此提示"点击重建存储统计"。

### 8.4 维护任务

| 任务 | 行为 | 产物 |
| --- | --- | --- |
| `rebuild-stats` | 遍历 `works/{pid}`，计算总大小与三个布尔列 | 更新 `illust` 三列；任务 detail 记录处理数与总字节 |
| `repair-download-state` | 按 `original/` 实际文件修正页状态与计数；不动已 `done` 但文件缺失的元数据 | 更新 `illust_page.download_state` / `illust.has_original` / `page_downloaded_count`；先返回预览计数再执行 |
| `db-check` | 只读检查：`PRAGMA integrity_check`、孤立 `bookmark`/`illust_page`/`illust_tag`、`has_original` 与文件不一致、重复 rank | JSON 报告：`{ok, issues: [{kind, count, samples}]}` |

CLI parity：新增 `uv run python -m pixiv_archive maintain rebuild-stats|repair-download-state|db-check`。

### 8.5 设置页维护区块

`Settings.tsx` 新增"维护"卡片：

- 三个操作按钮 + 说明文字（含"重建统计较慢"提示）。
- `rebuild-stats` / `repair-download-state` 显示任务进度（复用 `TaskPanel` 的 SSE 组件，或跳转任务页）。
- `db-check` 就地展示报告（`ok` / 问题列表 / 样本 pid）。

## 9. 测试策略

后端（pytest）：

- `tests/test_db_query.py`：`IllustFilters` 每个条件与组合的查询结果（多标签 AND、多作者 IN、区间边界、默认 active/unbookmarked、与旧 `GalleryFilters` 行为等价性回归）。
- `tests/test_web_gallery_query.py`：现有用例改为通过 `IllustFilters` 运行，确保行为不回退；新增新参数用例。
- `tests/test_download_scope.py`：`filter` 分支遵守全部新字段。
- `tests/test_web_export.py`：按筛选导出、按 pids 导出、交集语义。
- `tests/test_web_maintenance.py`：三个维护操作（用临时 works 目录伪造文件），rebuild 后统计字段正确。

前端（vitest）：

- `useGalleryQueryState`：URL 读写、默认值省略、多值序列化。
- `SelectionContext`：跨页累积、removeMany、clear、跨路由保留（`MemoryRouter` + 路由切换）。
- `Pagination`：页大小切换、跳页、首末页、键盘。
- `Toolbar`：页级操作回调、筛选 chip 增删。

验证顺序遵循仓库 CI：`ruff check` → `ruff format --check` → `mypy` → `pytest`；前端 `npm run lint/typecheck/test/build`，且前端改动后必须 `npm run build` 重新生成 `web/static`。

## 10. 风险与边界

| 风险 | 对策 |
| --- | --- |
| `limit` 上限 200 与每页 240 冲突 | 后端上限提升到 500（仅影响查询，无新风险） |
| 多标签 EXISTS 子查询在超大数据量下变慢 | `illust_tag` 已有 `(pid, tag_id)` 主键；`tag.name` 唯一索引；必要时先在子查询里按 name 取 id 列表 |
| `byte_size` 回填前后统计不一致 | `/api/stats` 暴露 `stats_stale`，UI 提示重建；任务完成后自动刷新 |
| `repair-download-state` 误改数据 | preview 端点只读预览计数，UI 二次确认后再 POST 执行；仅修正文件系统可观测的事实 |
| 选择状态跨路由保留导致详情页误操作 | 选择面板提供逐项移除与清空；下载前确认 pids 数量 |
| URL 参数爆炸（多标签/多作者） | 参数上限（各 20 个），超出时忽略并在 UI 提示 |

## 11. 实施拆分

- **子项目 ① 画廊核心**：`db/query.py` → 路由参数 → `scope.py` / 导出接入 → 前端 URL 状态 → SelectionContext → Toolbar / Pagination → 测试与构建。
- **子项目 ② 导出与统计 + 维护**：迁移 0004 → worker 埋点 → `/api/stats` 聚合 → 维护任务与 API → CLI parity → Export/Settings/Stats UI → 测试与构建。

② 依赖 ① 的共享筛选核心，按顺序实施。
