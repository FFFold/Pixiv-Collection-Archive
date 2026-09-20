import type { GalleryItem } from "../api/types";
import GalleryCard from "./GalleryCard";
import { useResponsiveColumns } from "./ResponsiveColumns";

interface Props {
  items: GalleryItem[];
  selected: Set<number>;
  onToggle: (pid: number) => void;
}

export default function GalleryGrid({ items, selected, onToggle }: Props) {
  const columns = useResponsiveColumns();

  if (items.length === 0) {
    return (
      <div className="flex min-h-[240px] items-center justify-center text-sm text-text-muted">
        没有匹配的作品
      </div>
    );
  }

  return (
    <div className="masonry" style={{ columnCount: columns }}>
      {items.map((item) => (
        <GalleryCard
          key={item.pid}
          item={item}
          selected={selected.has(item.pid)}
          onToggle={onToggle}
        />
      ))}
    </div>
  );
}
