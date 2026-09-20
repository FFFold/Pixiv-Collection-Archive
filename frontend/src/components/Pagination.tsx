interface Props {
  offset: number;
  limit: number;
  total: number;
  onChange: (offset: number) => void;
}

export default function Pagination({ offset, limit, total, onChange }: Props) {
  const start = total === 0 ? 0 : Math.min(offset + 1, total);
  const end = Math.min(offset + limit, total);
  const hasPrevious = offset > 0;
  const hasNext = offset + limit < total;

  return (
    <div className="flex items-center justify-between gap-4 py-4 text-sm text-text-muted">
      <span>
        {start}–{end} / 共 {total}
      </span>
      <div className="flex gap-2">
        <button
          type="button"
          disabled={!hasPrevious}
          onClick={() => onChange(Math.max(0, offset - limit))}
          className="rounded-md border border-border-subtle px-3 py-1.5 disabled:opacity-40"
        >
          上一页
        </button>
        <button
          type="button"
          disabled={!hasNext}
          onClick={() => onChange(offset + limit)}
          className="rounded-md border border-border-subtle px-3 py-1.5 disabled:opacity-40"
        >
          下一页
        </button>
      </div>
    </div>
  );
}
