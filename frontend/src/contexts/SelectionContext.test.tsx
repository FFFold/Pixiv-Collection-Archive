import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { SelectionProvider, useSelection } from "./SelectionContext";

function wrapper({ children }: { children: ReactNode }) {
  return <SelectionProvider>{children}</SelectionProvider>;
}

describe("SelectionContext", () => {
  it("toggles pids on and off", () => {
    const { result } = renderHook(() => useSelection(), { wrapper });
    act(() => result.current.toggle(1));
    expect(result.current.selected.has(1)).toBe(true);
    act(() => result.current.toggle(1));
    expect(result.current.selected.has(1)).toBe(false);
  });

  it("accumulates across pages via selectMany", () => {
    const { result } = renderHook(() => useSelection(), { wrapper });
    act(() => result.current.selectMany([1, 2]));
    act(() => result.current.selectMany([3]));
    expect(result.current.count).toBe(3);
  });

  it("removes a subset and clears", () => {
    const { result } = renderHook(() => useSelection(), { wrapper });
    act(() => result.current.selectMany([1, 2, 3]));
    act(() => result.current.removeMany([1, 3]));
    expect([...result.current.selected]).toEqual([2]);
    act(() => result.current.clear());
    expect(result.current.count).toBe(0);
  });
});
