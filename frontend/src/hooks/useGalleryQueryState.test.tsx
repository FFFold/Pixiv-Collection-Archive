import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { useGalleryQueryState } from "./useGalleryQueryState";

function wrapperFor(initialEntry: string) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <MemoryRouter initialEntries={[initialEntry]}>{children}</MemoryRouter>;
  };
}

describe("useGalleryQueryState", () => {
  it("parses repeated params into arrays", () => {
    const { result } = renderHook(() => useGalleryQueryState(), {
      wrapper: wrapperFor("/?tag=cat&tag=cute&author_id=1&author_id=2&page_min=2"),
    });
    expect(result.current.query.tags).toEqual(["cat", "cute"]);
    expect(result.current.query.author_ids).toEqual([1, 2]);
    expect(result.current.query.page_min).toBe(2);
  });

  it("omits default values when serializing", () => {
    const { result } = renderHook(
      () => {
        const state = useGalleryQueryState();
        return { state, location: useLocation() };
      },
      { wrapper: wrapperFor("/") },
    );
    act(() => result.current.state.patch({ sort: "rank", offset: 0, limit: 60 }));
    expect(result.current.location.search).toBe("");
  });

  it("resets offset when a filter changes", () => {
    const { result } = renderHook(
      () => {
        const state = useGalleryQueryState();
        return { state, location: useLocation() };
      },
      { wrapper: wrapperFor("/?offset=120") },
    );
    act(() => result.current.state.patch({ tags: ["cat"] }));
    expect(result.current.state.query.offset).toBe(0);
    expect(result.current.location.search).toContain("tag=cat");
  });

  it("applies the provided initial filter", () => {
    const { result } = renderHook(
      () => useGalleryQueryState({ only_unbookmarked: true }),
      { wrapper: wrapperFor("/") },
    );
    expect(result.current.query.only_unbookmarked).toBe(true);
  });
});
