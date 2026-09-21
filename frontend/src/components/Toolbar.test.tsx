import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { SelectionProvider } from "../contexts/SelectionContext";
import Toolbar from "./Toolbar";

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

function TestProviders({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <SelectionProvider>{children}</SelectionProvider>
    </QueryClientProvider>
  );
}

function renderToolbar(onChange = vi.fn()) {
  render(
    <TestProviders>
      <Toolbar
        query={{ offset: 0, limit: 60, sort: "rank" }}
        onChange={onChange}
        pagePids={[]}
        undownloadedPids={[]}
        onDownloadSelected={() => undefined}
        onDownloadAllMissing={() => undefined}
        downloadPending={false}
      />
    </TestProviders>,
  );
  return onChange;
}

describe("Toolbar 状态筛选", () => {
  it("defaults to 仅正常", () => {
    renderToolbar();
    expect(screen.getByLabelText("状态")).toHaveValue("active");
  });

  it("选择已失效时回传 only_deleted", async () => {
    const onChange = renderToolbar();
    await userEvent.selectOptions(screen.getByLabelText("状态"), "deleted");
    expect(onChange).toHaveBeenCalledWith({ only_deleted: true, offset: 0 });
  });

  it("选择全部状态时回传 include_deleted", async () => {
    const onChange = renderToolbar();
    await userEvent.selectOptions(screen.getByLabelText("状态"), "all");
    expect(onChange).toHaveBeenCalledWith({ include_deleted: true, offset: 0 });
  });

  it("从已失效切回仅正常时清掉失效参数", async () => {
    const onChange = vi.fn();
    render(
      <TestProviders>
        <Toolbar
          query={{ offset: 0, limit: 60, sort: "rank", only_deleted: true }}
          onChange={onChange}
          pagePids={[]}
          undownloadedPids={[]}
          onDownloadSelected={() => undefined}
          onDownloadAllMissing={() => undefined}
          downloadPending={false}
        />
      </TestProviders>,
    );
    await userEvent.selectOptions(screen.getByLabelText("状态"), "active");
    expect(onChange).toHaveBeenCalledWith({
      only_deleted: undefined,
      include_deleted: undefined,
      offset: 0,
    });
  });
});
