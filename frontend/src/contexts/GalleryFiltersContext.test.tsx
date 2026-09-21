import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { GalleryFiltersProvider, useGalleryFilters } from "./GalleryFiltersContext";

function wrapper({ children }: { children: ReactNode }) {
  return <GalleryFiltersProvider>{children}</GalleryFiltersProvider>;
}

describe("GalleryFiltersContext", () => {
  it("starts empty", () => {
    const { result } = renderHook(() => useGalleryFilters(), { wrapper });
    expect(result.current.filters).toEqual({});
  });

  it("stores the latest gallery filters", () => {
    const { result } = renderHook(() => useGalleryFilters(), { wrapper });
    act(() => result.current.setFilters({ tags: ["cat"], downloaded: false }));
    expect(result.current.filters).toEqual({ tags: ["cat"], downloaded: false });
  });

  it("clears filters back to empty", () => {
    const { result } = renderHook(() => useGalleryFilters(), { wrapper });
    act(() => result.current.setFilters({ q: "fox" }));
    act(() => result.current.setFilters({}));
    expect(result.current.filters).toEqual({});
  });
});
