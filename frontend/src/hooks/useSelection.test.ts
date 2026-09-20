import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useSelection } from "./useSelection";

describe("useSelection", () => {
  it("toggles pids on and off", () => {
    const { result } = renderHook(() => useSelection());
    act(() => result.current.toggle(1));
    expect(result.current.selected.has(1)).toBe(true);
    act(() => result.current.toggle(1));
    expect(result.current.selected.has(1)).toBe(false);
  });

  it("supports select-many and clear", () => {
    const { result } = renderHook(() => useSelection());
    act(() => result.current.selectMany([1, 2, 3]));
    expect(result.current.count).toBe(3);
    act(() => result.current.clear());
    expect(result.current.count).toBe(0);
  });

  it("keeps selection across rerenders", () => {
    const { result, rerender } = renderHook(() => useSelection());
    act(() => result.current.toggle(42));
    rerender();
    expect(result.current.selected.has(42)).toBe(true);
  });
});
