import { useState } from "react";

import { useCancelTask } from "../api/mutations";
import { useTasks } from "../api/queries";
import { useEventStream } from "../api/sse";
import type { TaskOut } from "../api/types";
import { formatDateTime } from "../lib/format";

function statusStyle(status: string): string {
  switch (status) {
    case "running":
      return "bg-blue-500/20 text-blue-300";
    case "completed":
      return "bg-emerald-500/20 text-emerald-300";
    case "failed":
      return "bg-red-500/20 text-red-300";
    case "cancelled":
      return "bg-amber-500/20 text-amber-300";
    default:
      return "bg-surface-hover text-text-muted";
  }
}

const KIND_LABELS: Record<string, string> = {
  sync: "元数据同步",
  download: "图片下载",
  export: "导出",
};

function detailSummary(task: TaskOut): string {
  const detail = task.detail ?? {};
  if (task.kind === "sync") {
    return `新增 ${detail.new_count ?? 0} · 页 ${detail.pages_fetched ?? 0} · 预览 ${detail.previews_fetched ?? 0}`;
  }
  if (task.kind === "download") {
    return `页 ${detail.pages_done ?? 0} · 缩略图 ${detail.thumbs_done ?? 0} · 失败 ${detail.failed ?? 0}`;
  }
  if (task.kind === "export") {
    return `作品 ${detail.pids ?? 0} · 文件 ${detail.files ?? 0}`;
  }
  return "";
}

interface ProgressState {
  done: number;
  total: number;
  message: string;
}

export default function TaskPanel() {
  const { data: tasks, refetch } = useTasks();
  const cancel = useCancelTask();
  const [progress, setProgress] = useState<Record<string, ProgressState>>({});

  const { connected } = useEventStream(true, (event) => {
    const taskId = String(event.payload.task_id ?? "");
    if (!taskId) return;
    if (event.type === "progress") {
      setProgress((current) => ({
        ...current,
        [taskId]: {
          done: Number(event.payload.done ?? 0),
          total: Number(event.payload.total ?? 0),
          message: String(event.payload.message ?? ""),
        },
      }));
    } else if (event.type === "task") {
      void refetch();
    }
  });

  return (
    <div className="space-y-4 p-6">
      <div className="flex items-center gap-2 text-xs text-text-muted">
        <span
          className={`inline-block h-2 w-2 rounded-full ${
            connected ? "bg-emerald-400" : "bg-red-400"
          }`}
        />
        {connected ? "实时连接正常" : "实时连接断开，进度可能不同步"}
      </div>

      {(tasks ?? []).length === 0 ? (
        <div className="rounded-lg border border-border-subtle bg-surface-raised p-6 text-sm text-text-muted">
          还没有任务记录。
        </div>
      ) : (
        <div className="space-y-2">
          {(tasks ?? []).map((task) => {
            const live = progress[task.id];
            const percent =
              live && live.total > 0 ? Math.min(100, (live.done / live.total) * 100) : null;
            return (
              <div
                key={task.id}
                className="rounded-lg border border-border-subtle bg-surface-raised p-4"
              >
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">
                      {KIND_LABELS[task.kind] ?? task.kind}
                    </span>
                    <span className={`rounded px-2 py-0.5 text-xs ${statusStyle(task.status)}`}>
                      {task.status}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-text-muted">
                    <span>{formatDateTime(task.started_at)}</span>
                    {task.status === "running" ? (
                      <button
                        type="button"
                        onClick={() => cancel.mutate(task.id)}
                        className="rounded border border-border-subtle px-2 py-0.5 hover:border-red-400 hover:text-red-300"
                      >
                        取消
                      </button>
                    ) : null}
                  </div>
                </div>

                {percent !== null ? (
                  <div className="mt-3">
                    <div className="h-1.5 w-full overflow-hidden rounded bg-surface-hover">
                      <div
                        className="h-full bg-accent transition-all"
                        style={{ width: `${percent}%` }}
                      />
                    </div>
                    <div className="mt-1 text-xs text-text-muted">
                      {live.message} ({live.done}/{live.total})
                    </div>
                  </div>
                ) : null}

                <div className="mt-2 text-xs text-text-muted">{detailSummary(task)}</div>
                {task.error ? (
                  <div className="mt-2 text-xs text-red-400">{task.error}</div>
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
