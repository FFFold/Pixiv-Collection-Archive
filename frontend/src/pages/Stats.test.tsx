import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import Stats from "./Stats";

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
  by_type_bytes: { illust: 401_234_567, ugoira: 100_000_000 },
  by_restrict_bytes: { public: 500_000_000, private: 1_234_567 },
  top_authors_bytes: [{ id: 1, name: "画师甲", bytes: 200_000_000, illust_count: 10 }],
  stats_stale: false,
};

afterEach(() => vi.restoreAllMocks());

function mockStats(overrides: Partial<typeof STATS> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      const payload = url.includes("/api/stats") ? { ...STATS, ...overrides } : [];
      return Promise.resolve(
        new Response(JSON.stringify(payload), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
    }),
  );
}

function renderStats() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Stats />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Stats", () => {
  it("renders totals from the api", async () => {
    mockStats();
    renderStats();
    await waitFor(() => expect(screen.getByText("2,050")).toBeInTheDocument());
    expect(screen.getByText("21,832")).toBeInTheDocument();
    expect(screen.getByText(/192/)).toBeInTheDocument();
  });

  it("shows a download progress percentage", async () => {
    mockStats();
    renderStats();
    await waitFor(() => expect(screen.getByText(/0\.9%/)).toBeInTheDocument());
  });

  it("renders the storage distribution", async () => {
    mockStats();
    renderStats();
    await waitFor(() => expect(screen.getByText("体积与页数分布")).toBeInTheDocument());
    expect(screen.getByText("画师甲")).toBeInTheDocument();
  });

  it("links download metrics to gallery filters", async () => {
    mockStats();
    renderStats();
    await waitFor(() => expect(screen.getByText(/192/)).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /已下载页/ })).toHaveAttribute(
      "href",
      "/?downloaded=true",
    );
  });

  it("prompts to rebuild stats when stale", async () => {
    mockStats({ stats_stale: true });
    renderStats();
    await waitFor(() => expect(screen.getByText(/体积未知/)).toBeInTheDocument());
  });
});
