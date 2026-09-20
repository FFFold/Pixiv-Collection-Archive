# Pixiv Collection Archive

自托管的 pixiv 收藏同步与备份服务。**核心特性：完整保留收藏顺序。**

- 收藏顺序模型基于稀疏 rank + 位置快照（pixiv API 不提供单条收藏时间戳）
- 元数据同步与图片下载解耦：先快速建立索引，再按范围分批下载原图
- ugoira 动图保留原始 zip 并转码为 mp4
- React WebUI：画廊 / 详情 / 下载队列 / 统计 / 导出（计划中）
- 单容器 + SQLite，GHCR 镜像

## 状态

- [x] 项目基础 + pixiv API 层
- [x] 阶段 A：元数据同步（增量 / 全量 + rank 顺序 + 预览图）
- [ ] 阶段 B：图片下载
- [ ] Web API 与前端
- [ ] 发布

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
uv run pytest tests/test_integration_live.py tests/test_integration_sync.py -m integration -v -s
```

## Docker

镜像由 GitHub Actions 构建并推送至 GHCR：

```bash
docker pull ghcr.io/fffold/pixiv-collection-archive:latest
docker compose up -d
```

数据保存在 `./data`（SQLite + 原图 + 缩略图）。

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

## 文档

- 设计文档：`docs/superpowers/specs/2026-09-20-pixiv-collection-archive-design.md`
- 实施计划：`docs/superpowers/plans/`
