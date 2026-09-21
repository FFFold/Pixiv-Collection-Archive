import { useCallback, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import type { GalleryQuery } from "../api/types";
import { GALLERY_LIST_PARAMS } from "../api/queries";
import { PAGE_SIZE } from "../lib/constants";

const SINGLE_KEYS = [
  "offset",
  "limit",
  "sort",
  "q",
  "type",
  "x_restrict",
  "downloaded",
  "restrict",
  "only_unbookmarked",
  "include_unbookmarked",
  "only_deleted",
  "include_deleted",
  "page_min",
  "page_max",
  "bookmarks_min",
  "bookmarks_max",
  "views_min",
  "views_max",
  "rank_start",
  "rank_count",
] as const;

type SingleKey = (typeof SINGLE_KEYS)[number];
type ListKey = keyof typeof GALLERY_LIST_PARAMS;

const INT_KEYS = new Set<SingleKey>([
  "offset",
  "limit",
  "x_restrict",
  "page_min",
  "page_max",
  "bookmarks_min",
  "bookmarks_max",
  "views_min",
  "views_max",
  "rank_start",
  "rank_count",
]);

const BOOL_KEYS = new Set<SingleKey>([
  "downloaded",
  "only_unbookmarked",
  "include_unbookmarked",
  "only_deleted",
  "include_deleted",
]);

const DEFAULT_VALUES: Partial<Record<SingleKey, string>> = {
  offset: "0",
  limit: String(PAGE_SIZE),
  sort: "rank",
};

function parseSingle(key: SingleKey, raw: string): unknown {
  if (INT_KEYS.has(key)) {
    const value = Number(raw);
    return Number.isFinite(value) ? value : undefined;
  }
  if (BOOL_KEYS.has(key)) {
    return raw === "true" ? true : raw === "false" ? false : undefined;
  }
  return raw === "" ? undefined : raw;
}

export interface UseGalleryQueryState {
  query: GalleryQuery;
  patch: (update: Partial<GalleryQuery>) => void;
  reset: () => void;
}

export function useGalleryQueryState(
  initial: Partial<GalleryQuery> = {},
): UseGalleryQueryState {
  const [searchParams, setSearchParams] = useSearchParams();
  const [released, setReleased] = useState(false);

  const query = useMemo(() => {
    const parsed: GalleryQuery = { offset: 0, limit: PAGE_SIZE, sort: "rank" };
    SINGLE_KEYS.forEach((key) => {
      if (!released && key in initial) return;
      const raw = searchParams.get(key);
      if (raw === null || raw === "") return;
      (parsed as Record<string, unknown>)[key] = parseSingle(key, raw);
    });
    (Object.keys(GALLERY_LIST_PARAMS) as ListKey[]).forEach((key) => {
      const raw = searchParams.getAll(GALLERY_LIST_PARAMS[key]);
      if (raw.length === 0) return;
      if (key === "author_ids") {
        const ids = raw.map(Number).filter((value) => Number.isFinite(value));
        if (ids.length > 0) (parsed as Record<string, unknown>)[key] = ids;
        return;
      }
      (parsed as Record<string, unknown>)[key] = raw;
    });
    return released ? parsed : { ...parsed, ...initial };
  }, [searchParams, initial, released]);

  const patch = useCallback(
    (update: Partial<GalleryQuery>) => {
      const next = new URLSearchParams(searchParams);
      let release = false;
      Object.entries(update).forEach(([key, value]) => {
        if (!released && key in initial) {
          release = true;
        }
        if (key in GALLERY_LIST_PARAMS) {
          const paramName = GALLERY_LIST_PARAMS[key as ListKey];
          next.delete(paramName);
          if (Array.isArray(value) && value.length > 0) {
            value.forEach((entry) => next.append(paramName, String(entry)));
          }
          return;
        }
        if (value === undefined || value === null || value === "") {
          next.delete(key);
          return;
        }
        const defaultValue = DEFAULT_VALUES[key as SingleKey];
        if (defaultValue !== undefined && String(value) === defaultValue) {
          next.delete(key);
          return;
        }
        if (Array.isArray(value)) return;
        next.set(key, String(value));
      });
      if (!("offset" in update)) {
        next.delete("offset");
      }
      setSearchParams(next, { replace: true });
      if (release) {
        setReleased(true);
      }
    },
    [searchParams, setSearchParams, initial, released],
  );

  const reset = useCallback(() => {
    setSearchParams(new URLSearchParams(), { replace: true });
    if (!released && Object.keys(initial).length > 0) {
      setReleased(true);
    }
  }, [setSearchParams, initial, released]);

  return { query, patch, reset };
}
