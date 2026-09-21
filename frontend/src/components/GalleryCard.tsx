import { Link } from "react-router-dom";

import type { GalleryItem } from "../api/types";
import { formatIndex } from "../lib/format";

interface Props {
  item: GalleryItem;
  selected: boolean;
  onToggle: (pid: number) => void;
}

export default function GalleryCard({ item, selected, onToggle }: Props) {
  const downloaded = item.has_original;

  return (
    <div className="group relative overflow-hidden rounded-lg border border-border-subtle bg-surface-raised">
      <label className="absolute left-2 top-2 z-10 flex h-5 w-5 cursor-pointer items-center justify-center rounded bg-black/60">
        <input
          type="checkbox"
          aria-label={`选择 ${item.pid}`}
          checked={selected}
          onChange={() => onToggle(item.pid)}
          className="h-3.5 w-3.5 accent-accent"
        />
      </label>

      <Link to={`/illust/${item.pid}`} className="block">
        <img
          src={item.thumb_url}
          alt={item.title}
          loading="lazy"
          data-fallback="false"
          onError={(event) => {
            const image = event.currentTarget;
            if (image.dataset.fallback === "true") return;
            image.dataset.fallback = "true";
            image.src =
              "data:image/svg+xml;utf8," +
              encodeURIComponent(
                '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="400">' +
                  '<rect width="100%" height="100%" fill="#1d2531"/>' +
                  '<text x="50%" y="50%" fill="#9aa4b2" font-family="sans-serif" ' +
                  'font-size="16" text-anchor="middle">图片不可用</text></svg>',
              );
          }}
          className="w-full bg-surface object-cover transition-opacity group-hover:opacity-90"
        />
      </Link>

      <div className="space-y-1 p-2">
        <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-text-muted">
          <span className="rounded bg-surface-hover px-1.5 py-0.5 text-text-primary">
            {formatIndex(item.index)}
          </span>
          {item.page_count > 1 ? (
            <span className="rounded bg-surface-hover px-1.5 py-0.5">{item.page_count}P</span>
          ) : null}
          {item.type === "ugoira" ? (
            <span className="rounded bg-surface-hover px-1.5 py-0.5">动图</span>
          ) : null}
          {item.x_restrict > 0 ? (
            <span className="rounded bg-red-500/20 px-1.5 py-0.5 text-red-300">R-18</span>
          ) : null}
          {downloaded ? (
            <span className="rounded bg-emerald-500/20 px-1.5 py-0.5 text-emerald-300">
              已下载
            </span>
          ) : (
            <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-amber-300">
              未下载
            </span>
          )}
        </div>
        <div className="truncate text-xs text-text-primary" title={item.title}>
          {item.title}
        </div>
        <div className="truncate text-[11px] text-text-muted">{item.author_name}</div>
      </div>
    </div>
  );
}
