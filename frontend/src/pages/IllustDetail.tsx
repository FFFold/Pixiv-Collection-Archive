import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { useStartDownload } from "../api/mutations";
import { useIllust } from "../api/queries";
import Lightbox from "../components/Lightbox";
import { formatDate, formatIndex } from "../lib/format";

export default function IllustDetail() {
  const params = useParams();
  const pid = params.pid ? Number(params.pid) : null;
  const navigate = useNavigate();
  const { data, isLoading, isError } = useIllust(pid);
  const download = useStartDownload();
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  if (isLoading) {
    return <div className="p-6 text-sm text-text-muted">加载中…</div>;
  }
  if (isError || !data) {
    return (
      <div className="p-6 text-sm text-red-400">
        作品不存在或加载失败。
        <button type="button" onClick={() => navigate(-1)} className="ml-2 underline">
          返回
        </button>
      </div>
    );
  }

  const missingPages = data.page_count - data.page_downloaded_count;
  const viewerAvailable = data.page_downloaded_count > 0 || data.animation_available;

  const requestDownload = () => {
    download.mutate(
      { scope: "selected", pids: [data.pid], with_thumbs: true },
      { onSuccess: () => setNotice("已加入下载队列") },
    );
  };

  return (
    <div className="grid gap-6 p-6 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div>
        <button
          type="button"
          onClick={() => setLightboxOpen(true)}
          disabled={!viewerAvailable}
          className="block w-full overflow-hidden rounded-lg border border-border-subtle disabled:cursor-not-allowed"
        >
          <img
            src={`/api/illust/${data.pid}/thumb`}
            alt={data.title}
            className="w-full object-contain"
          />
        </button>
        <p className="mt-2 text-xs text-text-muted">
          {viewerAvailable
            ? `点击打开查看器（${data.page_count} 页${data.animation_available ? " · 动图" : ""}）`
            : "原图尚未下载，可先加入下载队列"}
        </p>
      </div>

      <aside className="space-y-4">
        <div>
          <div className="mb-1 text-xs text-text-muted">{formatIndex(data.index)}</div>
          <h1 className="text-lg font-semibold leading-snug">{data.title}</h1>
          <p className="mt-1 text-sm text-text-muted">
            <Link
              to={`/?author=${data.author_id}`}
              className="hover:text-text-primary"
            >
              {data.author_name}
            </Link>
            {data.author_account ? ` @${data.author_account}` : ""}
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          {data.unbookmarked ? (
            <span className="rounded bg-amber-500/20 px-2 py-0.5 text-xs text-amber-300">
              已取消收藏
            </span>
          ) : null}
          <span className="rounded bg-surface-hover px-2 py-0.5 text-xs">
            {data.restrict === "private" ? "私密收藏" : "公开收藏"}
          </span>
          {data.x_restrict > 0 ? (
            <span className="rounded bg-red-500/20 px-2 py-0.5 text-xs text-red-300">
              R-18
            </span>
          ) : null}
          {data.type === "ugoira" ? (
            <span className="rounded bg-surface-hover px-2 py-0.5 text-xs">
              动图{data.frame_count ? ` ${data.frame_count} 帧` : ""}
            </span>
          ) : null}
        </div>

        <dl className="space-y-1.5 text-sm">
          <div className="flex justify-between">
            <dt className="text-text-muted">发布时间</dt>
            <dd>{formatDate(data.create_date)}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-text-muted">尺寸</dt>
            <dd>
              {data.width} × {data.height}
            </dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-text-muted">收藏 / 浏览</dt>
            <dd>
              {data.total_bookmarks} / {data.total_view}
            </dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-text-muted">已下载页</dt>
            <dd>
              {data.page_downloaded_count} / {data.page_count}
            </dd>
          </div>
        </dl>

        {notice ? (
          <div className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
            {notice}
          </div>
        ) : null}

        <div className="flex flex-col gap-2">
          {missingPages > 0 ? (
            <button
              type="button"
              onClick={requestDownload}
              disabled={download.isPending}
              className="rounded-md bg-accent px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {download.isPending ? "提交中…" : `下载缺失的 ${missingPages} 页`}
            </button>
          ) : (
            <span className="text-center text-xs text-emerald-400">已完整下载</span>
          )}
          <a
            href={data.pixiv_url}
            target="_blank"
            rel="noreferrer"
            className="rounded-md border border-border-subtle px-3 py-2 text-center text-sm hover:border-accent"
          >
            在 pixiv 打开
          </a>
          {data.animation_available ? (
            <a
              href={`/api/illust/${data.pid}/animation`}
              download
              className="rounded-md border border-border-subtle px-3 py-2 text-center text-sm hover:border-accent"
            >
              下载动图 mp4
            </a>
          ) : null}
          {data.type === "ugoira" ? (
            <a
              href={`/api/illust/${data.pid}/ugoira.zip`}
              download
              className="rounded-md border border-border-subtle px-3 py-2 text-center text-sm hover:border-accent"
            >
              下载原始帧 zip
            </a>
          ) : null}
        </div>

        {data.tags.length > 0 ? (
          <div>
            <div className="mb-1.5 text-xs text-text-muted">标签</div>
            <div className="flex flex-wrap gap-1.5">
              {data.tags.map((tag, index) => (
                <Link
                  key={tag}
                  to={`/?tag=${encodeURIComponent(tag)}`}
                  title={data.translated_tags[index] ?? tag}
                  className="rounded bg-surface-hover px-2 py-0.5 text-xs hover:text-accent"
                >
                  {data.translated_tags[index] || tag}
                </Link>
              ))}
            </div>
          </div>
        ) : null}

        {data.description ? (
          <details className="text-xs text-text-muted">
            <summary className="cursor-pointer">作品说明</summary>
            <p className="mt-2 whitespace-pre-wrap">{data.description}</p>
          </details>
        ) : null}
      </aside>

      {lightboxOpen ? (
        <Lightbox
          pid={data.pid}
          pages={data.pages}
          initialPage={0}
          animationAvailable={data.animation_available}
          onClose={() => setLightboxOpen(false)}
        />
      ) : null}
    </div>
  );
}
