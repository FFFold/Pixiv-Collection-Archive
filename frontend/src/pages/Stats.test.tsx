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

function mockStats() {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/stats")) {
        return Promise.resolve(
          new Response(JSON.stringify(STATS), {
            status: 200,
            headers: { "content-type": "application/json" },
          }),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify([]), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
    }),
  );
}

describe("Stats", () => {
  it("renders totals from the api", async () => {
    mockStats();
    render(<Stats />, { wrapper });
    await waitFor(() => expect(screen.getByText("2,050")).toBeInTheDocument());
    expect(screen.getByText("21,832")).toBeInTheDocument();
    expect(screen.getByText(/192/)).toBeInTheDocument();
  });

  it("shows a download progress percentage", async () => {
    mockStats();
    render(<Stats />, { wrapper });
    await waitFor(() => expect(screen.getByText(/0\.9%/)).toBeInTheDocument());
  });
});
