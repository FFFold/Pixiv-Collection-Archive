import { useEffect, useState } from "react";

import type { GalleryQuery } from "../api/types";
import { useSelection } from "../contexts/SelectionContext";
import FilterPickers from "./FilterPickers";
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
  pagePids: number[];
  undownloadedPids: number[];
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

function RangeInputs({
  ariaLabel,
  minValue,
  maxValue,
  onApply,
}: {
  ariaLabel: string;
  minValue?: number;
  maxValue?: number;
  onApply: (min?: number, max?: number) => void;
}) {
  const [min, setMin] = useState(minValue === undefined ? "" : String(minValue));
  const [max, setMax] = useState(maxValue === undefined ? "" : String(maxValue));

  useEffect(() => {
    setMin(minValue === undefined ? "" : String(minValue));
    setMax(maxValue === undefined ? "" : String(maxValue));
  }, [minValue, maxValue]);

  const apply = () => {
    const parse = (raw: string) => {
      if (raw.trim() === "") return undefined;
      const value = Number(raw);
      return Number.isFinite(value) ? value : undefined;
    };
    onApply(parse(min), parse(max));
  };
  return (
    <span className="flex items-center gap-1 text-xs text-text-muted">
      {ariaLabel}
      <input
        aria-label={`${ariaLabel}最小值`}
        value={min}
        onChange={(event) => setMin(event.target.value)}
        onBlur={apply}
        onKeyDown={(event) => {
          if (event.key === "Enter") apply();
        }}
        className="w-16 rounded-md border border-border-subtle bg-surface-raised px-2 py-1.5 text-sm"
      />
      <span>–</span>
      <input
        aria-label={`${ariaLabel}最大值`}
        value={max}
        onChange={(event) => setMax(event.target.value)}
        onBlur={apply}
        onKeyDown={(event) => {
          if (event.key === "Enter") apply();
        }}
        className="w-16 rounded-md border border-border-subtle bg-surface-raised px-2 py-1.5 text-sm"
      />
    </span>
  );
}

export default function Toolbar({
  query,
  onChange,
  pagePids,
  undownloadedPids,
  onDownloadSelected,
  onDownloadAllMissing,
  downloadPending,
}: Props) {
  const selection = useSelection();
  const [panelOpen, setPanelOpen] = useState(false);
  const filterCount = [
    query.tags?.length,
    query.author_ids?.length,
    query.q,
    query.type,
    query.x_restrict !== undefined ? 1 : undefined,
    query.downloaded !== undefined ? 1 : undefined,
    query.restrict,
    query.page_min ?? query.page_max,
    query.bookmarks_min ?? query.bookmarks_max,
    query.views_min ?? query.views_max,
    query.only_unbookmarked,
    query.only_deleted || query.include_deleted,
  ].filter(
    (value) =>
      value !== undefined && value !== null && value !== false && value !== "" && value !== 0,
  ).length;

  return (
    <div className="sticky top-0 z-20 space-y-2 border-b border-border-subtle bg-surface/95 px-4 py-3 backdrop-blur">
      <div className="flex flex-wrap items-center gap-2">
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
          onChange={(value) =>
            onChange({
              only_deleted: value === "deleted" ? true : undefined,
              include_deleted: value === "all" ? true : undefined,
              offset: 0,
            })
          }
        />
        <Select
          ariaLabel="页数预设"
          value={
            query.page_min === 1 && query.page_max === 1
              ? "1"
              : query.page_min === 2 && query.page_max === 5
                ? "2-5"
                : query.page_min === 6 && query.page_max === 10
                  ? "6-10"
                  : query.page_min === 11 && query.page_max === undefined
                    ? "11+"
                    : ""
          }
          options={[
            { value: "", label: "全部页数" },
            { value: "1", label: "1P" },
            { value: "2-5", label: "2–5P" },
            { value: "6-10", label: "6–10P" },
            { value: "11+", label: "11P+" },
          ]}
          onChange={(value) => {
            const preset: Record<string, Partial<GalleryQuery>> = {
              "": { page_min: undefined, page_max: undefined },
              "1": { page_min: 1, page_max: 1 },
              "2-5": { page_min: 2, page_max: 5 },
              "6-10": { page_min: 6, page_max: 10 },
              "11+": { page_min: 11, page_max: undefined },
            };
            onChange({ ...preset[value], offset: 0 });
          }}
        />
        <RangeInputs
          ariaLabel="页数自定义"
          minValue={query.page_min}
          maxValue={query.page_max}
          onApply={(min, max) => onChange({ page_min: min, page_max: max, offset: 0 })}
        />
        <RangeInputs
          ariaLabel="收藏"
          minValue={query.bookmarks_min}
          maxValue={query.bookmarks_max}
          onApply={(min, max) =>
            onChange({ bookmarks_min: min, bookmarks_max: max, offset: 0 })
          }
        />
        <RangeInputs
          ariaLabel="浏览"
          minValue={query.views_min}
          maxValue={query.views_max}
          onApply={(min, max) => onChange({ views_min: min, views_max: max, offset: 0 })}
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
      </div>

      <FilterPickers
        tags={query.tags ?? []}
        authorIds={query.author_ids ?? []}
        onChange={onChange}
      />

      <div className="flex flex-wrap items-center gap-2 text-sm">
        <button
          type="button"
          onClick={() => selection.selectMany(pagePids)}
          disabled={pagePids.length === 0}
          className="rounded-md border border-border-subtle px-3 py-1.5 disabled:opacity-40"
        >
          全选本页
        </button>
        <button
          type="button"
          onClick={() => selection.removeMany(pagePids)}
          disabled={pagePids.length === 0}
          className="rounded-md border border-border-subtle px-3 py-1.5 disabled:opacity-40"
        >
          取消本页
        </button>
        <button
          type="button"
          onClick={() => {
            const toRemove = pagePids.filter((pid) => selection.selected.has(pid));
            const toAdd = pagePids.filter((pid) => !selection.selected.has(pid));
            selection.removeMany(toRemove);
            selection.selectMany(toAdd);
          }}
          disabled={pagePids.length === 0}
          className="rounded-md border border-border-subtle px-3 py-1.5 disabled:opacity-40"
        >
          反选本页
        </button>
        <button
          type="button"
          onClick={() => selection.selectMany(undownloadedPids)}
          disabled={undownloadedPids.length === 0}
          className="rounded-md border border-border-subtle px-3 py-1.5 disabled:opacity-40"
        >
          仅选本页未下载
        </button>

        <button
          type="button"
          onClick={() => setPanelOpen((open) => !open)}
          disabled={selection.count === 0}
          className="rounded-md border border-border-subtle px-3 py-1.5 disabled:opacity-40"
        >
          已选 {selection.count}
        </button>
        {panelOpen ? (
          <div className="flex flex-wrap items-center gap-2 text-xs text-text-muted">
            <span>已选 {selection.count} 项（跨页累积）</span>
            <button
              type="button"
              onClick={() => selection.removeMany(pagePids)}
              className="rounded border border-border-subtle px-2 py-0.5"
            >
              移除本页选中
            </button>
            <button
              type="button"
              onClick={selection.clear}
              className="rounded border border-border-subtle px-2 py-0.5"
            >
              清空
            </button>
          </div>
        ) : null}

        <div className="flex-1" />
        {filterCount > 0 ? (
          <button
            type="button"
            onClick={() =>
              onChange({
                tags: undefined,
                author_ids: undefined,
                q: undefined,
                type: undefined,
                x_restrict: undefined,
                downloaded: undefined,
                restrict: undefined,
                page_min: undefined,
                page_max: undefined,
                bookmarks_min: undefined,
                bookmarks_max: undefined,
                views_min: undefined,
                views_max: undefined,
                only_unbookmarked: undefined,
                only_deleted: undefined,
                include_deleted: undefined,
                offset: 0,
              })
            }
            className="rounded-md border border-border-subtle px-3 py-1.5 text-xs"
          >
            清空筛选（{filterCount}）
          </button>
        ) : null}
        <button
          type="button"
          onClick={onDownloadSelected}
          disabled={selection.count === 0 || downloadPending}
          className="rounded-md border border-border-subtle px-3 py-1.5 disabled:opacity-40"
        >
          下载选中 ({selection.count})
        </button>
        <button
          type="button"
          onClick={onDownloadAllMissing}
          disabled={downloadPending}
          className="rounded-md bg-accent px-3 py-1.5 font-medium text-white disabled:opacity-40"
        >
          下载全部未下载
        </button>
      </div>
    </div>
  );
}
