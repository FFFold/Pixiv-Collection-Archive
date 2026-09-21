import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import Pagination from "./Pagination";

describe("Pagination", () => {
  it("shows the current range and total", () => {
    render(<Pagination offset={60} limit={60} total={2050} onChange={() => undefined} />);
    expect(screen.getByText(/61–120/)).toBeInTheDocument();
    expect(screen.getByText(/共 2050/)).toBeInTheDocument();
  });

  it("disables previous on the first page", () => {
    render(<Pagination offset={0} limit={60} total={100} onChange={() => undefined} />);
    expect(screen.getByRole("button", { name: "上一页" })).toBeDisabled();
  });

  it("emits the next offset", async () => {
    const onChange = vi.fn();
    render(<Pagination offset={0} limit={60} total={200} onChange={onChange} />);
    await userEvent.click(screen.getByRole("button", { name: "下一页" }));
    expect(onChange).toHaveBeenCalledWith(60);
  });

  it("disables next on the last page", () => {
    render(<Pagination offset={180} limit={60} total={200} onChange={() => undefined} />);
    expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
  });

  it("offers page size options and reports a change", async () => {
    const onLimitChange = vi.fn();
    render(
      <Pagination
        offset={0}
        limit={60}
        total={200}
        onChange={() => undefined}
        onLimitChange={onLimitChange}
      />,
    );
    await userEvent.selectOptions(screen.getByLabelText("每页数量"), "240");
    expect(onLimitChange).toHaveBeenCalledWith(240);
  });

  it("jumps to a page number", async () => {
    const onChange = vi.fn();
    render(<Pagination offset={0} limit={60} total={600} onChange={onChange} />);
    const input = screen.getByLabelText("页码");
    await userEvent.clear(input);
    await userEvent.type(input, "5{Enter}");
    expect(onChange).toHaveBeenCalledWith(240);
  });

  it("jumps to the last page", async () => {
    const onChange = vi.fn();
    render(<Pagination offset={0} limit={60} total={130} onChange={onChange} />);
    await userEvent.click(screen.getByRole("button", { name: "末页" }));
    expect(onChange).toHaveBeenCalledWith(120);
  });

  it("changes pages with arrow keys", async () => {
    const onChange = vi.fn();
    render(<Pagination offset={60} limit={60} total={200} onChange={onChange} />);
    await userEvent.keyboard("{ArrowRight}");
    expect(onChange).toHaveBeenCalledWith(120);
  });
});
