import { useState } from "react";

import { useStartExport } from "../api/mutations";
import { useStats } from "../api/queries";
import type { ExportRequest, GalleryQuery } from "../api/types";
import { useGalleryFilters } from "../contexts/GalleryFiltersContext";
import { useSelection } from "../contexts/SelectionContext";

type Scope = "all" | "filter" | "selected";

const FILTER_KEYS: (keyof GalleryQuery)[] = [
  "tags",
  "author_ids",
  "q",
  "type",
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
];

export default function Export() {
  const stats = useStats();
  const start = useStartExport();
  const { filters } = useGalleryFilters();
  const selection = useSelection();
  const [scope, setScope] = useState<Scope>("all");
  const [includeOriginals, setIncludeOriginals] = useState(false);
  const [includeMetadata, setIncludeMetadata] = useState(true);
  const [onlyDownloaded, setOnlyDownloaded] = useState(true);
  const [r18, setR18] = useState<"" | "0" | "1">("");
  const [groupByAuthor, setGroupByAuthor] = useState(false);
  const [filename, setFilename] = useState<string | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const payload: ExportRequest = {
      include_metadata: includeMetadata,
      include_originals: includeOriginals,
      only_downloaded: onlyDownloaded,
      x_restrict: r18 === "" ? undefined : Number(r18),
      group_by_author: groupByAuthor,
    };
    if (scope === "selected") {
      payload.pids = Array.from(selection.selected);
    } else if (scope === "filter") {
      payload.use_filter = true;
      FILTER_KEYS.forEach((key) => {
        const value = filters[key];
        if (value === undefined) return;
        Object.assign(payload, { [key]: value });
      });
      if (payload.x_restrict === undefined && filters.x_restrict !== undefined) {
        payload.x_restrict = filters.x_restrict;
      }
    }
    start.mutate(payload, {
      onSuccess: (response) => {
        setFilename(response.filename);
        setTaskId(response.task_id);
      },
    });
  };

  return (
    <div className="max-w-xl space-y-5 p-6">
      <h1 className="text-base font-semibold">导出</h1>
      <p className="text-sm text-text-muted">
        按条件打包下载。当前已下载{" "}
        {stats.data?.downloaded_pages.toLocaleString() ?? "…"} 页。
      </p>

      <form
        onSubmit={submit}
        className="space-y-3 rounded-lg border border-border-subtle bg-surface-raised p-4"
      >
        <fieldset className="space-y-2">
          <legend className="text-sm text-text-muted">范围</legend>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="scope"
              checked={scope === "all"}
              onChange={() => setScope("all")}
              className="accent-accent"
            />
            全部 / 条件
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="scope"
              checked={scope === "filter"}
              onChange={() => setScope("filter")}
              className="accent-accent"
            />
            按当前筛选
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="scope"
              checked={scope === "selected"}
              disabled={selection.count === 0}
              onChange={() => setScope("selected")}
              className="accent-accent"
            />
            按选中 ({selection.count})
          </label>
        </fieldset>

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={includeMetadata}
            onChange={(event) => setIncludeMetadata(event.target.checked)}
            className="accent-accent"
          />
          包含元数据 JSON
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={includeOriginals}
            onChange={(event) => setIncludeOriginals(event.target.checked)}
            className="accent-accent"
          />
          包含原图文件（体积可能很大）
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={onlyDownloaded}
            onChange={(event) => setOnlyDownloaded(event.target.checked)}
            className="accent-accent"
          />
          仅包含已下载的作品
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={groupByAuthor}
            onChange={(event) => setGroupByAuthor(event.target.checked)}
            className="accent-accent"
          />
          按作者分组目录
        </label>
        <label className="flex items-center gap-2 text-sm">
          <span className="text-text-muted">分级</span>
          <select
            value={r18}
            onChange={(event) => setR18(event.target.value as typeof r18)}
            className="rounded-md border border-border-subtle bg-surface px-2 py-1.5"
          >
            <option value="">不限</option>
            <option value="0">仅全年龄</option>
            <option value="1">仅 R-18</option>
          </select>
        </label>

        <button
          type="submit"
          disabled={start.isPending || (!includeMetadata && !includeOriginals)}
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {start.isPending ? "创建导出任务…" : "开始导出"}
        </button>
      </form>

      {start.isError ? (
        <div className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          {start.error instanceof Error ? start.error.message : "导出失败"}
        </div>
      ) : null}

      {filename && taskId ? (
        <div className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-3 text-sm">
          <div className="text-emerald-300">导出任务已创建：{filename}</div>
          <div className="mt-2 flex gap-3">
            <a className="underline" href={`/api/export/${taskId}/download`}>
              下载压缩包
            </a>
            <a className="underline" href="/tasks">
              查看进度
            </a>
          </div>
        </div>
      ) : null}
    </div>
  );
}
