# Pixiv Collection Archive

自托管的 pixiv 收藏同步与备份服务。**核心特性：完整保留收藏顺序。**

- 收藏顺序模型基于稀疏 rank + 位置快照（pixiv API 不提供单条收藏时间戳）
- 元数据同步与图片下载解耦：先快速建立索引，再按范围分批下载原图
- ugoira 动图保留原始 zip 并转码为 mp4
- React WebUI：画廊 / 详情 / 下载队列 / 统计 / 导出（计划中）
- 单容器 + SQLite，GHCR 镜像

## 状态

- [x] 项目基础 + pixiv API 层（当前进度）
- [ ] 阶段 A：元数据同步
- [ ] 阶段 B：图片下载
- [ ] Web API 与前端
- [ ] 发布

## 快速开始（开发）

```bash
uv sync
cp .env.example .env   # 填写 PIXIV_REFRESH_TOKEN / PIXIV_USER_ID
uv run pytest
```

真实 API 集成测试（需要代理与凭据）：

```bash
uv run pytest tests/test_integration_live.py -m integration -v -s
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
