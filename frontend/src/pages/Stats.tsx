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

function Card({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-border-subtle bg-surface-raised p-4">
      <div className="text-xs text-text-muted">{label}</div>
      <div className="mt-1 text-xl font-semibold">{value}</div>
      {hint ? <div className="mt-1 text-xs text-text-muted">{hint}</div> : null}
    </div>
  );
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

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Card label="作品总数" value={data.total_illusts.toLocaleString()} />
        <Card label="总页数" value={data.total_pages.toLocaleString()} />
        <Card
          label="已下载页"
          value={data.downloaded_pages.toLocaleString()}
          hint={`${percent.toFixed(1)}% · 待下载 ${data.pending_pages.toLocaleString()}`}
        />
        <Card label="占用空间" value={formatBytes(data.total_bytes)} />
        <Card label="缩略图" value={data.thumbs_ready.toLocaleString()} />
        <Card
          label="动图"
          value={data.ugoira_count.toLocaleString()}
          hint={`已转码 ${data.animation_ready}`}
        />
        <Card label="已取消收藏" value={data.unbookmarked.toLocaleString()} />
        <Card
          label="失败页"
          value={data.failed_pages.toLocaleString()}
          hint={data.failed_pages > 0 ? "可重新下载" : undefined}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-border-subtle bg-surface-raised p-4">
          <div className="mb-3 text-sm font-medium">类型与收藏夹</div>
          <div className="space-y-2 text-sm">
            {Object.entries(data.by_type).map(([type, count]) => (
              <div key={type} className="flex items-center justify-between">
                <span className="text-text-muted">
                  {TYPE_LABELS[type] ?? type}
                </span>
                <span>{count.toLocaleString()}</span>
              </div>
            ))}
            {Object.entries(data.by_restrict).map(([restrict, count]) => (
              <div key={restrict} className="flex items-center justify-between">
                <span className="text-text-muted">
                  {RESTRICT_LABELS[restrict] ?? restrict}
                </span>
                <span>{count.toLocaleString()}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-lg border border-border-subtle bg-surface-raised p-4">
          <div className="mb-3 text-sm font-medium">作者 TOP 10</div>
          <div className="space-y-2 text-sm">
            {(authors.data ?? []).map((author) => (
              <div key={author.id} className="flex items-center justify-between gap-3">
                <span className="truncate text-text-muted">{author.name}</span>
                <span>{author.illust_count}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-border-subtle bg-surface-raised p-4">
        <div className="mb-3 text-sm font-medium">常见标签</div>
        <div className="flex flex-wrap gap-2">
          {(tags.data ?? []).map((tag) => (
            <span key={tag.name} className="rounded bg-surface-hover px-2 py-1 text-xs">
              {tag.name} · {tag.illust_count}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
