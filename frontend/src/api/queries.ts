import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "./client";
import type {
  AuthorOut,
  GalleryQuery,
  GalleryResponse,
  IllustDetail,
  MeResponse,
  StatsOut,
  TagOut,
  TaskOut,
} from "./types";

type ListKey = {
  [K in keyof GalleryQuery]-?: NonNullable<GalleryQuery[K]> extends readonly unknown[]
    ? K
    : never;
}[keyof GalleryQuery];

export const GALLERY_LIST_PARAMS = {
  tags: "tag",
  author_ids: "author_id",
} as const satisfies Record<ListKey, string>;

export function buildGalleryUrl(query: GalleryQuery): string {
  const params = new URLSearchParams();
  const entries = Object.entries(query) as [keyof GalleryQuery, unknown][];
  entries.forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    const paramName =
      (GALLERY_LIST_PARAMS as Partial<Record<keyof GalleryQuery, string>>)[key] ?? key;
    if (Array.isArray(value)) {
      value.forEach((entry) => {
        if (entry === undefined || entry === null || entry === "") return;
        params.append(paramName, String(entry));
      });
      return;
    }
    params.set(paramName, String(value));
  });
  const suffix = params.toString();
  return suffix ? `/api/gallery?${suffix}` : "/api/gallery";
}

export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: () => apiFetch<MeResponse>("/api/auth/me"),
    staleTime: 60_000,
  });
}

export function useGallery(query: GalleryQuery) {
  return useQuery({
    queryKey: ["gallery", query],
    queryFn: () => apiFetch<GalleryResponse>(buildGalleryUrl(query)),
    placeholderData: (previous) => previous,
  });
}

export function useIllust(pid: number | null) {
  return useQuery({
    queryKey: ["illust", pid],
    queryFn: () => apiFetch<IllustDetail>(`/api/illust/${pid}`),
    enabled: pid !== null && Number.isFinite(pid),
  });
}

export function useStats() {
  return useQuery({
    queryKey: ["stats"],
    queryFn: () => apiFetch<StatsOut>("/api/stats"),
  });
}

export function useAuthors(limit = 50) {
  return useQuery({
    queryKey: ["authors", limit],
    queryFn: () => apiFetch<AuthorOut[]>(`/api/authors?limit=${limit}`),
  });
}

export function useTags(limit = 100) {
  return useQuery({
    queryKey: ["tags", limit],
    queryFn: () => apiFetch<TagOut[]>(`/api/tags?limit=${limit}`),
  });
}

const TASK_POLL_INTERVAL = 3000;

export function useTasks() {
  return useQuery({
    queryKey: ["tasks"],
    queryFn: () => apiFetch<TaskOut[]>("/api/tasks"),
    refetchInterval: (query) => {
      const data = query.state.data;
      if (Array.isArray(data) && data.some((task) => task.status === "running")) {
        return TASK_POLL_INTERVAL;
      }
      return false;
    },
  });
}
