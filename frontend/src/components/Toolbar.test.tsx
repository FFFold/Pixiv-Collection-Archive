import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SelectionProvider } from "../contexts/SelectionContext";
import Toolbar from "./Toolbar";

function renderToolbar(onChange = vi.fn()) {
  render(
    <SelectionProvider>
      <Toolbar
        query={{ offset: 0, limit: 60, sort: "rank" }}
        onChange={onChange}
        pagePids={[]}
        undownloadedPids={[]}
        onDownloadSelected={() => undefined}
        onDownloadAllMissing={() => undefined}
        downloadPending={false}
      />
    </SelectionProvider>,
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
      <SelectionProvider>
        <Toolbar
          query={{ offset: 0, limit: 60, sort: "rank", only_deleted: true }}
          onChange={onChange}
          pagePids={[]}
          undownloadedPids={[]}
          onDownloadSelected={() => undefined}
          onDownloadAllMissing={() => undefined}
          downloadPending={false}
        />
      </SelectionProvider>,
    );
    await userEvent.selectOptions(screen.getByLabelText("状态"), "active");
    expect(onChange).toHaveBeenCalledWith({
      only_deleted: undefined,
      include_deleted: undefined,
      offset: 0,
    });
  });
});
