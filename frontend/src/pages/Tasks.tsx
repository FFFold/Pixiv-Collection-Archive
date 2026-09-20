import { useStartSync } from "../api/mutations";
import TaskPanel from "../components/TaskPanel";

export default function Tasks() {
  const sync = useStartSync();

  return (
    <div className="min-h-full">
      <div className="flex flex-wrap items-center gap-3 border-b border-border-subtle px-6 py-4">
        <h1 className="text-base font-semibold">任务</h1>
        <div className="flex-1" />
        <button
          type="button"
          onClick={() => sync.mutate("incremental")}
          disabled={sync.isPending}
          className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        >
          增量同步
        </button>
        <button
          type="button"
          onClick={() => sync.mutate("full")}
          disabled={sync.isPending}
          className="rounded-md border border-border-subtle px-3 py-1.5 text-sm disabled:opacity-50"
        >
          全量同步
        </button>
      </div>
      {sync.isError ? (
        <div className="mx-6 mt-4 rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          启动失败：{sync.error instanceof Error ? sync.error.message : "未知错误"}
        </div>
      ) : null}
      <TaskPanel />
    </div>
  );
}
