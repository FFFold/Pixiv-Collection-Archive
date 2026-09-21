import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";

export interface SelectionValue {
  selected: Set<number>;
  count: number;
  toggle: (pid: number) => void;
  selectMany: (pids: number[]) => void;
  removeMany: (pids: number[]) => void;
  clear: () => void;
}

const SelectionContext = createContext<SelectionValue | null>(null);

export function SelectionProvider({ children }: { children: ReactNode }) {
  const [selected, setSelected] = useState<Set<number>>(() => new Set());

  const toggle = useCallback((pid: number) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(pid)) next.delete(pid);
      else next.add(pid);
      return next;
    });
  }, []);

  const selectMany = useCallback((pids: number[]) => {
    setSelected((current) => {
      const next = new Set(current);
      pids.forEach((pid) => next.add(pid));
      return next;
    });
  }, []);

  const removeMany = useCallback((pids: number[]) => {
    setSelected((current) => {
      const next = new Set(current);
      pids.forEach((pid) => next.delete(pid));
      return next;
    });
  }, []);

  const clear = useCallback(() => setSelected(new Set()), []);

  const value = useMemo(
    () => ({ selected, count: selected.size, toggle, selectMany, removeMany, clear }),
    [selected, toggle, selectMany, removeMany, clear],
  );

  return <SelectionContext.Provider value={value}>{children}</SelectionContext.Provider>;
}

export function useSelection(): SelectionValue {
  const value = useContext(SelectionContext);
  if (value === null) {
    throw new Error("useSelection must be used inside SelectionProvider");
  }
  return value;
}
