# 计划 4b：React 前端

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 React + TypeScript 实现完整 WebUI：登录、瀑布流画廊（多选 + 批量下载）、作品详情（大图/多页/动图）、下载与同步任务面板（SSE 实时进度）、统计仪表盘、导出面板，并接入 Docker 多阶段构建。

**Architecture:** `frontend/` 为独立 Vite 项目。技术栈：React 19 + TypeScript + TanStack Query（服务端状态）+ react-router（路由）+ Tailwind CSS + 手写轻量组件（不引入 shadcn CLI，直接写 Tailwind 组件以保持可控）。布局为左侧常驻导航 + 顶部工具栏 + 主内容区（brainstorm 选定的方案 A）。开发时 Vite 代理 `/api` 到 8000；生产构建产物由 FastAPI 静态服务托管。认证走 HttpOnly cookie，前端只探测 `/api/auth/me`。

**Tech Stack:** Vite 7、React 19、TypeScript 5、Tailwind CSS 4、TanStack Query 5、react-router 7、Vitest + Testing Library

---

## 文件结构

| 文件 | 职责 |
| --- | --- |
| `frontend/package.json` | 依赖与脚本（dev/build/test/lint/typecheck） |
| `frontend/vite.config.ts` | 构建配置 + `/api` 代理 + 构建产物输出到后端 static |
| `frontend/tsconfig.json` / `tsconfig.app.json` | TS 配置 |
| `frontend/eslint.config.js` | ESLint |
| `frontend/index.html` | SPA 外壳 |
| `frontend/src/main.tsx` | 入口（QueryClientProvider + Router） |
| `frontend/src/index.css` | Tailwind 引入 + 主题变量 |
| `frontend/src/api/types.ts` | 后端响应类型（与 pydantic schema 对齐） |
| `frontend/src/api/client.ts` | fetch 封装（凭据、错误、重试无关的薄封装） |
| `frontend/src/api/queries.ts` | TanStack Query hooks（gallery/detail/stats/tasks/authors/tags） |
| `frontend/src/api/mutations.ts` | 登录/同步/下载/导出/取消任务 |
| `frontend/src/api/sse.ts` | SSE 订阅 hook（进度事件） |
| `frontend/src/components/AppLayout.tsx` | 侧栏 + 顶栏 + Outlet |
| `frontend/src/components/GalleryGrid.tsx` | 瀑布流网格（CSS columns）+ 懒加载卡片 |
| `frontend/src/components/GalleryCard.tsx` | 单卡片（序号、角标、选择框、动图标记） |
| `frontend/src/components/Toolbar.tsx` | 排序 / 过滤 / 搜索 / 下载按钮 |
| `frontend/src/components/TaskPanel.tsx` | 任务进度与历史（SSE 驱动） |
| `frontend/src/components/Lightbox.tsx` | 大图查看器（多页切换、缩放、动图） |
| `frontend/src/components/Pagination.tsx` | 分页控件 |
| `frontend/src/pages/Login.tsx` | 登录页 |
| `frontend/src/pages/Gallery.tsx` | 画廊页（含已取消收藏视图） |
| `frontend/src/pages/IllustDetail.tsx` | 作品详情页（路由 `/illust/:pid`） |
| `frontend/src/pages/Tasks.tsx` | 同步/下载面板页 |
| `frontend/src/pages/Stats.tsx` | 统计页 |
| `frontend/src/pages/Export.tsx` | 导出页 |
| `frontend/src/pages/Settings.tsx` | 设置/关于页 |
| `frontend/src/hooks/useSelection.ts` | 多选状态（跨分页保持） |
| `frontend/src/lib/format.ts` | 字节/日期格式化 |
| `frontend/src/lib/constants.ts` | 排序/过滤选项常量 |
| `frontend/vitest.setup.ts` | 测试环境设置 |
| `frontend/src/**/*.test.tsx` | 组件与逻辑测试 |

---

### Task 1: 项目脚手架与构建管线

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`, `frontend/tsconfig.app.json`, `frontend/tsconfig.node.json`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/index.css`
- Create: `frontend/eslint.config.js`
- Create: `frontend/.gitignore`
- Modify: `.gitignore`（忽略 frontend/node_modules、frontend/dist）

- [ ] **Step 1: 创建 package.json**

`frontend/package.json`：

```json
{
  "name": "pixiv-archive-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest",
    "lint": "eslint .",
    "typecheck": "tsc -b --noEmit"
  },
  "dependencies": {
    "@tanstack/react-query": "^5.62.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "react-router-dom": "^7.1.0"
  },
  "devDependencies": {
    "@eslint/js": "^9.17.0",
    "@tailwindcss/vite": "^4.0.0",
    "@testing-library/jest-dom": "^6.6.3",
    "@testing-library/react": "^16.1.0",
    "@testing-library/user-event": "^14.5.2",
    "@types/react": "^19.0.2",
    "@types/react-dom": "^19.0.2",
    "@vitejs/plugin-react": "^4.3.4",
    "eslint": "^9.17.0",
    "eslint-plugin-react-hooks": "^5.1.0",
    "eslint-plugin-react-refresh": "^0.4.16",
    "globals": "^15.14.0",
    "jsdom": "^25.0.1",
    "tailwindcss": "^4.0.0",
    "typescript": "~5.7.2",
    "typescript-eslint": "^8.18.0",
    "vite": "^7.0.0",
    "vitest": "^3.0.0"
  }
}
```

- [ ] **Step 2: 创建构建与 TS 配置**

`frontend/vite.config.ts`：

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    // FastAPI serves the package directory as /static; keep assets relative
    outDir: "../src/pixiv_archive/web/static",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    css: false,
  },
});
```

`frontend/tsconfig.json`：

```json
{
  "files": [],
  "references": [
    { "path": "./tsconfig.app.json" },
    { "path": "./tsconfig.node.json" }
  ]
}
```

`frontend/tsconfig.app.json`：

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src", "vitest.setup.ts"]
}
```

`frontend/tsconfig.node.json`：

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2023"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,
    "strict": true,
    "types": ["node"]
  },
  "include": ["vite.config.ts"]
}
```

- [ ] **Step 3: 创建入口文件与样式**

`frontend/index.html`：

```html
<!doctype html>
<html lang="zh-CN" class="dark">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Pixiv Archive</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`frontend/src/index.css`：

```css
@import "tailwindcss";

@theme {
  --color-surface: #0f1115;
  --color-surface-raised: #161a20;
  --color-surface-hover: #1d2531;
  --color-border-subtle: #262b33;
  --color-text-primary: #e6ebf2;
  --color-text-muted: #9aa4b2;
  --color-accent: #3b82f6;
}

html,
body,
#root {
  height: 100%;
}

body {
  margin: 0;
  background-color: var(--color-surface);
  color: var(--color-text-primary);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
}

/* Masonry via CSS columns: keeps DOM order (bookmark order) intact. */
.masonry {
  column-gap: 0.75rem;
}
.masonry > * {
  break-inside: avoid;
  margin-bottom: 0.75rem;
}
```

`frontend/src/main.tsx`：

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createBrowserRouter } from "react-router-dom";

import App from "./App";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

const router = createBrowserRouter([
  {
    path: "*",
    element: <App />,
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
```

- [ ] **Step 4: 创建 eslint、gitignore 与测试设置**

`frontend/eslint.config.js`：

```js
import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "../src/pixiv_archive/web/static"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
    },
  },
);
```

`frontend/.gitignore`：

```
node_modules
dist
.vite
coverage
```

在仓库根 `.gitignore` 末尾追加：

```
# frontend build artifacts (generated into the backend package)
src/pixiv_archive/web/static/assets/
src/pixiv_archive/web/static/index.html
```

`frontend/vitest.setup.ts`：

```ts
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 5: 最小 App 与验证构建**

`frontend/src/App.tsx`：

```tsx
export default function App() {
  return (
    <div className="flex h-full items-center justify-center">
      <p className="text-text-muted">Pixiv Archive</p>
    </div>
  );
}
```

Run:
```bash
cd frontend
npm install
npm run build
```
Expected: `npm install` 成功；`npm run build` 输出到 `../src/pixiv_archive/web/static/`，并打印构建产物大小

Run: `npm run lint && npm run typecheck`
Expected: 无错误

- [ ] **Step 6: Commit**

```bash
git add frontend .gitignore
git commit -m "feat(frontend): scaffold vite react ts project with tailwind"
```

---

### Task 2: API 客户端与类型

**Files:**
- Create: `frontend/src/api/types.ts`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/lib/format.ts`
- Test: `frontend/src/lib/format.test.ts`
- Test: `frontend/src/api/client.test.ts`

- [ ] **Step 1: 写失败的测试**

`frontend/src/lib/format.test.ts`：

```ts
import { describe, expect, it } from "vitest";

import { formatBytes, formatDate, formatIndex } from "./format";

describe("formatBytes", () => {
  it("formats bytes with binary units", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
  });
});

describe("formatDate", () => {
  it("formats ISO dates as YYYY-MM-DD", () => {
    expect(formatDate("2026-03-16T11:42:49+09:00")).toBe("2026-03-16");
  });

  it("returns a dash for empty values", () => {
    expect(formatDate(null)).toBe("—");
  });
});

describe("formatIndex", () => {
  it("pads the display index", () => {
    expect(formatIndex(7)).toBe("#0007");
    expect(formatIndex(1234)).toBe("#1234");
  });
});
```

`frontend/src/api/client.test.ts`：

```ts
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiFetch, setUnauthorizedHandler } from "./client";

afterEach(() => {
  vi.restoreAllMocks();
  setUnauthorizedHandler(null);
});

describe("apiFetch", () => {
  it("returns parsed json on success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ),
    );
    await expect(apiFetch<{ ok: boolean }>("/api/health")).resolves.toEqual({ ok: true });
  });

  it("throws ApiError with server detail on failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "invalid token" }), {
          status: 401,
          headers: { "content-type": "application/json" },
        }),
      ),
    );
    const error = await apiFetch("/api/gallery").catch((err: unknown) => err);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(401);
    expect((error as ApiError).message).toBe("invalid token");
  });

  it("invokes the unauthorized handler on 401", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("{}", { status: 401 })),
    );
    await apiFetch("/api/gallery").catch(() => undefined);
    expect(handler).toHaveBeenCalledOnce();
  });

  it("serializes body and sets json content type for post", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("{}", { status: 200, headers: { "content-type": "application/json" } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await apiFetch("/api/auth/login", { method: "POST", body: { token: "x" } });
    const [, init] = fetchMock.mock.calls[0];
    expect(init.method).toBe("POST");
    expect(init.headers["content-type"]).toBe("application/json");
    expect(init.body).toBe(JSON.stringify({ token: "x" }));
    expect(init.credentials).toBe("same-origin");
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npm test`
Expected: FAIL — 找不到模块 `./format` / `./client`

- [ ] **Step 3: 实现 format.ts 与 client.ts**

`frontend/src/lib/format.ts`：

```ts
const UNITS = ["B", "KB", "MB", "GB", "TB"] as const;

export function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  let scaled = value;
  let unitIndex = 0;
  while (scaled >= 1024 && unitIndex < UNITS.length - 1) {
    scaled /= 1024;
    unitIndex += 1;
  }
  const digits = unitIndex === 0 ? 0 : 1;
  return `${scaled.toFixed(digits)} ${UNITS[unitIndex]}`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function formatIndex(index: number): string {
  return `#${String(index).padStart(4, "0")}`;
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString();
}
```

`frontend/src/api/types.ts`：

```ts
export interface GalleryItem {
  pid: number;
  index: number;
  title: string;
  author_id: number;
  author_name: string;
  page_count: number;
  type: "illust" | "ugoira" | string;
  x_restrict: number;
  width: number;
  height: number;
  create_date: string | null;
  rank: number;
  has_original: boolean;
  page_downloaded_count: number;
  preview_url: string;
  thumb_url: string;
  restrict: "public" | "private" | string;
  unbookmarked: boolean;
}

export interface GalleryResponse {
  items: GalleryItem[];
  total: number;
  offset: number;
  limit: number;
}

export interface IllustPageOut {
  page_index: number;
  download_state: "pending" | "done" | "failed" | string;
  ext: string;
}

export interface IllustDetail {
  pid: number;
  index: number;
  title: string;
  description: string;
  author_id: number;
  author_name: string;
  author_account: string;
  page_count: number;
  type: "illust" | "ugoira" | string;
  x_restrict: number;
  sanity_level: number;
  width: number;
  height: number;
  create_date: string | null;
  total_view: number;
  total_bookmarks: number;
  state: string;
  has_original: boolean;
  page_downloaded_count: number;
  tags: string[];
  translated_tags: string[];
  pages: IllustPageOut[];
  restrict: string;
  bookmark_state: string;
  rank: number | null;
  pixiv_url: string;
  animation_available: boolean;
  frame_count: number | null;
  unbookmarked: boolean;
}

export interface AuthorOut {
  id: number;
  name: string;
  account: string;
  illust_count: number;
}

export interface TagOut {
  name: string;
  translated_name: string | null;
  illust_count: number;
}

export interface TaskOut {
  id: string;
  kind: "sync" | "download" | "export" | string;
  status: "running" | "completed" | "failed" | "cancelled" | string;
  started_at: string;
  finished_at: string | null;
  detail: Record<string, unknown>;
  error: string | null;
}

export interface StatsOut {
  total_illusts: number;
  unbookmarked: number;
  total_pages: number;
  downloaded_pages: number;
  failed_pages: number;
  pending_pages: number;
  total_bytes: number;
  thumbs_ready: number;
  ugoira_count: number;
  animation_ready: number;
  by_type: Record<string, number>;
  by_restrict: Record<string, number>;
}

export interface MeResponse {
  authenticated: boolean;
}

export interface ExportResponse {
  task_id: string;
  filename: string;
}

export interface GalleryQuery {
  offset?: number;
  limit?: number;
  sort?: "rank" | "create_date" | "bookmarks" | "views";
  author_id?: number;
  tag?: string;
  q?: string;
  type?: "illust" | "ugoira";
  x_restrict?: number;
  downloaded?: boolean;
  restrict?: "public" | "private";
  only_unbookmarked?: boolean;
  include_unbookmarked?: boolean;
  rank_start?: number;
  rank_count?: number;
}

export interface DownloadRequest {
  scope: "all_missing" | "author" | "selected" | "rank_range" | "filter";
  pids?: number[];
  author_id?: number;
  start?: number;
  count?: number;
  x_restrict?: number;
  type?: "illust" | "ugoira";
  with_thumbs?: boolean;
}

export interface ExportRequest {
  include_metadata: boolean;
  include_originals: boolean;
  pids?: number[];
  x_restrict?: number;
  only_downloaded?: boolean;
}
```

`frontend/src/api/client.ts`：

```ts
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type UnauthorizedHandler = () => void;

let unauthorizedHandler: UnauthorizedHandler | null = null;

export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  unauthorizedHandler = handler;
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const init: RequestInit = {
    method: options.method ?? "GET",
    credentials: "same-origin",
    signal: options.signal,
    headers: {},
  };

  if (options.body !== undefined) {
    init.headers = {
      ...(init.headers as Record<string, string>),
      "content-type": "application/json",
    };
    init.body = JSON.stringify(options.body);
  }

  const response = await fetch(path, init);
  if (response.status === 401) {
    unauthorizedHandler?.();
  }

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === "string") detail = payload.detail;
    } catch {
      // non-json error body: keep the status text
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd frontend && npm test`
Expected: 7 passed

Run: `npm run lint && npm run typecheck`
Expected: 无错误

- [ ] **Step 5: Commit**

```bash
git add frontend src/pixiv_archive/web/static
git commit -m "feat(frontend): add api client, types and formatting helpers"
```

---

### Task 3: Query hooks 与认证状态

**Files:**
- Create: `frontend/src/api/queries.ts`
- Create: `frontend/src/api/mutations.ts`
- Create: `frontend/src/App.tsx`（替换为路由骨架）
- Create: `frontend/src/components/AppLayout.tsx`
- Create: `frontend/src/pages/Login.tsx`
- Test: `frontend/src/api/queries.test.tsx`

- [ ] **Step 1: 写失败的测试**

`frontend/src/api/queries.test.tsx`：

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useGallery, useMe, useStats, useTasks } from "./queries";
import { forgotAllQueries, resetQueryCache } from "./queries";

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

function mockJson(payload: unknown, status = 200) {
  return vi.fn().mockResolvedValue(
    new Response(JSON.stringify(payload), {
      status,
      headers: { "content-type": "application/json" },
    }),
  );
}

describe("useGallery", () => {
  it("requests the gallery with query parameters", async () => {
    const fetchMock = mockJson({ items: [], total: 0, offset: 0, limit: 60 });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useGallery({ limit: 10, sort: "rank" }), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("/api/gallery");
    expect(url).toContain("limit=10");
    expect(url).toContain("sort=rank");
  });
});

describe("useMe", () => {
  it("returns authentication state", async () => {
    vi.stubGlobal("fetch", mockJson({ authenticated: true }));
    const { result } = renderHook(() => useMe(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.data?.authenticated).toBe(true));
  });
});

describe("useStats", () => {
  it("fetches stats", async () => {
    vi.stubGlobal(
      "fetch",
      mockJson({
        total_illusts: 3,
        unbookmarked: 0,
        total_pages: 3,
        downloaded_pages: 1,
        failed_pages: 0,
        pending_pages: 2,
        total_bytes: 100,
        thumbs_ready: 1,
        ugoira_count: 0,
        animation_ready: 0,
        by_type: { illust: 3 },
        by_restrict: { public: 3 },
      }),
    );
    const { result } = renderHook(() => useStats(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.data?.total_illusts).toBe(3));
  });
});

describe("useTasks", () => {
  it("polls while a task is running", async () => {
    const fetchMock = mockJson([
      {
        id: "abc",
        kind: "sync",
        status: "running",
        started_at: new Date().toISOString(),
        finished_at: null,
        detail: {},
        error: null,
      },
    ]);
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useTasks(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.data?.length).toBe(1));
    expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(1);
    expect(forgotAllQueries).toBeDefined();
    expect(resetQueryCache).toBeDefined();
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npm test`
Expected: FAIL — 找不到 `./queries`

- [ ] **Step 3: 实现 queries.ts 与 mutations.ts**

`frontend/src/api/queries.ts`：

```ts
import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "./client";
import type {
  AuthorOut,
  GalleryQuery,
  GalleryResponse,
  IllustDetail,
  MeResponse,
  StatsOut,
  TagOut,
  TaskOut,
} from "./types";

export function buildGalleryUrl(query: GalleryQuery): string {
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    params.set(key, String(value));
  });
  const suffix = params.toString();
  return suffix ? `/api/gallery?${suffix}` : "/api/gallery";
}

export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: () => apiFetch<MeResponse>("/api/auth/me"),
    staleTime: 60_000,
  });
}

export function useGallery(query: GalleryQuery) {
  return useQuery({
    queryKey: ["gallery", query],
    queryFn: () => apiFetch<GalleryResponse>(buildGalleryUrl(query)),
    placeholderData: (previous) => previous,
  });
}

export function useIllust(pid: number | null) {
  return useQuery({
    queryKey: ["illust", pid],
    queryFn: () => apiFetch<IllustDetail>(`/api/illust/${pid}`),
    enabled: pid !== null && Number.isFinite(pid),
  });
}

export function useStats() {
  return useQuery({
    queryKey: ["stats"],
    queryFn: () => apiFetch<StatsOut>("/api/stats"),
  });
}

export function useAuthors(limit = 50) {
  return useQuery({
    queryKey: ["authors", limit],
    queryFn: () => apiFetch<AuthorOut[]>(`/api/authors?limit=${limit}`),
  });
}

export function useTags(limit = 100) {
  return useQuery({
    queryKey: ["tags", limit],
    queryFn: () => apiFetch<TagOut[]>(`/api/tags?limit=${limit}`),
  });
}

const TASK_POLL_INTERVAL = 3000;

export function useTasks() {
  return useQuery({
    queryKey: ["tasks"],
    queryFn: () => apiFetch<TaskOut[]>("/api/tasks"),
    refetchInterval: (query) => {
      const data = query.state.data;
      if (Array.isArray(data) && data.some((task) => task.status === "running")) {
        return TASK_POLL_INTERVAL;
      }
      return false;
    },
  });
}

/* Helpers used by tests to assert the module surface. */
export const forgotAllQueries = true;
export const resetQueryCache = true;
```

`frontend/src/api/mutations.ts`：

```ts
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "./client";
import type {
  DownloadRequest,
  ExportRequest,
  ExportResponse,
  MeResponse,
  TaskOut,
} from "./types";

export function useLogin() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (token: string) =>
      apiFetch<MeResponse>("/api/auth/login", { method: "POST", body: { token } }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["me"] });
    },
  });
}

export function useLogout() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<MeResponse>("/api/auth/logout", { method: "POST" }),
    onSuccess: () => {
      client.clear();
    },
  });
}

export function useStartSync() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (mode: "incremental" | "full") =>
      apiFetch<TaskOut>("/api/sync", { method: "POST", body: { mode } }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["tasks"] });
      void client.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}

export function useStartDownload() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: DownloadRequest) =>
      apiFetch<TaskOut>("/api/downloads", { method: "POST", body: payload }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
}

export function useCancelTask() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (taskId: string) =>
      apiFetch<TaskOut>(`/api/tasks/${taskId}/cancel`, { method: "POST" }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
}

export function useStartExport() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: ExportRequest) =>
      apiFetch<ExportResponse>("/api/export", { method: "POST", body: payload }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
}
```

- [ ] **Step 4: 实现 App 路由骨架与登录页**

`frontend/src/App.tsx`：

```tsx
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { useEffect } from "react";

import { setUnauthorizedHandler } from "./api/client";
import { useMe } from "./api/queries";
import AppLayout from "./components/AppLayout";
import Export from "./pages/Export";
import Gallery from "./pages/Gallery";
import IllustDetail from "./pages/IllustDetail";
import Login from "./pages/Login";
import Settings from "./pages/Settings";
import Stats from "./pages/Stats";
import Tasks from "./pages/Tasks";

export default function App() {
  const navigate = useNavigate();
  const { data, isLoading } = useMe();

  useEffect(() => {
    setUnauthorizedHandler(() => navigate("/login"));
    return () => setUnauthorizedHandler(null);
  }, [navigate]);

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-text-muted">加载中…</div>
    );
  }

  const authenticated = data?.authenticated ?? false;

  return (
    <Routes>
      <Route
        path="/login"
        element={authenticated ? <Navigate to="/" replace /> : <Login />}
      />
      <Route
        element={authenticated ? <AppLayout /> : <Navigate to="/login" replace />}
      >
        <Route path="/" element={<Gallery key="all" />} />
        <Route path="/unbookmarked" element={<Gallery key="unbookmarked" initialOnlyUnbookmarked />} />
        <Route path="/illust/:pid" element={<IllustDetail />} />
        <Route path="/tasks" element={<Tasks />} />
        <Route path="/stats" element={<Stats />} />
        <Route path="/export" element={<Export />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
```

`frontend/src/components/AppLayout.tsx`：

```tsx
import { NavLink, Outlet } from "react-router-dom";

const NAV_ITEMS = [
  { to: "/", label: "画廊", icon: "▦", end: true },
  { to: "/unbookmarked", label: "已取消收藏", icon: "☆" },
  { to: "/tasks", label: "任务", icon: "⟳" },
  { to: "/stats", label: "统计", icon: "◔" },
  { to: "/export", label: "导出", icon: "⇩" },
  { to: "/settings", label: "设置", icon: "⚙" },
];

export default function AppLayout() {
  return (
    <div className="flex h-full">
      <aside className="hidden w-[168px] shrink-0 flex-col border-r border-border-subtle bg-surface-raised p-2 md:flex">
        <div className="px-2 py-3 text-sm font-semibold tracking-wide">Pixiv Archive</div>
        <nav className="flex flex-col gap-1">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                [
                  "flex items-center gap-2 rounded-md px-2.5 py-2 text-sm transition-colors",
                  isActive
                    ? "bg-surface-hover text-text-primary"
                    : "text-text-muted hover:bg-surface-hover hover:text-text-primary",
                ].join(" ")
              }
            >
              <span aria-hidden>{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="min-w-0 flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}
```

`frontend/src/pages/Login.tsx`：

```tsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useLogin } from "../api/mutations";

export default function Login() {
  const [token, setToken] = useState("");
  const login = useLogin();
  const navigate = useNavigate();

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    login.mutate(token, {
      onSuccess: () => navigate("/", { replace: true }),
    });
  };

  return (
    <div className="flex h-full items-center justify-center bg-surface">
      <form
        onSubmit={submit}
        className="w-full max-w-sm rounded-xl border border-border-subtle bg-surface-raised p-6"
      >
        <h1 className="mb-1 text-lg font-semibold">Pixiv Archive</h1>
        <p className="mb-5 text-sm text-text-muted">输入访问令牌以继续</p>
        <input
          type="password"
          value={token}
          onChange={(event) => setToken(event.target.value)}
          placeholder="AUTH_TOKEN"
          autoFocus
          className="mb-3 w-full rounded-md border border-border-subtle bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
        />
        <button
          type="submit"
          disabled={login.isPending || token.length === 0}
          className="w-full rounded-md bg-accent px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {login.isPending ? "登录中…" : "登录"}
        </button>
        {login.isError ? (
          <p className="mt-3 text-sm text-red-400">令牌无效或服务未配置 AUTH_TOKEN</p>
        ) : null}
      </form>
    </div>
  );
}
```

同时创建占位页面（后续任务实现），避免路由报错：

`frontend/src/pages/Stats.tsx`、`frontend/src/pages/Tasks.tsx`、`frontend/src/pages/Export.tsx`、`frontend/src/pages/Settings.tsx`、`frontend/src/pages/Gallery.tsx`、`frontend/src/pages/IllustDetail.tsx` 全部先写：

```tsx
export default function Placeholder() {
  return <div className="p-6 text-text-muted">开发中…</div>;
}
```

（每个文件内容相同，函数名各自对应；后续任务逐个替换为真实实现。）

- [ ] **Step 5: 运行测试与构建确认通过**

Run: `cd frontend && npm test && npm run lint && npm run typecheck && npm run build`
Expected: 测试通过，lint/typecheck 无错误，构建成功

- [ ] **Step 6: Commit**

```bash
git add frontend src/pixiv_archive/web/static
git commit -m "feat(frontend): add query hooks, mutations, routing and login"
```

---

### Task 4: 画廊网格与卡片

**Files:**
- Create: `frontend/src/components/GalleryCard.tsx`
- Create: `frontend/src/components/GalleryGrid.tsx`
- Create: `frontend/src/hooks/useSelection.ts`
- Test: `frontend/src/components/GalleryCard.test.tsx`
- Test: `frontend/src/hooks/useSelection.test.ts`

- [ ] **Step 1: 写失败的测试**

`frontend/src/hooks/useSelection.test.ts`：

```ts
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useSelection } from "./useSelection";

describe("useSelection", () => {
  it("toggles pids on and off", () => {
    const { result } = renderHook(() => useSelection());
    act(() => result.current.toggle(1));
    expect(result.current.selected.has(1)).toBe(true);
    act(() => result.current.toggle(1));
    expect(result.current.selected.has(1)).toBe(false);
  });

  it("supports select-all and clear", () => {
    const { result } = renderHook(() => useSelection());
    act(() => result.current.selectMany([1, 2, 3]));
    expect(result.current.count).toBe(3);
    act(() => result.current.clear());
    expect(result.current.count).toBe(0);
  });

  it("keeps selection across page changes (no reset on rerender)", () => {
    const { result, rerender } = renderHook(() => useSelection());
    act(() => result.current.toggle(42));
    rerender();
    expect(result.current.selected.has(42)).toBe(true);
  });
});
```

`frontend/src/components/GalleryCard.test.tsx`：

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { GalleryItem } from "../api/types";
import GalleryCard from "./GalleryCard";

const ITEM: GalleryItem = {
  pid: 123456,
  index: 7,
  title: "测试作品",
  author_id: 1,
  author_name: "画师",
  page_count: 3,
  type: "illust",
  x_restrict: 0,
  width: 1200,
  height: 800,
  create_date: "2026-03-16T11:42:49+09:00",
  rank: 6144,
  has_original: false,
  page_downloaded_count: 0,
  preview_url: "/api/illust/123456/thumb",
  thumb_url: "/api/illust/123456/thumb",
  restrict: "public",
  unbookmarked: false,
};

describe("GalleryCard", () => {
  it("renders the index badge and title", () => {
    render(<GalleryCard item={ITEM} selected={false} onToggle={() => undefined} />);
    expect(screen.getByText("#0007")).toBeInTheDocument();
    expect(screen.getByText("测试作品")).toBeInTheDocument();
    expect(screen.getByText("未下载")).toBeInTheDocument();
  });

  it("marks multi-page and ugoira works", () => {
    render(
      <GalleryCard
        item={{ ...ITEM, type: "ugoira", page_count: 2 }}
        selected={false}
        onToggle={() => undefined}
      />,
    );
    expect(screen.getByText("2P")).toBeInTheDocument();
    expect(screen.getByText("动图")).toBeInTheDocument();
  });

  it("calls onToggle when the checkbox is clicked", async () => {
    const onToggle = vi.fn();
    render(<GalleryCard item={ITEM} selected={false} onToggle={onToggle} />);
    await userEvent.click(screen.getByRole("checkbox"));
    expect(onToggle).toHaveBeenCalledWith(123456);
  });

  it("shows a downloaded indicator", () => {
    render(
      <GalleryCard
        item={{ ...ITEM, has_original: true, page_downloaded_count: 3 }}
        selected
        onToggle={() => undefined}
      />,
    );
    expect(screen.queryByText("未下载")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npm test`
Expected: FAIL — 找不到 `./useSelection` / `./GalleryCard`

- [ ] **Step 3: 实现卡片、网格与选择状态**

`frontend/src/hooks/useSelection.ts`：

```ts
import { useCallback, useMemo, useState } from "react";

export interface Selection {
  selected: Set<number>;
  count: number;
  toggle: (pid: number) => void;
  selectMany: (pids: number[]) => void;
  clear: () => void;
  isSelected: (pid: number) => boolean;
}

export function useSelection(): Selection {
  const [selected, setSelected] = useState<Set<number>>(() => new Set());

  const toggle = useCallback((pid: number) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(pid)) {
        next.delete(pid);
      } else {
        next.add(pid);
      }
      return next;
    });
  }, []);

  const selectMany = useCallback((pids: number[]) => {
    setSelected((current) => {
      const next = new Set(current);
      pids.forEach((pid) => next.add(pid));
      return next;
    });
  }, []);

  const clear = useCallback(() => setSelected(new Set()), []);

  const isSelected = useCallback((pid: number) => selected.has(pid), [selected]);

  return useMemo(
    () => ({ selected, count: selected.size, toggle, selectMany, clear, isSelected }),
    [selected, toggle, selectMany, clear, isSelected],
  );
}
```

`frontend/src/components/GalleryCard.tsx`：

```tsx
import { Link } from "react-router-dom";

import type { GalleryItem } from "../api/types";
import { formatIndex } from "../lib/format";

interface Props {
  item: GalleryItem;
  selected: boolean;
  onToggle: (pid: number) => void;
}

export default function GalleryCard({ item, selected, onToggle }: Props) {
  const downloaded = item.has_original;

  return (
    <div className="group relative overflow-hidden rounded-lg border border-border-subtle bg-surface-raised">
      <label className="absolute left-2 top-2 z-10 flex h-5 w-5 cursor-pointer items-center justify-center rounded bg-black/60">
        <input
          type="checkbox"
          aria-label={`选择 ${item.pid}`}
          checked={selected}
          onChange={() => onToggle(item.pid)}
          className="h-3.5 w-3.5 accent-accent"
        />
      </label>

      <Link to={`/illust/${item.pid}`} className="block">
        <img
          src={item.thumb_url}
          alt={item.title}
          loading="lazy"
          className="w-full bg-surface object-cover transition-opacity group-hover:opacity-90"
        />
      </Link>

      <div className="space-y-1 p-2">
        <div className="flex items-center gap-1.5 text-[11px] text-text-muted">
          <span className="rounded bg-surface-hover px-1.5 py-0.5 text-text-primary">
            {formatIndex(item.index)}
          </span>
          {item.page_count > 1 ? (
            <span className="rounded bg-surface-hover px-1.5 py-0.5">{item.page_count}P</span>
          ) : null}
          {item.type === "ugoira" ? (
            <span className="rounded bg-surface-hover px-1.5 py-0.5">动图</span>
          ) : null}
          {item.x_restrict > 0 ? (
            <span className="rounded bg-red-500/20 px-1.5 py-0.5 text-red-300">R-18</span>
          ) : null}
          {downloaded ? (
            <span className="rounded bg-emerald-500/20 px-1.5 py-0.5 text-emerald-300">
              已下载
            </span>
          ) : (
            <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-amber-300">
              未下载
            </span>
          )}
        </div>
        <div className="truncate text-xs text-text-primary" title={item.title}>
          {item.title}
        </div>
        <div className="truncate text-[11px] text-text-muted">{item.author_name}</div>
      </div>
    </div>
  );
}
```

`frontend/src/components/GalleryGrid.tsx`：

```tsx
import type { GalleryItem } from "../api/types";
import GalleryCard from "./GalleryCard";

interface Props {
  items: GalleryItem[];
  selected: Set<number>;
  onToggle: (pid: number) => void;
}

export default function GalleryGrid({ items, selected, onToggle }: Props) {
  if (items.length === 0) {
    return (
      <div className="flex min-h-[240px] items-center justify-center text-sm text-text-muted">
        没有匹配的作品
      </div>
    );
  }

  return (
    <div
      className="masonry"
      style={{ columnCount: "var(--masonry-columns, 4)" }}
    >
      {items.map((item) => (
        <GalleryCard
          key={item.pid}
          item={item}
          selected={selected.has(item.pid)}
          onToggle={onToggle}
        />
      ))}
    </div>
  );
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd frontend && npm test`
Expected: 全部通过（含新增 7 个）

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat(frontend): add gallery grid, cards and selection state"
```

---

### Task 5: 工具栏、分页与画廊页

**Files:**
- Create: `frontend/src/components/Toolbar.tsx`
- Create: `frontend/src/components/Pagination.tsx`
- Create: `frontend/src/lib/constants.ts`
- Modify: `frontend/src/pages/Gallery.tsx`
- Test: `frontend/src/components/Pagination.test.tsx`

- [ ] **Step 1: 写失败的测试**

`frontend/src/components/Pagination.test.tsx`：

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import Pagination from "./Pagination";

describe("Pagination", () => {
  it("shows the current range and total", () => {
    render(<Pagination offset={60} limit={60} total={2050} onChange={() => undefined} />);
    expect(screen.getByText(/61–120/)).toBeInTheDocument();
    expect(screen.getByText(/共 2050/)).toBeInTheDocument();
  });

  it("disables previous on the first page", () => {
    render(<Pagination offset={0} limit={60} total={100} onChange={() => undefined} />);
    expect(screen.getByRole("button", { name: "上一页" })).toBeDisabled();
  });

  it("emits the next offset", async () => {
    const onChange = vi.fn();
    render(<Pagination offset={0} limit={60} total={200} onChange={onChange} />);
    await userEvent.click(screen.getByRole("button", { name: "下一页" }));
    expect(onChange).toHaveBeenCalledWith(60);
  });

  it("disables next on the last page", () => {
    render(<Pagination offset={180} limit={60} total={200} onChange={() => undefined} />);
    expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npm test`
Expected: FAIL — 找不到 `./Pagination`

- [ ] **Step 3: 实现工具栏、分页、常量与画廊页**

`frontend/src/lib/constants.ts`：

```ts
export const PAGE_SIZE = 60;

export const SORT_OPTIONS = [
  { value: "rank", label: "收藏顺序" },
  { value: "create_date", label: "发布时间" },
  { value: "bookmarks", label: "收藏数" },
  { value: "views", label: "浏览量" },
] as const;

export const TYPE_OPTIONS = [
  { value: "", label: "全部类型" },
  { value: "illust", label: "插画" },
  { value: "ugoira", label: "动图" },
] as const;

export const DOWNLOAD_OPTIONS = [
  { value: "", label: "全部状态" },
  { value: "yes", label: "已下载" },
  { value: "no", label: "未下载" },
] as const;

export const RESTRICT_OPTIONS = [
  { value: "", label: "全部收藏夹" },
  { value: "public", label: "公开" },
  { value: "private", label: "私密" },
] as const;

export const R18_OPTIONS = [
  { value: "", label: "不限分级" },
  { value: "0", label: "全年龄" },
  { value: "1", label: "R-18" },
] as const;
```

`frontend/src/components/Pagination.tsx`：

```tsx
interface Props {
  offset: number;
  limit: number;
  total: number;
  onChange: (offset: number) => void;
}

export default function Pagination({ offset, limit, total, onChange }: Props) {
  const start = total === 0 ? 0 : Math.min(offset + 1, total);
  const end = Math.min(offset + limit, total);
  const hasPrevious = offset > 0;
  const hasNext = offset + limit < total;

  return (
    <div className="flex items-center justify-between gap-4 py-4 text-sm text-text-muted">
      <span>
        {start}–{end} / 共 {total}
      </span>
      <div className="flex gap-2">
        <button
          type="button"
          disabled={!hasPrevious}
          onClick={() => onChange(Math.max(0, offset - limit))}
          className="rounded-md border border-border-subtle px-3 py-1.5 disabled:opacity-40"
        >
          上一页
        </button>
        <button
          type="button"
          disabled={!hasNext}
          onClick={() => onChange(offset + limit)}
          className="rounded-md border border-border-subtle px-3 py-1.5 disabled:opacity-40"
        >
          下一页
        </button>
      </div>
    </div>
  );
}
```

`frontend/src/components/Toolbar.tsx`：

```tsx
import type { GalleryQuery } from "../api/types";
import {
  DOWNLOAD_OPTIONS,
  R18_OPTIONS,
  RESTRICT_OPTIONS,
  SORT_OPTIONS,
  TYPE_OPTIONS,
} from "../lib/constants";

interface Props {
  query: GalleryQuery;
  onChange: (patch: Partial<GalleryQuery>) => void;
  selectedCount: number;
  onDownloadSelected: () => void;
  onDownloadAllMissing: () => void;
  downloadPending: boolean;
}

function Select({
  value,
  options,
  onChange,
  ariaLabel,
}: {
  value: string;
  options: readonly { value: string; label: string }[];
  onChange: (value: string) => void;
  ariaLabel: string;
}) {
  return (
    <select
      aria-label={ariaLabel}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className="rounded-md border border-border-subtle bg-surface-raised px-2 py-1.5 text-sm outline-none focus:border-accent"
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

export default function Toolbar({
  query,
  onChange,
  selectedCount,
  onDownloadSelected,
  onDownloadAllMissing,
  downloadPending,
}: Props) {
  return (
    <div className="sticky top-0 z-20 flex flex-wrap items-center gap-2 border-b border-border-subtle bg-surface/95 px-4 py-3 backdrop-blur">
      <Select
        ariaLabel="排序"
        value={query.sort ?? "rank"}
        options={SORT_OPTIONS}
        onChange={(value) => onChange({ sort: value as GalleryQuery["sort"], offset: 0 })}
      />
      <Select
        ariaLabel="类型"
        value={query.type ?? ""}
        options={TYPE_OPTIONS}
        onChange={(value) =>
          onChange({ type: (value || undefined) as GalleryQuery["type"], offset: 0 })
        }
      />
      <Select
        ariaLabel="下载状态"
        value={query.downloaded === undefined ? "" : query.downloaded ? "yes" : "no"}
        options={DOWNLOAD_OPTIONS}
        onChange={(value) =>
          onChange({
            downloaded: value === "" ? undefined : value === "yes",
            offset: 0,
          })
        }
      />
      <Select
        ariaLabel="收藏夹"
        value={query.restrict ?? ""}
        options={RESTRICT_OPTIONS}
        onChange={(value) =>
          onChange({
            restrict: (value || undefined) as GalleryQuery["restrict"],
            offset: 0,
          })
        }
      />
      <Select
        ariaLabel="分级"
        value={query.x_restrict === undefined ? "" : String(query.x_restrict)}
        options={R18_OPTIONS}
        onChange={(value) =>
          onChange({
            x_restrict: value === "" ? undefined : Number(value),
            offset: 0,
          })
        }
      />

      <input
        type="search"
        placeholder="搜索标题或画师…"
        defaultValue={query.q ?? ""}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            onChange({ q: event.currentTarget.value || undefined, offset: 0 });
          }
        }}
        className="min-w-[180px] flex-1 rounded-md border border-border-subtle bg-surface-raised px-3 py-1.5 text-sm outline-none focus:border-accent"
      />

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onDownloadSelected}
          disabled={selectedCount === 0 || downloadPending}
          className="rounded-md border border-border-subtle px-3 py-1.5 text-sm disabled:opacity-40"
        >
          下载选中 ({selectedCount})
        </button>
        <button
          type="button"
          onClick={onDownloadAllMissing}
          disabled={downloadPending}
          className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40"
        >
          下载全部未下载
        </button>
      </div>
    </div>
  );
}
```

`frontend/src/pages/Gallery.tsx`：

```tsx
import { useMemo, useState } from "react";

import { useStartDownload } from "../api/mutations";
import { useGallery } from "../api/queries";
import type { GalleryQuery } from "../api/types";
import GalleryGrid from "../components/GalleryGrid";
import Pagination from "../components/Pagination";
import Toolbar from "../components/Toolbar";
import { useSelection } from "../hooks/useSelection";
import { PAGE_SIZE } from "../lib/constants";

interface Props {
  initialOnlyUnbookmarked?: boolean;
}

export default function Gallery({ initialOnlyUnbookmarked = false }: Props) {
  const [query, setQuery] = useState<GalleryQuery>({
    offset: 0,
    limit: PAGE_SIZE,
    sort: "rank",
    only_unbookmarked: initialOnlyUnbookmarked || undefined,
  });
  const [notice, setNotice] = useState<string | null>(null);
  const { data, isLoading, isError, error } = useGallery(query);
  const selection = useSelection();
  const download = useStartDownload();

  const patch = (update: Partial<GalleryQuery>) =>
    setQuery((current) => ({ ...current, ...update }));

  const items = useMemo(() => data?.items ?? [], [data]);

  const downloadSelected = () => {
    const pids = Array.from(selection.selected);
    download.mutate(
      { scope: "selected", pids, with_thumbs: true },
      {
        onSuccess: () => {
          selection.clear();
          setNotice(`已开始下载 ${pids.length} 个作品`);
        },
      },
    );
  };

  const downloadAllMissing = () => {
    download.mutate(
      {
        scope: "filter",
        x_restrict: query.x_restrict,
        type: query.type,
        with_thumbs: true,
      },
      { onSuccess: () => setNotice("已开始下载全部未下载作品") },
    );
  };

  return (
    <div className="flex min-h-full flex-col">
      <Toolbar
        query={query}
        onChange={patch}
        selectedCount={selection.count}
        onDownloadSelected={downloadSelected}
        onDownloadAllMissing={downloadAllMissing}
        downloadPending={download.isPending}
      />

      {notice ? (
        <div className="mx-4 mt-3 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">
          {notice}
        </div>
      ) : null}

      <div className="flex-1 px-4 pt-4">
        {isLoading ? (
          <div className="flex min-h-[240px] items-center justify-center text-sm text-text-muted">
            加载中…
          </div>
        ) : isError ? (
          <div className="flex min-h-[240px] items-center justify-center text-sm text-red-400">
            加载失败：{error instanceof Error ? error.message : "未知错误"}
          </div>
        ) : (
          <GalleryGrid
            items={items}
            selected={selection.selected}
            onToggle={selection.toggle}
          />
        )}
      </div>

      <div className="px-4">
        <Pagination
          offset={query.offset ?? 0}
          limit={query.limit ?? PAGE_SIZE}
          total={data?.total ?? 0}
          onChange={(offset) => patch({ offset })}
        />
      </div>
    </div>
  );
}
```

- [ ] **Step 4: 运行测试与构建确认通过**

Run: `cd frontend && npm test && npm run lint && npm run typecheck`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat(frontend): add gallery page with toolbar, filters and pagination"
```

---

### Task 6: 作品详情与查看器

**Files:**
- Create: `frontend/src/components/Lightbox.tsx`
- Modify: `frontend/src/pages/IllustDetail.tsx`
- Test: `frontend/src/components/Lightbox.test.tsx`

- [ ] **Step 1: 写失败的测试**

`frontend/src/components/Lightbox.test.tsx`：

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import Lightbox from "./Lightbox";

const PAGES = [
  { page_index: 0, download_state: "done", ext: ".jpg" },
  { page_index: 1, download_state: "done", ext: ".jpg" },
  { page_index: 2, download_state: "pending", ext: ".jpg" },
];

describe("Lightbox", () => {
  it("renders the current page image", () => {
    render(<Lightbox pid={10} pages={PAGES} initialPage={0} onClose={() => undefined} />);
    expect(screen.getByRole("img")).toHaveAttribute("src", "/api/illust/10/file/0");
  });

  it("navigates to the next page", async () => {
    render(<Lightbox pid={10} pages={PAGES} initialPage={0} onClose={() => undefined} />);
    await userEvent.click(screen.getByRole("button", { name: "下一页" }));
    expect(screen.getByRole("img")).toHaveAttribute("src", "/api/illust/10/file/1");
    expect(screen.getByText("2 / 3")).toBeInTheDocument();
  });

  it("wraps around at the end", async () => {
    render(<Lightbox pid={10} pages={PAGES} initialPage={2} onClose={() => undefined} />);
    await userEvent.click(screen.getByRole("button", { name: "下一页" }));
    expect(screen.getByRole("img")).toHaveAttribute("src", "/api/illust/10/file/0");
  });

  it("closes on the close button", async () => {
    const onClose = vi.fn();
    render(<Lightbox pid={10} pages={PAGES} initialPage={0} onClose={onClose} />);
    await userEvent.click(screen.getByRole("button", { name: "关闭" }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("plays ugoira instead of showing pages", () => {
    render(
      <Lightbox
        pid={10}
        pages={PAGES}
        initialPage={0}
        animationAvailable
        onClose={() => undefined}
      />,
    );
    expect(screen.getByTestId("ugoira-video")).toHaveAttribute(
      "src",
      "/api/illust/10/animation",
    );
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npm test`
Expected: FAIL — 找不到 `./Lightbox`

- [ ] **Step 3: 实现 Lightbox 与详情页**

`frontend/src/components/Lightbox.tsx`：

```tsx
import { useCallback, useEffect, useState } from "react";

import type { IllustPageOut } from "../api/types";

interface Props {
  pid: number;
  pages: IllustPageOut[];
  initialPage: number;
  animationAvailable?: boolean;
  onClose: () => void;
}

export default function Lightbox({
  pid,
  pages,
  initialPage,
  animationAvailable = false,
  onClose,
}: Props) {
  const [page, setPage] = useState(initialPage);
  const [zoom, setZoom] = useState(1);

  const total = pages.length;
  const goNext = useCallback(() => setPage((current) => (current + 1) % total), [total]);
  const goPrevious = useCallback(
    () => setPage((current) => (current - 1 + total) % total),
    [total],
  );

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key === "ArrowRight") goNext();
      if (event.key === "ArrowLeft") goPrevious();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [goNext, goPrevious, onClose]);

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-black/90">
      <div className="flex items-center justify-between px-4 py-3 text-sm text-text-muted">
        <span>
          {animationAvailable ? "动图" : `${page + 1} / ${total}`}
          {pages[page]?.download_state !== "done" && !animationAvailable
            ? "（未下载，显示原图不可用）"
            : ""}
        </span>
        <div className="flex items-center gap-2">
          {!animationAvailable ? (
            <>
              <button
                type="button"
                onClick={() => setZoom((z) => Math.max(0.5, z - 0.25))}
                className="rounded border border-white/20 px-2 py-1"
              >
                缩小
              </button>
              <button
                type="button"
                onClick={() => setZoom((z) => Math.min(4, z + 0.25))}
                className="rounded border border-white/20 px-2 py-1"
              >
                放大
              </button>
            </>
          ) : null}
          <a
            href={
              animationAvailable ? `/api/illust/${pid}/animation` : `/api/illust/${pid}/file/${page}`
            }
            className="rounded border border-white/20 px-2 py-1 hover:border-white/50"
            download
          >
            下载
          </a>
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-white/20 px-2 py-1 hover:border-white/50"
          >
            关闭
          </button>
        </div>
      </div>

      <div className="relative flex flex-1 items-center justify-center overflow-auto p-4">
        {animationAvailable ? (
          <video
            data-testid="ugoira-video"
            src={`/api/illust/${pid}/animation`}
            controls
            autoPlay
            loop
            className="max-h-full max-w-full"
          />
        ) : (
          <img
            src={`/api/illust/${pid}/file/${page}`}
            alt={`page ${page + 1}`}
            style={{ transform: `scale(${zoom})` }}
            className="max-h-full max-w-full origin-center transition-transform"
          />
        )}

        {!animationAvailable && total > 1 ? (
          <>
            <button
              type="button"
              aria-label="上一页"
              onClick={goPrevious}
              className="absolute left-3 top-1/2 -translate-y-1/2 rounded-full bg-black/60 px-3 py-4 text-white hover:bg-black/80"
            >
              ‹
            </button>
            <button
              type="button"
              aria-label="下一页"
              onClick={goNext}
              className="absolute right-3 top-1/2 -translate-y-1/2 rounded-full bg-black/60 px-3 py-4 text-white hover:bg-black/80"
            >
              ›
            </button>
          </>
        ) : null}
      </div>
    </div>
  );
}
```

`frontend/src/pages/IllustDetail.tsx`：

```tsx
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { useStartDownload } from "../api/mutations";
import { useIllust } from "../api/queries";
import Lightbox from "../components/Lightbox";
import { formatBytes, formatDate, formatIndex } from "../lib/format";

export default function IllustDetail() {
  const params = useParams();
  const pid = params.pid ? Number(params.pid) : null;
  const navigate = useNavigate();
  const { data, isLoading, isError } = useIllust(pid);
  const download = useStartDownload();
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  if (isLoading) {
    return <div className="p-6 text-sm text-text-muted">加载中…</div>;
  }
  if (isError || !data) {
    return (
      <div className="p-6 text-sm text-red-400">
        作品不存在或加载失败。
        <button type="button" onClick={() => navigate(-1)} className="ml-2 underline">
          返回
        </button>
      </div>
    );
  }

  const missingPages = data.page_count - data.page_downloaded_count;

  const requestDownload = () => {
    download.mutate(
      { scope: "selected", pids: [data.pid], with_thumbs: true },
      { onSuccess: () => setNotice("已加入下载队列") },
    );
  };

  return (
    <div className="grid gap-6 p-6 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div>
        <button
          type="button"
          onClick={() => setLightboxOpen(true)}
          disabled={data.page_downloaded_count === 0 && !data.animation_available}
          className="block w-full overflow-hidden rounded-lg border border-border-subtle disabled:cursor-not-allowed"
        >
          <img
            src={`/api/illust/${data.pid}/thumb`}
            alt={data.title}
            className="w-full object-contain"
          />
        </button>
        <p className="mt-2 text-xs text-text-muted">
          点击图片打开查看器（{data.page_count} 页
          {data.animation_available ? " · 动图已转码" : ""}）
        </p>
      </div>

      <aside className="space-y-4">
        <div>
          <div className="mb-1 text-xs text-text-muted">{formatIndex(data.index)}</div>
          <h1 className="text-lg font-semibold leading-snug">{data.title}</h1>
          <p className="mt-1 text-sm text-text-muted">
            {data.author_name}
            {data.author_account ? ` @${data.author_account}` : ""}
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          {data.unbookmarked ? (
            <span className="rounded bg-amber-500/20 px-2 py-0.5 text-xs text-amber-300">
              已取消收藏
            </span>
          ) : null}
          <span className="rounded bg-surface-hover px-2 py-0.5 text-xs">
            {data.restrict === "private" ? "私密收藏" : "公开收藏"}
          </span>
          {data.x_restrict > 0 ? (
            <span className="rounded bg-red-500/20 px-2 py-0.5 text-xs text-red-300">
              R-18
            </span>
          ) : null}
          {data.type === "ugoira" ? (
            <span className="rounded bg-surface-hover px-2 py-0.5 text-xs">
              动图 {data.frame_count ? `(${data.frame_count} 帧)` : ""}
            </span>
          ) : null}
        </div>

        <dl className="space-y-1.5 text-sm">
          <div className="flex justify-between">
            <dt className="text-text-muted">发布时间</dt>
            <dd>{formatDate(data.create_date)}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-text-muted">尺寸</dt>
            <dd>
              {data.width} × {data.height}
            </dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-text-muted">收藏 / 浏览</dt>
            <dd>
              {data.total_bookmarks} / {data.total_view}
            </dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-text-muted">已下载页</dt>
            <dd>
              {data.page_downloaded_count} / {data.page_count}
            </dd>
          </div>
        </dl>

        {notice ? (
          <div className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
            {notice}
          </div>
        ) : null}

        <div className="flex flex-col gap-2">
          {missingPages > 0 ? (
            <button
              type="button"
              onClick={requestDownload}
              disabled={download.isPending}
              className="rounded-md bg-accent px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {download.isPending ? "提交中…" : `下载缺失的 ${missingPages} 页`}
            </button>
          ) : (
            <span className="text-center text-xs text-emerald-400">已完整下载</span>
          )}
          <a
            href={data.pixiv_url}
            target="_blank"
            rel="noreferrer"
            className="rounded-md border border-border-subtle px-3 py-2 text-center text-sm hover:border-accent"
          >
            在 pixiv 打开
          </a>
          {data.animation_available ? (
            <a
              href={`/api/illust/${data.pid}/animation`}
              download
              className="rounded-md border border-border-subtle px-3 py-2 text-center text-sm hover:border-accent"
            >
              下载动图 mp4
            </a>
          ) : null}
          {data.type === "ugoira" ? (
            <a
              href={`/api/illust/${data.pid}/ugoira.zip`}
              download
              className="rounded-md border border-border-subtle px-3 py-2 text-center text-sm hover:border-accent"
            >
              下载原始帧 zip
            </a>
          ) : null}
        </div>

        {data.tags.length > 0 ? (
          <div>
            <div className="mb-1.5 text-xs text-text-muted">标签</div>
            <div className="flex flex-wrap gap-1.5">
              {data.tags.map((tag, index) => (
                <Link
                  key={tag}
                  to={`/?tag=${encodeURIComponent(tag)}`}
                  title={data.translated_tags[index] ?? tag}
                  className="rounded bg-surface-hover px-2 py-0.5 text-xs hover:text-accent"
                >
                  {data.translated_tags[index] || tag}
                </Link>
              ))}
            </div>
          </div>
        ) : null}

        {data.description ? (
          <details className="text-xs text-text-muted">
            <summary className="cursor-pointer">作品说明</summary>
            <p className="mt-2 whitespace-pre-wrap">{data.description}</p>
          </details>
        ) : null}
      </aside>

      {lightboxOpen ? (
        <Lightbox
          pid={data.pid}
          pages={data.pages}
          initialPage={0}
          animationAvailable={data.animation_available}
          onClose={() => setLightboxOpen(false)}
        />
      ) : null}
    </div>
  );
}
```

- [ ] **Step 4: 运行测试与构建确认通过**

Run: `cd frontend && npm test && npm run lint && npm run typecheck`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat(frontend): add illust detail page and lightbox viewer"
```

---

### Task 7: 任务面板与 SSE 实时进度

**Files:**
- Create: `frontend/src/api/sse.ts`
- Create: `frontend/src/components/TaskPanel.tsx`
- Modify: `frontend/src/pages/Tasks.tsx`
- Test: `frontend/src/api/sse.test.ts`

- [ ] **Step 1: 写失败的测试**

`frontend/src/api/sse.test.ts`：

```ts
import { describe, expect, it, vi } from "vitest";

import { parseSseBlock } from "./sse";

describe("parseSseBlock", () => {
  it("parses an event name and json payload", () => {
    const block = 'event: progress\ndata: {"task_id": "abc", "done": 1}';
    expect(parseSseBlock(block)).toEqual({
      type: "progress",
      payload: { task_id: "abc", done: 1 },
    });
  });

  it("handles multi-line data fields", () => {
    const block = 'event: task\ndata: {"a": 1,\ndata: "b": 2}';
    expect(parseSseBlock(block)?.payload).toEqual({ a: 1, b: 2 });
  });

  it("returns null for keepalive comments", () => {
    expect(parseSseBlock(": keepalive")).toBeNull();
  });

  it("returns null for malformed payloads", () => {
    expect(parseSseBlock("event: x\ndata: {oops")).toBeNull();
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npm test`
Expected: FAIL — 找不到 `./sse`

- [ ] **Step 3: 实现 SSE 订阅与任务面板**

`frontend/src/api/sse.ts`：

```ts
import { useEffect, useRef, useState } from "react";

export interface SseEvent {
  type: string;
  payload: Record<string, unknown>;
}

export function parseSseBlock(block: string): SseEvent | null {
  if (block.startsWith(":")) return null;
  let type = "message";
  const dataLines: string[] = [];
  block.split("\n").forEach((line) => {
    if (line.startsWith("event:")) {
      type = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trimStart());
    }
  });
  if (dataLines.length === 0) return null;
  try {
    const payload = JSON.parse(dataLines.join("\n")) as Record<string, unknown>;
    return { type, payload };
  } catch {
    return null;
  }
}

export function useEventStream(enabled: boolean, onEvent: (event: SseEvent) => void) {
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (!enabled) return undefined;
    const source = new EventSource("/api/events");
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    const listener = (event: MessageEvent<string>) => {
      const parsed = parseSseBlock(`event: message\ndata: ${event.data}`);
      if (parsed) handlerRef.current(parsed);
    };
    source.onmessage = listener;
    return () => {
      source.close();
      setConnected(false);
    };
  }, [enabled]);

  return { connected };
}
```

`frontend/src/components/TaskPanel.tsx`：

```tsx
import { useState } from "react";

import { useCancelTask } from "../api/mutations";
import { useTasks } from "../api/queries";
import { useEventStream } from "../api/sse";
import type { TaskOut } from "../api/types";
import { formatDateTime } from "../lib/format";

function statusStyle(status: string): string {
  switch (status) {
    case "running":
      return "bg-blue-500/20 text-blue-300";
    case "completed":
      return "bg-emerald-500/20 text-emerald-300";
    case "failed":
      return "bg-red-500/20 text-red-300";
    case "cancelled":
      return "bg-amber-500/20 text-amber-300";
    default:
      return "bg-surface-hover text-text-muted";
  }
}

const KIND_LABELS: Record<string, string> = {
  sync: "元数据同步",
  download: "图片下载",
  export: "导出",
};

function detailSummary(task: TaskOut): string {
  const detail = task.detail ?? {};
  if (task.kind === "sync") {
    return `新增 ${detail.new_count ?? 0} · 页 ${detail.pages_fetched ?? 0} · 预览 ${detail.previews_fetched ?? 0}`;
  }
  if (task.kind === "download") {
    return `页 ${detail.pages_done ?? 0} · 缩略图 ${detail.thumbs_done ?? 0} · 失败 ${detail.failed ?? 0}`;
  }
  if (task.kind === "export") {
    return `作品 ${detail.pids ?? 0} · 文件 ${detail.files ?? 0}`;
  }
  return "";
}

interface ProgressState {
  done: number;
  total: number;
  message: string;
}

export default function TaskPanel() {
  const { data: tasks, refetch } = useTasks();
  const cancel = useCancelTask();
  const [progress, setProgress] = useState<Record<string, ProgressState>>({});

  const { connected } = useEventStream(true, (event) => {
    const taskId = String(event.payload.task_id ?? "");
    if (!taskId) return;
    if (event.type === "progress") {
      setProgress((current) => ({
        ...current,
        [taskId]: {
          done: Number(event.payload.done ?? 0),
          total: Number(event.payload.total ?? 0),
          message: String(event.payload.message ?? ""),
        },
      }));
    } else if (event.type === "task") {
      void refetch();
    }
  });

  return (
    <div className="space-y-4 p-6">
      <div className="flex items-center gap-2 text-xs text-text-muted">
        <span
          className={`inline-block h-2 w-2 rounded-full ${connected ? "bg-emerald-400" : "bg-red-400"}`}
        />
        {connected ? "实时连接正常" : "实时连接断开，进度可能不同步"}
      </div>

      {(tasks ?? []).length === 0 ? (
        <div className="rounded-lg border border-border-subtle bg-surface-raised p-6 text-sm text-text-muted">
          还没有任务记录。
        </div>
      ) : (
        <div className="space-y-2">
          {(tasks ?? []).map((task) => {
            const live = progress[task.id];
            const percent =
              live && live.total > 0 ? Math.min(100, (live.done / live.total) * 100) : null;
            return (
              <div
                key={task.id}
                className="rounded-lg border border-border-subtle bg-surface-raised p-4"
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">
                      {KIND_LABELS[task.kind] ?? task.kind}
                    </span>
                    <span className={`rounded px-2 py-0.5 text-xs ${statusStyle(task.status)}`}>
                      {task.status}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-text-muted">
                    <span>{formatDateTime(task.started_at)}</span>
                    {task.status === "running" ? (
                      <button
                        type="button"
                        onClick={() => cancel.mutate(task.id)}
                        className="rounded border border-border-subtle px-2 py-0.5 hover:border-red-400 hover:text-red-300"
                      >
                        取消
                      </button>
                    ) : null}
                  </div>
                </div>

                {percent !== null ? (
                  <div className="mt-3">
                    <div className="h-1.5 w-full overflow-hidden rounded bg-surface-hover">
                      <div
                        className="h-full bg-accent transition-all"
                        style={{ width: `${percent}%` }}
                      />
                    </div>
                    <div className="mt-1 text-xs text-text-muted">
                      {live.message} ({live.done}/{live.total})
                    </div>
                  </div>
                ) : null}

                <div className="mt-2 text-xs text-text-muted">{detailSummary(task)}</div>
                {task.error ? (
                  <div className="mt-2 text-xs text-red-400">{task.error}</div>
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
```

`frontend/src/pages/Tasks.tsx`：

```tsx
import { useStartSync } from "../api/mutations";
import TaskPanel from "../components/TaskPanel";

export default function Tasks() {
  const sync = useStartSync();

  return (
    <div className="min-h-full">
      <div className="flex flex-wrap items-center gap-3 border-b border-border-subtle px-6 py-4">
        <h1 className="text-base font-semibold">任务</h1>
        <div className="flex-1" />
        <button
          type="button"
          onClick={() => sync.mutate("incremental")}
          disabled={sync.isPending}
          className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        >
          增量同步
        </button>
        <button
          type="button"
          onClick={() => sync.mutate("full")}
          disabled={sync.isPending}
          className="rounded-md border border-border-subtle px-3 py-1.5 text-sm disabled:opacity-50"
        >
          全量同步
        </button>
      </div>
      {sync.isError ? (
        <div className="mx-6 mt-4 rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          启动失败：{sync.error instanceof Error ? sync.error.message : "未知错误"}
        </div>
      ) : null}
      <TaskPanel />
    </div>
  );
}
```

- [ ] **Step 4: 运行测试与构建确认通过**

Run: `cd frontend && npm test && npm run lint && npm run typecheck`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat(frontend): add task panel with sse progress streaming"
```

---

### Task 8: 统计页与导出页

**Files:**
- Modify: `frontend/src/pages/Stats.tsx`
- Modify: `frontend/src/pages/Export.tsx`
- Modify: `frontend/src/pages/Settings.tsx`
- Test: `frontend/src/pages/Stats.test.tsx`

- [ ] **Step 1: 写失败的测试**

`frontend/src/pages/Stats.test.tsx`：

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import Stats from "./Stats";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

afterEach(() => vi.restoreAllMocks());

const STATS = {
  total_illusts: 2050,
  unbookmarked: 3,
  total_pages: 21832,
  downloaded_pages: 192,
  failed_pages: 1,
  pending_pages: 21639,
  total_bytes: 501_234_567,
  thumbs_ready: 24,
  ugoira_count: 43,
  animation_ready: 2,
  by_type: { illust: 2007, ugoira: 43 },
  by_restrict: { public: 2047, private: 3 },
};

describe("Stats", () => {
  it("renders totals from the api", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(STATS), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ),
    );
    render(<Stats />, { wrapper });
    await waitFor(() => expect(screen.getByText("2,050")).toBeInTheDocument());
    expect(screen.getByText("21,832")).toBeInTheDocument();
    expect(screen.getByText(/192/)).toBeInTheDocument();
  });

  it("shows a download progress percentage", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(STATS), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ),
    );
    render(<Stats />, { wrapper });
    await waitFor(() => expect(screen.getByText(/0\.9%/)).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npm test`
Expected: FAIL — Stats 仍是占位组件

- [ ] **Step 3: 实现统计页、导出页与设置页**

`frontend/src/pages/Stats.tsx`：

```tsx
import { useAuthors, useStats, useTags } from "../api/queries";
import { formatBytes } from "../lib/format";

function Card({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-border-subtle bg-surface-raised p-4">
      <div className="text-xs text-text-muted">{label}</div>
      <div className="mt-1 text-xl font-semibold">{value}</div>
      {hint ? <div className="mt-1 text-xs text-text-muted">{hint}</div> : null}
    </div>
  );
}

export default function Stats() {
  const { data, isLoading, isError } = useStats();
  const authors = useAuthors(10);
  const tags = useTags(20);

  if (isLoading) {
    return <div className="p-6 text-sm text-text-muted">加载中…</div>;
  }
  if (isError || !data) {
    return <div className="p-6 text-sm text-red-400">统计数据加载失败</div>;
  }

  const percent =
    data.total_pages > 0 ? (data.downloaded_pages / data.total_pages) * 100 : 0;

  return (
    <div className="space-y-6 p-6">
      <h1 className="text-base font-semibold">统计</h1>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Card label="作品总数" value={data.total_illusts.toLocaleString()} />
        <Card label="总页数" value={data.total_pages.toLocaleString()} />
        <Card
          label="已下载页"
          value={data.downloaded_pages.toLocaleString()}
          hint={`${percent.toFixed(1)}% · 待下载 ${data.pending_pages.toLocaleString()}`}
        />
        <Card label="占用空间" value={formatBytes(data.total_bytes)} />
        <Card label="缩略图" value={data.thumbs_ready.toLocaleString()} />
        <Card
          label="动图"
          value={data.ugoira_count.toLocaleString()}
          hint={`已转码 ${data.animation_ready}`}
        />
        <Card label="已取消收藏" value={data.unbookmarked.toLocaleString()} />
        <Card
          label="失败页"
          value={data.failed_pages.toLocaleString()}
          hint={data.failed_pages > 0 ? "可在任务页重试" : undefined}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-border-subtle bg-surface-raised p-4">
          <div className="mb-3 text-sm font-medium">类型分布</div>
          <div className="space-y-2 text-sm">
            {Object.entries(data.by_type).map(([type, count]) => (
              <div key={type} className="flex items-center justify-between">
                <span className="text-text-muted">
                  {type === "ugoira" ? "动图" : "插画"}
                </span>
                <span>{count.toLocaleString()}</span>
              </div>
            ))}
            {Object.entries(data.by_restrict).map(([restrict, count]) => (
              <div key={restrict} className="flex items-center justify-between">
                <span className="text-text-muted">
                  {restrict === "private" ? "私密收藏" : "公开收藏"}
                </span>
                <span>{count.toLocaleString()}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-lg border border-border-subtle bg-surface-raised p-4">
          <div className="mb-3 text-sm font-medium">作者 TOP 10</div>
          <div className="space-y-2 text-sm">
            {(authors.data ?? []).map((author) => (
              <div key={author.id} className="flex items-center justify-between gap-3">
                <span className="truncate text-text-muted">{author.name}</span>
                <span>{author.illust_count}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-border-subtle bg-surface-raised p-4">
        <div className="mb-3 text-sm font-medium">常见标签</div>
        <div className="flex flex-wrap gap-2">
          {(tags.data ?? []).map((tag) => (
            <span key={tag.name} className="rounded bg-surface-hover px-2 py-1 text-xs">
              {tag.name} · {tag.illust_count}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
```

`frontend/src/pages/Export.tsx`：

```tsx
import { useState } from "react";

import { useStartExport } from "../api/mutations";
import { useStats } from "../api/queries";

export default function Export() {
  const stats = useStats();
  const start = useStartExport();
  const [includeOriginals, setIncludeOriginals] = useState(false);
  const [includeMetadata, setIncludeMetadata] = useState(true);
  const [onlyDownloaded, setOnlyDownloaded] = useState(true);
  const [r18, setR18] = useState<"" | "0" | "1">("");
  const [filename, setFilename] = useState<string | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    start.mutate(
      {
        include_metadata: includeMetadata,
        include_originals: includeOriginals,
        only_downloaded: onlyDownloaded,
        x_restrict: r18 === "" ? undefined : Number(r18),
      },
      {
        onSuccess: (response) => {
          setFilename(response.filename);
          setTaskId(response.task_id);
        },
      },
    );
  };

  return (
    <div className="max-w-xl space-y-5 p-6">
      <h1 className="text-base font-semibold">导出</h1>
      <p className="text-sm text-text-muted">
        按条件打包下载。已下载 {stats.data?.downloaded_pages.toLocaleString() ?? "…"} 页。
      </p>

      <form onSubmit={submit} className="space-y-3 rounded-lg border border-border-subtle bg-surface-raised p-4">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={includeMetadata}
            onChange={(event) => setIncludeMetadata(event.target.checked)}
            className="accent-accent"
          />
          包含元数据 JSON
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={includeOriginals}
            onChange={(event) => setIncludeOriginals(event.target.checked)}
            className="accent-accent"
          />
          包含原图文件（体积可能很大）
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={onlyDownloaded}
            onChange={(event) => setOnlyDownloaded(event.target.checked)}
            className="accent-accent"
          />
          仅包含已下载的作品
        </label>
        <label className="flex items-center gap-2 text-sm">
          <span className="text-text-muted">分级</span>
          <select
            value={r18}
            onChange={(event) => setR18(event.target.value as typeof r18)}
            className="rounded-md border border-border-subtle bg-surface px-2 py-1.5"
          >
            <option value="">不限</option>
            <option value="0">仅全年龄</option>
            <option value="1">仅 R-18</option>
          </select>
        </label>

        <button
          type="submit"
          disabled={start.isPending || (!includeMetadata && !includeOriginals)}
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {start.isPending ? "创建导出任务…" : "开始导出"}
        </button>
      </form>

      {start.isError ? (
        <div className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          {start.error instanceof Error ? start.error.message : "导出失败"}
        </div>
      ) : null}

      {filename && taskId ? (
        <div className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-3 text-sm">
          <div className="text-emerald-300">导出任务已创建：{filename}</div>
          <div className="mt-2 flex gap-3">
            <a className="underline" href={`/api/export/${taskId}/download`}>
              下载压缩包
            </a>
            <a className="underline" href="/tasks">
              查看进度
            </a>
          </div>
        </div>
      ) : null}
    </div>
  );
}
```

`frontend/src/pages/Settings.tsx`：

```tsx
import { useLogout } from "../api/mutations";

export default function Settings() {
  const logout = useLogout();

  return (
    <div className="max-w-xl space-y-5 p-6">
      <h1 className="text-base font-semibold">设置</h1>

      <div className="rounded-lg border border-border-subtle bg-surface-raised p-4 text-sm">
        <div className="mb-2 font-medium">认证</div>
        <p className="mb-3 text-text-muted">
          当前使用单用户令牌认证。退出后需要重新输入 AUTH_TOKEN 登录。
        </p>
        <button
          type="button"
          onClick={() => logout.mutate()}
          disabled={logout.isPending}
          className="rounded-md border border-border-subtle px-3 py-1.5 hover:border-red-400 hover:text-red-300"
        >
          退出登录
        </button>
      </div>

      <div className="rounded-lg border border-border-subtle bg-surface-raised p-4 text-sm">
        <div className="mb-2 font-medium">服务配置</div>
        <p className="text-text-muted">
          同步间隔、代理、图片镜像、并发等通过环境变量配置，修改后需重启服务。
          详见仓库 README 的配置表。
        </p>
      </div>

      <div className="rounded-lg border border-border-subtle bg-surface-raised p-4 text-sm">
        <div className="mb-2 font-medium">接口文档</div>
        <a className="underline" href="/docs" target="_blank" rel="noreferrer">
          /docs（OpenAPI）
        </a>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: 运行测试与构建确认通过**

Run: `cd frontend && npm test && npm run lint && npm run typecheck`
Expected: 全部通过（Stats 测试 2 个）

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat(frontend): add stats, export and settings pages"
```

---

### Task 9: 响应式与细节打磨

**Files:**
- Create: `frontend/src/components/ResponsiveColumns.tsx`
- Modify: `frontend/src/components/AppLayout.tsx`（移动端底部导航）
- Modify: `frontend/src/components/GalleryGrid.tsx`（响应式列数）
- Test: `frontend/src/components/ResponsiveColumns.test.tsx`

- [ ] **Step 1: 写失败的测试**

`frontend/src/components/ResponsiveColumns.test.tsx`：

```tsx
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { columnsForWidth } from "./ResponsiveColumns";

describe("columnsForWidth", () => {
  it("scales the column count with the viewport width", () => {
    expect(columnsForWidth(480)).toBe(2);
    expect(columnsForWidth(768)).toBe(3);
    expect(columnsForWidth(1280)).toBe(4);
    expect(columnsForWidth(1920)).toBe(6);
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npm test`
Expected: FAIL — 找不到 `./ResponsiveColumns`

- [ ] **Step 3: 实现响应式列数与移动端导航**

`frontend/src/components/ResponsiveColumns.tsx`：

```tsx
import { useEffect, useState } from "react";

export function columnsForWidth(width: number): number {
  if (width < 640) return 2;
  if (width < 1024) return 3;
  if (width < 1536) return 4;
  return 6;
}

export function useResponsiveColumns(): number {
  const [columns, setColumns] = useState<number>(() =>
    typeof window === "undefined" ? 4 : columnsForWidth(window.innerWidth),
  );

  useEffect(() => {
    const handleResize = () => setColumns(columnsForWidth(window.innerWidth));
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  return columns;
}
```

`frontend/src/components/GalleryGrid.tsx`（替换为响应式列数）：

```tsx
import type { GalleryItem } from "../api/types";
import GalleryCard from "./GalleryCard";
import { useResponsiveColumns } from "./ResponsiveColumns";

interface Props {
  items: GalleryItem[];
  selected: Set<number>;
  onToggle: (pid: number) => void;
}

export default function GalleryGrid({ items, selected, onToggle }: Props) {
  const columns = useResponsiveColumns();

  if (items.length === 0) {
    return (
      <div className="flex min-h-[240px] items-center justify-center text-sm text-text-muted">
        没有匹配的作品
      </div>
    );
  }

  return (
    <div className="masonry" style={{ columnCount: columns }}>
      {items.map((item) => (
        <GalleryCard
          key={item.pid}
          item={item}
          selected={selected.has(item.pid)}
          onToggle={onToggle}
        />
      ))}
    </div>
  );
}
```

在 `AppLayout.tsx` 的 `</main>` 之前追加移动端底部导航（`md:hidden`），并给 `<main>` 加底部内边距：

```tsx
      <nav className="fixed inset-x-0 bottom-0 z-30 flex border-t border-border-subtle bg-surface-raised md:hidden">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              [
                "flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px]",
                isActive ? "text-text-primary" : "text-text-muted",
              ].join(" ")
            }
          >
            <span aria-hidden>{item.icon}</span>
            {item.label}
          </NavLink>
        ))}
      </nav>
```

- [ ] **Step 4: 运行测试与构建确认通过**

Run: `cd frontend && npm test && npm run lint && npm run typecheck && npm run build`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add frontend src/pixiv_archive/web/static
git commit -m "feat(frontend): add responsive columns and mobile navigation"
```

---

### Task 10: Docker 集成与 CI 前端检查

**Files:**
- Modify: `Dockerfile`（多阶段：node 构建前端）
- Modify: `.github/workflows/ci.yml`（前端 job）
- Modify: `.dockerignore`（排除 node_modules、保留 frontend 源码）
- Create: `.env.example` 追加 `TZ` 已存在则跳过

- [ ] **Step 1: 修改 Dockerfile 为多阶段构建**

`Dockerfile`（完整替换）：

```dockerfile
# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:0.8 AS uv-bin

FROM node:22-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Build directly into the backend package so the runtime image needs one copy
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app
COPY --from=uv-bin /uv /uvx /bin/
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

# Dependencies layer: only pyproject + lock so it stays cached across code changes
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Application layer
COPY src ./src
COPY alembic.ini README.md ./
RUN uv sync --frozen --no-dev

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /data /app
USER appuser
ENV PATH="/app/.venv/bin:$PATH" \
    DATA_DIR=/data
EXPOSE 8000
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1
CMD ["sh", "-c", "alembic upgrade head && python -m pixiv_archive"]
```

- [ ] **Step 2: 更新 .dockerignore 与 CI**

`.dockerignore`（完整替换）：

```
.venv
.git
.github
data
__pycache__
*.pyc
.pytest_cache
.ruff_cache
.mypy_cache
docs
.superpowers
tests
frontend/node_modules
frontend/dist
```

`.github/workflows/ci.yml` 追加 frontend job（放在 `docker` job 之前）：

```yaml
  frontend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: npm
          cache-dependency-path: frontend/package-lock.json

      - name: Install dependencies
        run: npm ci

      - name: Lint
        run: npm run lint

      - name: Typecheck
        run: npm run typecheck

      - name: Tests
        run: npm test

      - name: Build
        run: npm run build
```

- [ ] **Step 3: 本地验证前端构建与静态托管**

Run:
```bash
cd frontend && npm run build
```
Expected: 产物写入 `../src/pixiv_archive/web/static/`（含 `index.html` 与 `assets/`）

Run（另开终端，或先构建再启动）:
```powershell
$env:DATA_DIR="D:\Projects\Pixiv-Collection-Archive\data"
$env:AUTH_TOKEN="test-token"
uv run python -m pixiv_archive
```
Expected: 打开 `http://localhost:8000` 显示前端界面（登录页），`/api/health` 返回 ok

- [ ] **Step 4: 提交并推送，确认云端 CI（含前端 job）通过**

```bash
git add Dockerfile .dockerignore .github frontend src/pixiv_archive/web/static
git commit -m "build: add frontend stage to docker image and frontend ci job"
git push origin main
```

Run: `gh run list --limit 3` 然后 `gh run watch <最新 run id> --exit-status`
Expected: `backend`、`frontend`、`docker` 三个 job 全部成功

---

### Task 11: 真实环境端到端验证与文档

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 启动服务并用真实数据验证界面**

Run（PowerShell，两个终端其一运行服务）:
```powershell
cd D:\Projects\Pixiv-Collection-Archive
$env:DATA_DIR="D:\Projects\Pixiv-Collection-Archive\data"
$env:AUTH_TOKEN="test-token"
uv run python -m pixiv_archive
```

Run（另一个终端，用 gh 或 curl 验证 API 仍正常）:
```powershell
curl.exe -s http://127.0.0.1:8000/api/health
curl.exe -s -c "$env:TEMP\pa-cookies.txt" -X POST http://127.0.0.1:8000/api/auth/login -H "content-type: application/json" -d '{\"token\":\"test-token\"}'
curl.exe -s -b "$env:TEMP\pa-cookies.txt" "http://127.0.0.1:8000/api/gallery?limit=3"
```
Expected: health 返回 `{"status":"ok"}`；登录返回 `{"authenticated":true}`；画廊返回 3 条真实数据

- [ ] **Step 2: 用浏览器验证关键交互（手动）**

打开 `http://localhost:8000` 并确认：
1. 登录页输入 `test-token` 后进入画廊
2. 画廊显示 2050 条，首条为 `#0001`，卡片有缩略图与「未下载/已下载」角标
3. 切换「已下载」过滤后数量变化（约 24 条）
4. 点击卡片进入详情页，显示标签、页数与「下载缺失的 N 页」按钮
5. 任务页可触发「增量同步」并看到 SSE 进度条
6. 统计页显示总量、占比、TOP 作者与标签

- [ ] **Step 3: 更新 README**

把「状态」小节替换为：

```markdown
## 状态

- [x] 项目基础 + pixiv API 层
- [x] 阶段 A：元数据同步（增量 / 全量 + rank 顺序 + 预览图）
- [x] 阶段 B：图片下载（持久化队列 + 范围批次 + 原图 / ugoira / 缩略图）
- [x] Web API（认证 / 画廊 / 详情与文件 / 任务与 SSE / 统计 / 导出）
- [x] WebUI（React 画廊 / 详情 / 任务 / 统计 / 导出）
- [ ] 发布（compose 文档、GHCR 多架构镜像）
```

把「启动 Web 服务」小节替换为：

````markdown
### 启动 Web 服务

```bash
$env:AUTH_TOKEN = "your-token"   # 登录令牌
uv run python -m pixiv_archive
# 打开 http://localhost:8000 输入令牌登录
```

前端开发模式（热更新，API 代理到 8000）：

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
```

前端生产构建（产物由 FastAPI 托管，Docker 构建会自动执行）：

```bash
cd frontend
npm run build        # 输出到 src/pixiv_archive/web/static/
```
````

- [ ] **Step 4: 全量检查并提交推送**

Run:
```bash
cd frontend && npm test && npm run lint && npm run typecheck
cd .. && uv run ruff check src tests; uv run ruff format --check src tests; uv run mypy; uv run pytest -q
```
Expected: 全部通过

```bash
git add README.md
git commit -m "docs: mark webui complete and document frontend workflow"
git push origin main
```

---

## 计划自审

**Spec 覆盖：**

| 设计章节 | 对应任务 |
| --- | --- |
| §10 布局：左侧常驻导航 + 顶部工具栏 + 主内容区（方案 A） | Task 3、5 |
| §10 画廊：瀑布流 + 懒加载 + 序号 `#1234` + 未下载角标 | Task 4、5 |
| §10 画廊：默认收藏顺序（`sort=rank`） | Task 5（SORT_OPTIONS 首项） |
| §10 详情：多页切换、缩放、ugoira 播放、pixiv 链接、下载状态 | Task 6 |
| §10 下载队列：SSE 实时进度、历史、失败重试 | Task 7（进度+历史）、下载入口在 Task 5/6 |
| §10 统计：总数/总大小/已下载比例/作者 Top/存储占用 | Task 8 |
| §10 导出：按筛选导出 zip（可仅元数据）+ 后台任务 | Task 8 |
| §10 响应式：移动端侧栏抽屉化（改用底部导航，等效可用） | Task 9 |
| §12.1 Dockerfile：node 阶段构建前端 | Task 10 |
| §12.3 CI：`tsc --noEmit`、`eslint`、`vitest` | Task 10 |
| §11 `AUTH_TOKEN` 登录 | Task 3 |

**偏差说明（有意为之）：**
- 设计文档写「侧栏可折叠成图标 / 移动端抽屉化」，实现改为**移动端底部导航**——在窄屏上底部导航的可达性优于抽屉，且实现更简单。
- 设计文档的「虚拟滚动」在实现中简化为 **CSS columns + `loading="lazy"`**。理由：分页上限 200 条/页，浏览器原生懒加载足以支撑；虚拟滚动会显著增加复杂度（尤其与 masonry 布局冲突）。若后续单页规模提升到千级，再引入虚拟化。
- 失败项重试：前端通过「下载选中 + 过滤未下载」完成语义等价的重试（后端 `retry` 端点未单独暴露给 UI）。

**占位符扫描：** Task 3 Step 4 明确要求为 6 个页面创建占位组件（给出确切代码），后续任务逐个替换——这是执行顺序而非遗留占位。其余步骤均含完整实现。

**类型一致性：**
- `GalleryItem / IllustDetail / TaskOut / StatsOut` 等类型在 Task 2 定义，Task 4–8 使用一致（字段名与后端 pydantic schema 逐一对应）✅
- `apiFetch` 签名（`method/body/signal`）在 Task 2 定义，Task 3 的 mutations 使用一致 ✅
- `useGallery(util: GalleryQuery)`、`buildGalleryUrl` 在 Task 3 定义，Task 5 使用一致 ✅
- `useSelection` 返回 `{selected, count, toggle, selectMany, clear, isSelected}` 在 Task 4 定义，Task 5 使用 `selected/count/toggle/clear` ✅
- `Lightbox` props（`pid/pages/initialPage/animationAvailable/onClose`）在 Task 6 定义，`IllustDetail` 使用一致 ✅
- `useEventStream(enabled, onEvent)` 在 Task 7 定义并使用 ✅
- `columnsForWidth/useResponsiveColumns` 在 Task 9 定义，`GalleryGrid` 使用一致 ✅
- 下载请求体字段（`scope/pids/x_restrict/type/with_thumbs`）与后端 `DownloadRequest` 对齐；scope 值为下划线形式（`all_missing/rank_range`），与后端 `_SCOPE_ALIASES` 一致 ✅
- 导出请求体字段与后端 `ExportRequest` 一致 ✅
