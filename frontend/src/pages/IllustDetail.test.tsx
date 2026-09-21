import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SelectionProvider, useSelection } from "../contexts/SelectionContext";
import IllustDetail from "./IllustDetail";

const DETAIL = {
  pid: 42,
  index: 1,
  title: "作品",
  description: "",
  author_id: 7,
  author_name: "画师",
  author_account: "acct",
  page_count: 1,
  type: "illust",
  x_restrict: 0,
  sanity_level: 0,
  width: 100,
  height: 100,
  create_date: null,
  total_view: 0,
  total_bookmarks: 0,
  state: "active",
  has_original: true,
  page_downloaded_count: 1,
  tags: [],
  translated_tags: [],
  pages: [{ page_index: 0, download_state: "done", ext: ".jpg" }],
  restrict: "public",
  bookmark_state: "active",
  rank: 0,
  pixiv_url: "https://www.pixiv.net/artworks/42",
  animation_available: false,
  frame_count: null,
  unbookmarked: false,
};

function Probe() {
  const selection = useSelection();
  return <span data-testid="probe">{selection.count}</span>;
}

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/illust/42"]}>
          <SelectionProvider>
            <Routes>
              <Route path="/illust/:pid" element={children} />
            </Routes>
            <Probe />
          </SelectionProvider>
        </MemoryRouter>
      </QueryClientProvider>
    );
  };
}

afterEach(() => vi.restoreAllMocks());

function mockDetail() {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(DETAIL), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    ),
  );
}

describe("IllustDetail", () => {
  it("adds and removes the work from the selection", async () => {
    mockDetail();
    render(<IllustDetail />, { wrapper: wrapper() });
    await waitFor(() => expect(screen.getByText("作品")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: "加入选择" }));
    expect(screen.getByTestId("probe")).toHaveTextContent("1");

    await userEvent.click(screen.getByRole("button", { name: "移出选择" }));
    expect(screen.getByTestId("probe")).toHaveTextContent("0");
  });

  it("links the author with author_id parameter", async () => {
    mockDetail();
    render(<IllustDetail />, { wrapper: wrapper() });
    await waitFor(() => expect(screen.getByText("画师")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "画师" })).toHaveAttribute(
      "href",
      "/?author_id=7",
    );
  });
});
