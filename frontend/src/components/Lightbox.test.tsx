import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import Lightbox from "./Lightbox";

const PAGES = [
  { page_index: 0, download_state: "done", ext: ".jpg" },
  { page_index: 1, download_state: "done", ext: ".jpg" },
  { page_index: 2, download_state: "pending", ext: ".jpg" },
];

describe("Lightbox", () => {
  it("renders the current page image", () => {
    render(<Lightbox pid={10} pages={PAGES} initialPage={0} onClose={() => undefined} />);
    expect(screen.getByRole("img")).toHaveAttribute("src", "/api/illust/10/file/0");
  });

  it("navigates to the next page", async () => {
    render(<Lightbox pid={10} pages={PAGES} initialPage={0} onClose={() => undefined} />);
    await userEvent.click(screen.getByRole("button", { name: "下一页" }));
    expect(screen.getByRole("img")).toHaveAttribute("src", "/api/illust/10/file/1");
    expect(screen.getByText("2 / 3")).toBeInTheDocument();
  });

  it("wraps around at the end", async () => {
    render(<Lightbox pid={10} pages={PAGES} initialPage={2} onClose={() => undefined} />);
    await userEvent.click(screen.getByRole("button", { name: "下一页" }));
    expect(screen.getByRole("img")).toHaveAttribute("src", "/api/illust/10/file/0");
  });

  it("closes on the close button", async () => {
    const onClose = vi.fn();
    render(<Lightbox pid={10} pages={PAGES} initialPage={0} onClose={onClose} />);
    await userEvent.click(screen.getByRole("button", { name: "关闭" }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("plays ugoira instead of showing pages", () => {
    render(
      <Lightbox
        pid={10}
        pages={PAGES}
        initialPage={0}
        animationAvailable
        onClose={() => undefined}
      />,
    );
    expect(screen.getByTestId("ugoira-video")).toHaveAttribute(
      "src",
      "/api/illust/10/animation",
    );
  });
});
