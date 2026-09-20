import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { GalleryItem } from "../api/types";
import GalleryCard from "./GalleryCard";

const ITEM: GalleryItem = {
  pid: 123456,
  index: 7,
  title: "测试作品",
  author_id: 1,
  author_name: "画师",
  page_count: 3,
  type: "illust",
  x_restrict: 0,
  width: 1200,
  height: 800,
  create_date: "2026-03-16T11:42:49+09:00",
  rank: 6144,
  has_original: false,
  page_downloaded_count: 0,
  preview_url: "/api/illust/123456/thumb",
  thumb_url: "/api/illust/123456/thumb",
  restrict: "public",
  unbookmarked: false,
};

function renderCard(item: GalleryItem, selected = false, onToggle = () => undefined) {
  return render(
    <MemoryRouter>
      <GalleryCard item={item} selected={selected} onToggle={onToggle} />
    </MemoryRouter>,
  );
}

describe("GalleryCard", () => {
  it("renders the index badge and title", () => {
    renderCard(ITEM);
    expect(screen.getByText("#0007")).toBeInTheDocument();
    expect(screen.getByText("测试作品")).toBeInTheDocument();
    expect(screen.getByText("未下载")).toBeInTheDocument();
  });

  it("marks multi-page and ugoira works", () => {
    renderCard({ ...ITEM, type: "ugoira", page_count: 2 });
    expect(screen.getByText("2P")).toBeInTheDocument();
    expect(screen.getByText("动图")).toBeInTheDocument();
  });

  it("calls onToggle when the checkbox is clicked", async () => {
    const onToggle = vi.fn();
    renderCard(ITEM, false, onToggle);
    await userEvent.click(screen.getByRole("checkbox"));
    expect(onToggle).toHaveBeenCalledWith(123456);
  });

  it("shows a downloaded indicator", () => {
    renderCard({ ...ITEM, has_original: true, page_downloaded_count: 3 });
    expect(screen.queryByText("未下载")).not.toBeInTheDocument();
    expect(screen.getByText("已下载")).toBeInTheDocument();
  });
});
