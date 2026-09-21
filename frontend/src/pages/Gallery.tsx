import { useEffect, useMemo } from "react";

import { useStartDownload } from "../api/mutations";
import { useGallery } from "../api/queries";
import type { GalleryQuery } from "../api/types";
import GalleryGrid from "../components/GalleryGrid";
import Pagination from "../components/Pagination";
import Toolbar from "../components/Toolbar";
import { useGalleryFilters } from "../contexts/GalleryFiltersContext";
import { useSelection } from "../contexts/SelectionContext";
import { useGalleryQueryState } from "../hooks/useGalleryQueryState";
import { PAGE_SIZE } from "../lib/constants";

interface Props {
  initialOnlyUnbookmarked?: boolean;
}

export default function Gallery({ initialOnlyUnbookmarked = false }: Props) {
  const initial = useMemo(
    () => (initialOnlyUnbookmarked ? { only_unbookmarked: true } : {}),
    [initialOnlyUnbookmarked],
  );
  const { query, patch } = useGalleryQueryState(initial);
  const { setFilters } = useGalleryFilters();
  const { data, isLoading, isError, error } = useGallery(query);
  const selection = useSelection();
  const download = useStartDownload();

  const items = useMemo(() => data?.items ?? [], [data]);
  const pagePids = useMemo(() => items.map((item) => item.pid), [items]);
  const undownloadedPids = useMemo(
    () => items.filter((item) => !item.has_original).map((item) => item.pid),
    [items],
  );

  useEffect(() => {
    setFilters(query);
  }, [query, setFilters]);

  const downloadSelected = () => {
    const pids = Array.from(selection.selected);
    download.mutate(
      { scope: "selected", pids, with_thumbs: true },
      { onSuccess: () => selection.clear() },
    );
  };

  const downloadAllMissing = () => {
    const filter: Partial<GalleryQuery> = {
      tags: query.tags,
      author_ids: query.author_ids,
      q: query.q,
      type: query.type,
      x_restrict: query.x_restrict,
      downloaded: false,
      restrict: query.restrict,
      only_unbookmarked: query.only_unbookmarked,
      include_unbookmarked: query.include_unbookmarked,
      page_min: query.page_min,
      page_max: query.page_max,
      bookmarks_min: query.bookmarks_min,
      bookmarks_max: query.bookmarks_max,
      views_min: query.views_min,
      views_max: query.views_max,
    };
    download.mutate({
      scope: "filter",
      ...filter,
      with_thumbs: true,
    });
  };

  return (
    <div className="flex min-h-full flex-col">
      <Toolbar
        query={query}
        onChange={patch}
        pagePids={pagePids}
        undownloadedPids={undownloadedPids}
        onDownloadSelected={downloadSelected}
        onDownloadAllMissing={downloadAllMissing}
        downloadPending={download.isPending}
      />

      <div className="flex-1 px-4 pt-4">
        {isLoading ? (
          <div className="flex min-h-[240px] items-center justify-center text-sm text-text-muted">
            加载中…
          </div>
        ) : isError ? (
          <div className="flex min-h-[240px] items-center justify-center text-sm text-red-400">
            加载失败：{error instanceof Error ? error.message : "未知错误"}
          </div>
        ) : (
          <GalleryGrid
            items={items}
            selected={selection.selected}
            onToggle={selection.toggle}
          />
        )}
      </div>

      <div className="px-4">
        <Pagination
          offset={query.offset ?? 0}
          limit={query.limit ?? PAGE_SIZE}
          total={data?.total ?? 0}
          onChange={(offset) => patch({ offset })}
          onLimitChange={(limit) => patch({ limit, offset: 0 })}
        />
      </div>
    </div>
  );
}
