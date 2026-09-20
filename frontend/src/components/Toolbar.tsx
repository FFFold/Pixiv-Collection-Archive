import type { GalleryQuery } from "../api/types";
import {
  DOWNLOAD_OPTIONS,
  R18_OPTIONS,
  RESTRICT_OPTIONS,
  SORT_OPTIONS,
  STATUS_OPTIONS,
  TYPE_OPTIONS,
} from "../lib/constants";

interface Props {
  query: GalleryQuery;
  onChange: (patch: Partial<GalleryQuery>) => void;
  selectedCount: number;
  onDownloadSelected: () => void;
  onDownloadAllMissing: () => void;
  downloadPending: boolean;
}

function Select({
  value,
  options,
  onChange,
  ariaLabel,
}: {
  value: string;
  options: readonly { value: string; label: string }[];
  onChange: (value: string) => void;
  ariaLabel: string;
}) {
  return (
    <select
      aria-label={ariaLabel}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className="rounded-md border border-border-subtle bg-surface-raised px-2 py-1.5 text-sm outline-none focus:border-accent"
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

export default function Toolbar({
  query,
  onChange,
  selectedCount,
  onDownloadSelected,
  onDownloadAllMissing,
  downloadPending,
}: Props) {
  return (
    <div className="sticky top-0 z-20 flex flex-wrap items-center gap-2 border-b border-border-subtle bg-surface/95 px-4 py-3 backdrop-blur">
      <Select
        ariaLabel="排序"
        value={query.sort ?? "rank"}
        options={SORT_OPTIONS}
        onChange={(value) => onChange({ sort: value as GalleryQuery["sort"], offset: 0 })}
      />
      <Select
        ariaLabel="类型"
        value={query.type ?? ""}
        options={TYPE_OPTIONS}
        onChange={(value) =>
          onChange({ type: (value || undefined) as GalleryQuery["type"], offset: 0 })
        }
      />
      <Select
        ariaLabel="下载状态"
        value={query.downloaded === undefined ? "" : query.downloaded ? "yes" : "no"}
        options={DOWNLOAD_OPTIONS}
        onChange={(value) =>
          onChange({
            downloaded: value === "" ? undefined : value === "yes",
            offset: 0,
          })
        }
      />
      <Select
        ariaLabel="收藏夹"
        value={query.restrict ?? ""}
        options={RESTRICT_OPTIONS}
        onChange={(value) =>
          onChange({
            restrict: (value || undefined) as GalleryQuery["restrict"],
            offset: 0,
          })
        }
      />
      <Select
        ariaLabel="分级"
        value={query.x_restrict === undefined ? "" : String(query.x_restrict)}
        options={R18_OPTIONS}
        onChange={(value) =>
          onChange({
            x_restrict: value === "" ? undefined : Number(value),
            offset: 0,
          })
        }
      />
      <Select
        ariaLabel="状态"
        value={query.only_deleted ? "deleted" : query.include_deleted ? "all" : "active"}
        options={STATUS_OPTIONS}
        onChange={(value) => {
          const patch: Partial<GalleryQuery> = {
            only_deleted: value === "deleted" ? true : undefined,
            include_deleted: value === "all" ? true : undefined,
            offset: 0,
          };
          if (value === "active") {
            delete patch.only_deleted;
            delete patch.include_deleted;
          }
          onChange(patch);
        }}
      />

      <input
        type="search"
        placeholder="搜索标题或画师（回车）"
        defaultValue={query.q ?? ""}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            onChange({ q: event.currentTarget.value || undefined, offset: 0 });
          }
        }}
        className="min-w-[180px] flex-1 rounded-md border border-border-subtle bg-surface-raised px-3 py-1.5 text-sm outline-none focus:border-accent"
      />

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onDownloadSelected}
          disabled={selectedCount === 0 || downloadPending}
          className="rounded-md border border-border-subtle px-3 py-1.5 text-sm disabled:opacity-40"
        >
          下载选中 ({selectedCount})
        </button>
        <button
          type="button"
          onClick={onDownloadAllMissing}
          disabled={downloadPending}
          className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40"
        >
          下载全部未下载
        </button>
      </div>
    </div>
  );
}
