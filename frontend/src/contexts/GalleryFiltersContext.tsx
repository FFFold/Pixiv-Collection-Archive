import { createContext, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";

import type { GalleryQuery } from "../api/types";

export interface GalleryFiltersValue {
  filters: Partial<GalleryQuery>;
  setFilters: (filters: Partial<GalleryQuery>) => void;
}

const GalleryFiltersContext = createContext<GalleryFiltersValue | null>(null);

export function GalleryFiltersProvider({ children }: { children: ReactNode }) {
  const [filters, setFilters] = useState<Partial<GalleryQuery>>({});
  const value = useMemo(() => ({ filters, setFilters }), [filters]);
  return (
    <GalleryFiltersContext.Provider value={value}>{children}</GalleryFiltersContext.Provider>
  );
}

export function useGalleryFilters(): GalleryFiltersValue {
  const value = useContext(GalleryFiltersContext);
  if (value === null) {
    throw new Error("useGalleryFilters must be used inside GalleryFiltersProvider");
  }
  return value;
}
