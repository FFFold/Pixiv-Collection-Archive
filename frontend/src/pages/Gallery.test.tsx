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

  it("keeps the selection when navigating to another page", async () => {
    const pageTwo = { ...ITEM, pid: 2, index: 2, title: "作品二" };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        const url = String(input);
        const onSecondPage = url.includes("offset=60");
        const payload = url.includes("/api/gallery")
          ? {
              items: onSecondPage ? [pageTwo] : [ITEM],
              total: 120,
              offset: onSecondPage ? 60 : 0,
              limit: 60,
            }
          : { task_id: "t", filename: "f" };
        return Promise.resolve(
          new Response(JSON.stringify(payload), {
            status: 200,
            headers: { "content-type": "application/json" },
          }),
        );
      }),
    );
    render(<Gallery />, { wrapper: wrapper() });
    await waitFor(() => expect(screen.getByText("作品一")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "全选本页" }));
    expect(screen.getByText(/下载选中 \(1\)/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "下一页" }));
    await waitFor(() => expect(screen.getByText("作品二")).toBeInTheDocument());
    expect(screen.getByText(/下载选中 \(1\)/)).toBeInTheDocument();
  });

  it("clears the deleted-state filter when switching back to 仅正常", async () => {
    mockGallery();
    render(<Gallery />, { wrapper: wrapper("/?only_deleted=true") });
    await waitFor(() => expect(screen.getByLabelText("状态")).toHaveValue("deleted"));

    await userEvent.selectOptions(screen.getByLabelText("状态"), "active");
    await waitFor(() => expect(screen.getByLabelText("状态")).toHaveValue("active"));
  });

  it("clears the pinned unbookmarked filter via 清空筛选", async () => {
    mockGallery();
    render(<Gallery initialOnlyUnbookmarked />, { wrapper: wrapper() });
    await waitFor(() => expect(screen.getByText("作品一")).toBeInTheDocument());
    expect(screen.getByLabelText("状态")).toHaveValue("active");

    await userEvent.click(screen.getByRole("button", { name: /清空筛选/ }));
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /清空筛选/ })).not.toBeInTheDocument(),
    );
  });
});
