import { Link } from "react-router-dom";

import { useAuthors, useStats, useTags } from "../api/queries";
import { formatBytes } from "../lib/format";

const TYPE_LABELS: Record<string, string> = {
  illust: "插画",
  manga: "漫画",
  ugoira: "动图",
};

const RESTRICT_LABELS: Record<string, string> = {
  public: "公开收藏",
  private: "私密收藏",
};

function Card({
  label,
  value,
  hint,
  to,
}: {
  label: string;
  value: string;
  hint?: string;
  to?: string;
}) {
  const body = (
    <>
      <div className="text-xs text-text-muted">{label}</div>
      <div className="mt-1 text-xl font-semibold">{value}</div>
      {hint ? <div className="mt-1 text-xs text-text-muted">{hint}</div> : null}
    </>
  );
  if (to) {
    return (
      <Link
        to={to}
        className="block rounded-lg border border-border-subtle bg-surface-raised p-4 transition-colors hover:border-accent"
      >
        {body}
      </Link>
    );
  }
  return <div className="rounded-lg border border-border-subtle bg-surface-raised p-4">{body}</div>;
}

export default function Stats() {
  const { data, isLoading, isError } = useStats();
  const authors = useAuthors(10);
  const tags = useTags(20);

  if (isLoading) {
    return <div className="p-6 text-sm text-text-muted">加载中…</div>;
  }
  if (isError || !data) {
    return <div className="p-6 text-sm text-red-400">统计数据加载失败</div>;
  }

  const percent = data.total_pages > 0 ? (data.downloaded_pages / data.total_pages) * 100 : 0;

  return (
    <div className="space-y-6 p-6">
      <h1 className="text-base font-semibold">统计</h1>

      {data.stats_stale ? (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-300">
          部分作品体积未知，请在「设置 → 维护」中运行「重建存储统计」。
        </div>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Card label="作品总数" value={data.total_illusts.toLocaleString()} />
        <Card label="总页数" value={data.total_pages.toLocaleString()} />
        <Card
          label="已下载页"
          value={data.downloaded_pages.toLocaleString()}
          hint={`${percent.toFixed(1)}% · 待下载 ${data.pending_pages.toLocaleString()}`}
          to="/?downloaded=true"
        />
        <Card label="占用空间" value={formatBytes(data.total_bytes)} />
        <Card label="缩略图" value={data.thumbs_ready.toLocaleString()} />
        <Card
          label="动图"
          value={data.ugoira_count.toLocaleString()}
          hint={`已转码 ${data.animation_ready}`}
        />
        <Card label="已取消收藏" value={data.unbookmarked.toLocaleString()} to="/unbookmarked" />
        <Card
          label="失败页"
          value={data.failed_pages.toLocaleString()}
          hint={data.failed_pages > 0 ? "可在任务页重试失败项" : undefined}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-border-subtle bg-surface-raised p-4">
          <div className="mb-3 text-sm font-medium">体积与页数分布</div>
          <div className="space-y-2 text-sm">
            {Object.entries(data.by_type).map(([type, count]) => (
              <div key={type} className="flex items-center justify-between">
                <span className="text-text-muted">{TYPE_LABELS[type] ?? type}</span>
                <span>
                  {count.toLocaleString()} · {formatBytes(data.by_type_bytes[type] ?? 0)}
                </span>
              </div>
            ))}
            {Object.entries(data.by_restrict).map(([restrict, count]) => (
              <div key={restrict} className="flex items-center justify-between">
                <span className="text-text-muted">{RESTRICT_LABELS[restrict] ?? restrict}</span>
                <span>
                  {count.toLocaleString()} · {formatBytes(data.by_restrict_bytes[restrict] ?? 0)}
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-lg border border-border-subtle bg-surface-raised p-4">
          <div className="mb-3 text-sm font-medium">体积 TOP 作者</div>
          <div className="space-y-2 text-sm">
            {data.top_authors_bytes.length === 0 ? (
              <span className="text-text-muted">暂无数据</span>
            ) : (
              data.top_authors_bytes.map((author) => (
                <div key={author.id} className="flex items-center justify-between gap-3">
                  <Link to={`/?author_id=${author.id}`} className="truncate hover:text-accent">
                    {author.name}
                  </Link>
                  <span>
                    {formatBytes(author.bytes)} · {author.illust_count}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-border-subtle bg-surface-raised p-4">
          <div className="mb-3 text-sm font-medium">作者 TOP 10</div>
          <div className="space-y-2 text-sm">
            {(authors.data ?? []).map((author) => (
              <div key={author.id} className="flex items-center justify-between gap-3">
                <Link to={`/?author_id=${author.id}`} className="truncate hover:text-accent">
                  {author.name}
                </Link>
                <span>{author.illust_count}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-lg border border-border-subtle bg-surface-raised p-4">
          <div className="mb-3 text-sm font-medium">常见标签</div>
          <div className="flex flex-wrap gap-2">
            {(tags.data ?? []).map((tag) => (
              <Link
                key={tag.name}
                to={`/?tag=${encodeURIComponent(tag.name)}`}
                className="rounded bg-surface-hover px-2 py-1 text-xs hover:text-accent"
              >
                {tag.name} · {tag.illust_count}
              </Link>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
