import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import FilterPickers from "./FilterPickers";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

afterEach(() => vi.restoreAllMocks());

function mockOptions() {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      const payload = url.includes("/api/tags")
        ? [
            { name: "cat", translated_name: null, illust_count: 5 },
            { name: "cute", translated_name: null, illust_count: 3 },
          ]
        : [
            { id: 7, name: "画师甲", account: "a", illust_count: 4 },
            { id: 8, name: "画师乙", account: "b", illust_count: 2 },
          ];
      return Promise.resolve(
        new Response(JSON.stringify(payload), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
    }),
  );
}

describe("FilterPickers", () => {
  it("adds a tag when chosen from the dropdown", async () => {
    mockOptions();
    const onChange = vi.fn();
    render(<FilterPickers tags={[]} authorIds={[]} onChange={onChange} />, { wrapper });
    await waitFor(() => expect(screen.getByLabelText("添加标签")).toBeInTheDocument());
    await waitFor(() =>
      expect(screen.getByRole("option", { name: /cat/ })).toBeInTheDocument(),
    );

    await userEvent.selectOptions(screen.getByLabelText("添加标签"), "cat");
    expect(onChange).toHaveBeenCalledWith({ tags: ["cat"], offset: 0 });
  });

  it("appends to existing tags instead of replacing them", async () => {
    mockOptions();
    const onChange = vi.fn();
    render(<FilterPickers tags={["cat"]} authorIds={[]} onChange={onChange} />, { wrapper });
    await waitFor(() =>
      expect(screen.getByRole("option", { name: /cute/ })).toBeInTheDocument(),
    );

    await userEvent.selectOptions(screen.getByLabelText("添加标签"), "cute");
    expect(onChange).toHaveBeenCalledWith({ tags: ["cat", "cute"], offset: 0 });
  });

  it("hides already selected tags from the dropdown", async () => {
    mockOptions();
    render(<FilterPickers tags={["cat"]} authorIds={[]} onChange={vi.fn()} />, { wrapper });
    await waitFor(() =>
      expect(screen.getByRole("option", { name: /cute/ })).toBeInTheDocument(),
    );
    expect(screen.queryByRole("option", { name: /cat/ })).not.toBeInTheDocument();
  });

  it("removes a tag chip", async () => {
    mockOptions();
    const onChange = vi.fn();
    render(<FilterPickers tags={["cat", "cute"]} authorIds={[]} onChange={onChange} />, {
      wrapper,
    });

    await userEvent.click(screen.getByRole("button", { name: "移除标签 cat" }));
    expect(onChange).toHaveBeenCalledWith({ tags: ["cute"], offset: 0 });
  });

  it("clears tags entirely when the last chip is removed", async () => {
    mockOptions();
    const onChange = vi.fn();
    render(<FilterPickers tags={["cat"]} authorIds={[]} onChange={onChange} />, { wrapper });

    await userEvent.click(screen.getByRole("button", { name: "移除标签 cat" }));
    expect(onChange).toHaveBeenCalledWith({ tags: undefined, offset: 0 });
  });

  it("adds and removes an author", async () => {
    mockOptions();
    const onChange = vi.fn();
    render(<FilterPickers tags={[]} authorIds={[]} onChange={onChange} />, { wrapper });
    await waitFor(() =>
      expect(screen.getByRole("option", { name: /画师甲/ })).toBeInTheDocument(),
    );

    await userEvent.selectOptions(screen.getByLabelText("添加作者"), "7");
    expect(onChange).toHaveBeenCalledWith({ author_ids: [7], offset: 0 });
  });

  it("removes an author chip by id and label", async () => {
    mockOptions();
    const onChange = vi.fn();
    render(<FilterPickers tags={[]} authorIds={[7]} onChange={onChange} />, { wrapper });
    await waitFor(() => expect(screen.getByText("画师甲")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: "移除作者 画师甲" }));
    expect(onChange).toHaveBeenCalledWith({ author_ids: undefined, offset: 0 });
  });
});
