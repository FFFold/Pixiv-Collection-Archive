import { useEffect, useState } from "react";

import { PAGE_SIZE_OPTIONS } from "../lib/constants";

interface Props {
  offset: number;
  limit: number;
  total: number;
  onChange: (offset: number) => void;
  onLimitChange?: (limit: number) => void;
}

const NAV_KEYS = new Set(["ArrowLeft", "ArrowRight"]);

export default function Pagination({
  offset,
  limit,
  total,
  onChange,
  onLimitChange,
}: Props) {
  const pageCount = Math.max(1, Math.ceil(total / limit));
  const currentPage = Math.min(pageCount, Math.floor(offset / limit) + 1);
  const [pageInput, setPageInput] = useState(String(currentPage));

  useEffect(() => setPageInput(String(currentPage)), [currentPage]);

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (!NAV_KEYS.has(event.key)) return;
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName ?? "";
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (event.key === "ArrowRight" && offset + limit < total) {
        onChange(offset + limit);
      }
      if (event.key === "ArrowLeft" && offset > 0) {
        onChange(Math.max(0, offset - limit));
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [offset, limit, total, onChange]);

  const start = total === 0 ? 0 : Math.min(offset + 1, total);
  const end = Math.min(offset + limit, total);
  const hasPrevious = offset > 0;
  const hasNext = offset + limit < total;
  const lastOffset = Math.max(0, (pageCount - 1) * limit);

  const jumpToPage = () => {
    const parsed = Number(pageInput);
    if (!Number.isFinite(parsed)) {
      setPageInput(String(currentPage));
      return;
    }
    const clamped = Math.min(pageCount, Math.max(1, Math.trunc(parsed)));
    setPageInput(String(clamped));
    onChange((clamped - 1) * limit);
  };

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 py-4 text-sm text-text-muted">
      <span>
        {start}–{end} / 共 {total}
      </span>
      <div className="flex flex-wrap items-center gap-2">
        {onLimitChange ? (
          <label className="flex items-center gap-1.5">
            每页
            <select
              aria-label="每页数量"
              value={limit}
              onChange={(event) => onLimitChange(Number(event.target.value))}
              className="rounded-md border border-border-subtle bg-surface-raised px-2 py-1.5"
            >
              {PAGE_SIZE_OPTIONS.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <button
          type="button"
          disabled={!hasPrevious}
          onClick={() => onChange(0)}
          className="rounded-md border border-border-subtle px-3 py-1.5 disabled:opacity-40"
        >
          首页
        </button>
        <button
          type="button"
          disabled={!hasPrevious}
          onClick={() => onChange(Math.max(0, offset - limit))}
          className="rounded-md border border-border-subtle px-3 py-1.5 disabled:opacity-40"
        >
          上一页
        </button>
        <label className="flex items-center gap-1.5">
          第
          <input
            aria-label="页码"
            value={pageInput}
            onChange={(event) => setPageInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") jumpToPage();
            }}
            onBlur={() => setPageInput(String(currentPage))}
            className="w-14 rounded-md border border-border-subtle bg-surface-raised px-2 py-1.5 text-center"
          />
          / {pageCount} 页
        </label>
        <button
          type="button"
          disabled={!hasNext}
          onClick={() => onChange(offset + limit)}
          className="rounded-md border border-border-subtle px-3 py-1.5 disabled:opacity-40"
        >
          下一页
        </button>
        <button
          type="button"
          disabled={!hasNext}
          onClick={() => onChange(lastOffset)}
          className="rounded-md border border-border-subtle px-3 py-1.5 disabled:opacity-40"
        >
          末页
        </button>
      </div>
    </div>
  );
}
