import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GalleryFiltersProvider } from "../contexts/GalleryFiltersContext";
import { SelectionProvider } from "../contexts/SelectionContext";
import Export from "./Export";

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <SelectionProvider>
            <GalleryFiltersProvider>{children}</GalleryFiltersProvider>
          </SelectionProvider>
        </MemoryRouter>
      </QueryClientProvider>
    );
  };
}

afterEach(() => vi.restoreAllMocks());

function mockApi() {
  const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/api/stats")) {
      return Promise.resolve(
        new Response(
          JSON.stringify({
            total_illusts: 1,
            unbookmarked: 0,
            total_pages: 1,
            downloaded_pages: 1,
            failed_pages: 0,
            pending_pages: 0,
            total_bytes: 1,
            thumbs_ready: 1,
            ugoira_count: 0,
            animation_ready: 0,
            by_type: {},
            by_restrict: {},
            by_type_bytes: {},
            by_restrict_bytes: {},
            top_authors_bytes: [],
            stats_stale: false,
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
      );
    }
    return Promise.resolve(
      new Response(JSON.stringify({ task_id: "t1", filename: "f.zip" }), {
        status: 202,
        headers: { "content-type": "application/json" },
      }),
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function lastExportBody(fetchMock: ReturnType<typeof vi.fn>) {
  const call = fetchMock.mock.calls.find(([url]) => String(url) === "/api/export");
  return JSON.parse(String(call?.[1]?.body));
}

describe("Export", () => {
  it("does not set use_filter in the default all scope", async () => {
    const fetchMock = mockApi();
    render(<Export />, { wrapper: wrapper() });
    await userEvent.click(screen.getByRole("button", { name: "开始导出" }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url) === "/api/export")).toBe(true),
    );
    const body = lastExportBody(fetchMock);
    expect(body.use_filter).toBeFalsy();
    expect(body.pids).toBeUndefined();
  });

  it("submits the current gallery filter when selecting filter scope", async () => {
    const fetchMock = mockApi();
    render(<Export />, { wrapper: wrapper() });

    await userEvent.click(screen.getByLabelText("按当前筛选"));
    await userEvent.click(screen.getByRole("button", { name: "开始导出" }));

    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url) === "/api/export")).toBe(true),
    );
    expect(lastExportBody(fetchMock).use_filter).toBe(true);
  });

  it("disables selection scope when nothing is selected", async () => {
    mockApi();
    render(<Export />, { wrapper: wrapper() });
    expect(screen.getByLabelText("按选中 (0)")).toBeDisabled();
  });
});
