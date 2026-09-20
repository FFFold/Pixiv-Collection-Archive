import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import Toolbar from "./Toolbar";

function renderToolbar(onChange = vi.fn()) {
  render(
    <Toolbar
      query={{ offset: 0, limit: 60, sort: "rank" }}
      onChange={onChange}
      selectedCount={0}
      onDownloadSelected={() => undefined}
      onDownloadAllMissing={() => undefined}
      downloadPending={false}
    />,
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
      <Toolbar
        query={{ offset: 0, limit: 60, sort: "rank", only_deleted: true }}
        onChange={onChange}
        selectedCount={0}
        onDownloadSelected={() => undefined}
        onDownloadAllMissing={() => undefined}
        downloadPending={false}
      />,
    );
    await userEvent.selectOptions(screen.getByLabelText("状态"), "active");
    expect(onChange).toHaveBeenCalledWith({ offset: 0 });
  });
});
