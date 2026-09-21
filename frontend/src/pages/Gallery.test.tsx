import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GalleryFiltersProvider } from "../contexts/GalleryFiltersContext";
import { SelectionProvider } from "../contexts/SelectionContext";
import Gallery from "./Gallery";

const ITEM = {
  pid: 1,
  index: 1,
  title: "作品一",
  author_id: 1,
  author_name: "画师",
  page_count: 1,
  type: "illust",
  x_restrict: 0,
  width: 100,
  height: 100,
  create_date: null,
  rank: 0,
  has_original: false,
  page_downloaded_count: 0,
  preview_url: "/api/illust/1/thumb",
  thumb_url: "/api/illust/1/thumb",
  restrict: "public",
  unbookmarked: false,
  state: "active",
};

function wrapper(initialEntry = "/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[initialEntry]}>
          <SelectionProvider>
            <GalleryFiltersProvider>{children}</GalleryFiltersProvider>
          </SelectionProvider>
        </MemoryRouter>
      </QueryClientProvider>
    );
  };
}

afterEach(() => vi.restoreAllMocks());

function mockGallery() {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      const payload = url.includes("/api/gallery")
        ? { items: [ITEM], total: 1, offset: 0, limit: 60 }
        : { task_id: "t", filename: "f" };
      return Promise.resolve(
        new Response(JSON.stringify(payload), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
    }),
  );
}

describe("Gallery", () => {
  it("selects the whole page", async () => {
    mockGallery();
    render(<Gallery />, { wrapper: wrapper() });
    await waitFor(() => expect(screen.getByText("作品一")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "全选本页" }));
    expect(screen.getByText(/下载选中 \(1\)/)).toBeInTheDocument();
  });

  it("inverts the page selection", async () => {
    mockGallery();
    render(<Gallery />, { wrapper: wrapper() });
    await waitFor(() => expect(screen.getByText("作品一")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "反选本页" }));
    expect(screen.getByText(/下载选中 \(1\)/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "反选本页" }));
    expect(screen.getByText(/下载选中 \(0\)/)).toBeInTheDocument();
  });

  it("keeps selection across pages (selection context)", async () => {
    mockGallery();
    render(<Gallery />, { wrapper: wrapper() });
    await waitFor(() => expect(screen.getByText("作品一")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("checkbox"));
    expect(screen.getByText(/下载选中 \(1\)/)).toBeInTheDocument();
  });
});
