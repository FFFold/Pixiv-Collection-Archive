import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "./client";
import type {
  DbCheckReport,
  DownloadRequest,
  ExportRequest,
  ExportResponse,
  MaintenancePreview,
  MeResponse,
  TaskOut,
} from "./types";

export function useLogin() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (token: string) =>
      apiFetch<MeResponse>("/api/auth/login", { method: "POST", body: { token } }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["me"] });
    },
  });
}

export function useLogout() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<MeResponse>("/api/auth/logout", { method: "POST" }),
    onSuccess: () => {
      client.clear();
    },
  });
}

export function useStartSync() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (mode: "incremental" | "full") =>
      apiFetch<TaskOut>("/api/sync", { method: "POST", body: { mode } }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["tasks"] });
      void client.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}

export function useStartDownload() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: DownloadRequest) =>
      apiFetch<TaskOut>("/api/downloads", { method: "POST", body: payload }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
}

export function useCancelTask() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (taskId: string) =>
      apiFetch<TaskOut>(`/api/tasks/${taskId}/cancel`, { method: "POST" }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
}

export function useStartExport() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: ExportRequest) =>
      apiFetch<ExportResponse>("/api/export", { method: "POST", body: payload }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
}

export function useRebuildStats() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<TaskOut>("/api/maintenance/rebuild-stats", { method: "POST" }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["tasks"] });
      void client.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}

export function usePreviewRepair() {
  return useMutation({
    mutationFn: () =>
      apiFetch<MaintenancePreview>("/api/maintenance/repair-download-state/preview"),
  });
}

export function useRepairDownloadState() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<TaskOut>("/api/maintenance/repair-download-state", { method: "POST" }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["tasks"] });
      void client.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}

export function useDbCheck() {
  return useMutation({
    mutationFn: () => apiFetch<DbCheckReport>("/api/maintenance/db-check", { method: "POST" }),
  });
}
