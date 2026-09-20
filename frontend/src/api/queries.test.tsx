import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useGallery, useMe, useStats, useTasks } from "./queries";

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
  it("fetches the task list", async () => {
    const fetchMock = mockJson([
      {
        id: "abc",
        kind: "sync",
        status: "completed",
        started_at: new Date().toISOString(),
        finished_at: new Date().toISOString(),
        detail: {},
        error: null,
      },
    ]);
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useTasks(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.data?.length).toBe(1));
    expect(fetchMock.mock.calls[0][0]).toBe("/api/tasks");
  });
});
