import { useDbCheck, usePreviewRepair, useRebuildStats, useRepairDownloadState } from "../api/mutations";

export default function MaintenanceCard() {
  const rebuild = useRebuildStats();
  const preview = usePreviewRepair();
  const repair = useRepairDownloadState();
  const check = useDbCheck();

  return (
    <div className="rounded-lg border border-border-subtle bg-surface-raised p-4 text-sm">
      <div className="mb-2 font-medium">维护</div>
      <p className="mb-3 text-text-muted">
        对数据库与本地文件做一致性检查与修复。重建统计会扫描 works 目录，数据量大时较慢。
      </p>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => rebuild.mutate()}
          disabled={rebuild.isPending}
          className="rounded-md bg-accent px-3 py-1.5 text-white disabled:opacity-50"
        >
          {rebuild.isPending ? "已提交…" : "重建存储统计"}
        </button>
        <button
          type="button"
          onClick={() => preview.mutate()}
          disabled={preview.isPending}
          className="rounded-md border border-border-subtle px-3 py-1.5 disabled:opacity-50"
        >
          预览修复下载状态
        </button>
        <button
          type="button"
          onClick={() => repair.mutate()}
          disabled={repair.isPending}
          className="rounded-md border border-border-subtle px-3 py-1.5 disabled:opacity-50"
        >
          执行修复
        </button>
        <button
          type="button"
          onClick={() => check.mutate()}
          disabled={check.isPending}
          className="rounded-md border border-border-subtle px-3 py-1.5 disabled:opacity-50"
        >
          数据库体检
        </button>
      </div>

      {preview.data ? (
        <div className="mt-3 text-xs text-text-muted">
          预览：{preview.data.works_to_fix} 个作品、{preview.data.pages_to_reset} 页需要修正。
        </div>
      ) : null}

      {check.data ? (
        <div className="mt-3 text-xs">
          {check.data.ok ? (
            <span className="text-emerald-300">体检通过，无异常。</span>
          ) : (
            <ul className="space-y-1 text-amber-300">
              {check.data.issues.map((issue) => (
                <li key={issue.kind}>
                  {issue.kind}：{issue.count} 例（样本 {issue.samples.join(", ")}）
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}

      {rebuild.isError || repair.isError || check.isError ? (
        <div className="mt-3 text-xs text-red-400">操作失败，请查看任务页或服务日志。</div>
      ) : null}
    </div>
  );
}
