import { useCallback, useMemo, useState } from "react";

export interface Selection {
  selected: Set<number>;
  count: number;
  toggle: (pid: number) => void;
  selectMany: (pids: number[]) => void;
  clear: () => void;
  isSelected: (pid: number) => boolean;
}

export function useSelection(): Selection {
  const [selected, setSelected] = useState<Set<number>>(() => new Set());

  const toggle = useCallback((pid: number) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(pid)) {
        next.delete(pid);
      } else {
        next.add(pid);
      }
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

  const clear = useCallback(() => setSelected(new Set()), []);

  const isSelected = useCallback((pid: number) => selected.has(pid), [selected]);

  return useMemo(
    () => ({ selected, count: selected.size, toggle, selectMany, clear, isSelected }),
    [selected, toggle, selectMany, clear, isSelected],
  );
}
