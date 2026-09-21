import { useAuthors, useTags } from "../api/queries";
import type { GalleryQuery } from "../api/types";

interface Props {
  tags: string[];
  authorIds: number[];
  onChange: (patch: Partial<GalleryQuery>) => void;
}

export default function FilterPickers({ tags, authorIds, onChange }: Props) {
  const tagOptions = useTags(200);
  const authorOptions = useAuthors(100);
  const allTags = Array.isArray(tagOptions.data) ? tagOptions.data : [];
  const allAuthors = Array.isArray(authorOptions.data) ? authorOptions.data : [];
  const selectedTags = tags ?? [];
  const selectedAuthorIds = authorIds ?? [];
  const availableTags = allTags.filter((tag) => !selectedTags.includes(tag.name));
  const availableAuthors = allAuthors.filter((author) => !selectedAuthorIds.includes(author.id));

  const addTag = (name: string) => {
    if (!name || selectedTags.includes(name)) return;
    onChange({ tags: [...selectedTags, name], offset: 0 });
  };

  const removeTag = (name: string) => {
    const next = selectedTags.filter((tag) => tag !== name);
    onChange({ tags: next.length > 0 ? next : undefined, offset: 0 });
  };

  const addAuthor = (value: string) => {
    const id = Number(value);
    if (!Number.isFinite(id) || selectedAuthorIds.includes(id)) return;
    onChange({ author_ids: [...selectedAuthorIds, id], offset: 0 });
  };

  const removeAuthor = (id: number) => {
    const next = selectedAuthorIds.filter((value) => value !== id);
    onChange({ author_ids: next.length > 0 ? next : undefined, offset: 0 });
  };

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-text-muted">
      {selectedTags.map((tag) => (
        <span
          key={tag}
          className="flex items-center gap-1 rounded bg-surface-hover px-2 py-1 text-text-primary"
        >
          #{tag}
          <button
            type="button"
            aria-label={`移除标签 ${tag}`}
            onClick={() => removeTag(tag)}
            className="hover:text-red-300"
          >
            ×
          </button>
        </span>
      ))}
      <select
        aria-label="添加标签"
        value=""
        onChange={(event) => addTag(event.target.value)}
        className="rounded-md border border-border-subtle bg-surface-raised px-2 py-1 text-xs outline-none focus:border-accent"
      >
        <option value="">+ 标签</option>
        {availableTags.map((tag) => (
          <option key={tag.name} value={tag.name}>
            {tag.name} · {tag.illust_count}
          </option>
        ))}
      </select>

      {selectedAuthorIds.map((id) => {
        const author = allAuthors.find((entry) => entry.id === id);
        return (
          <span
            key={id}
            className="flex items-center gap-1 rounded bg-surface-hover px-2 py-1 text-text-primary"
          >
            {author ? author.name : `#${id}`}
            <button
              type="button"
              aria-label={`移除作者 ${author ? author.name : id}`}
              onClick={() => removeAuthor(id)}
              className="hover:text-red-300"
            >
              ×
            </button>
          </span>
        );
      })}
      <select
        aria-label="添加作者"
        value=""
        onChange={(event) => addAuthor(event.target.value)}
        className="max-w-[180px] rounded-md border border-border-subtle bg-surface-raised px-2 py-1 text-xs outline-none focus:border-accent"
      >
        <option value="">+ 作者</option>
        {availableAuthors.map((author) => (
          <option key={author.id} value={author.id}>
            {author.name} · {author.illust_count}
          </option>
        ))}
      </select>
    </div>
  );
}
