import { useCallback, useEffect, useState } from "react";

import type { IllustPageOut } from "../api/types";

interface Props {
  pid: number;
  pages: IllustPageOut[];
  initialPage: number;
  animationAvailable?: boolean;
  onClose: () => void;
}

export default function Lightbox({
  pid,
  pages,
  initialPage,
  animationAvailable = false,
  onClose,
}: Props) {
  const [page, setPage] = useState(initialPage);
  const [zoom, setZoom] = useState(1);

  const total = pages.length;
  const goNext = useCallback(() => setPage((current) => (current + 1) % total), [total]);
  const goPrevious = useCallback(
    () => setPage((current) => (current - 1 + total) % total),
    [total],
  );

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key === "ArrowRight") goNext();
      if (event.key === "ArrowLeft") goPrevious();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [goNext, goPrevious, onClose]);

  const currentDownloaded = pages[page]?.download_state === "done";

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-black/90">
      <div className="flex items-center justify-between px-4 py-3 text-sm text-text-muted">
        <span>
          {animationAvailable ? "动图" : `${page + 1} / ${total}`}
          {!animationAvailable && !currentDownloaded ? "（原图未下载）" : ""}
        </span>
        <div className="flex items-center gap-2">
          {!animationAvailable ? (
            <>
              <button
                type="button"
                onClick={() => setZoom((z) => Math.max(0.5, z - 0.25))}
                className="rounded border border-white/20 px-2 py-1"
              >
                缩小
              </button>
              <button
                type="button"
                onClick={() => setZoom((z) => Math.min(4, z + 0.25))}
                className="rounded border border-white/20 px-2 py-1"
              >
                放大
              </button>
            </>
          ) : null}
          <a
            href={
              animationAvailable
                ? `/api/illust/${pid}/animation`
                : `/api/illust/${pid}/file/${page}`
            }
            className="rounded border border-white/20 px-2 py-1 hover:border-white/50"
            download
          >
            下载
          </a>
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-white/20 px-2 py-1 hover:border-white/50"
          >
            关闭
          </button>
        </div>
      </div>

      <div className="relative flex flex-1 items-center justify-center overflow-auto p-4">
        {animationAvailable ? (
          <video
            data-testid="ugoira-video"
            src={`/api/illust/${pid}/animation`}
            controls
            autoPlay
            loop
            className="max-h-full max-w-full"
          />
        ) : (
          <img
            src={`/api/illust/${pid}/file/${page}`}
            alt={`page ${page + 1}`}
            style={{ transform: `scale(${zoom})` }}
            className="max-h-full max-w-full origin-center transition-transform"
          />
        )}

        {!animationAvailable && total > 1 ? (
          <>
            <button
              type="button"
              aria-label="上一页"
              onClick={goPrevious}
              className="absolute left-3 top-1/2 -translate-y-1/2 rounded-full bg-black/60 px-3 py-4 text-white hover:bg-black/80"
            >
              ‹
            </button>
            <button
              type="button"
              aria-label="下一页"
              onClick={goNext}
              className="absolute right-3 top-1/2 -translate-y-1/2 rounded-full bg-black/60 px-3 py-4 text-white hover:bg-black/80"
            >
              ›
            </button>
          </>
        ) : null}
      </div>
    </div>
  );
}
