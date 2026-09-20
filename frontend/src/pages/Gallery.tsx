import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { useStartDownload } from "../api/mutations";
import { useGallery } from "../api/queries";
import type { GalleryQuery } from "../api/types";
import GalleryGrid from "../components/GalleryGrid";
import Pagination from "../components/Pagination";
import Toolbar from "../components/Toolbar";
import { useSelection } from "../hooks/useSelection";
import { PAGE_SIZE } from "../lib/constants";

interface Props {
  initialOnlyUnbookmarked?: boolean;
}

export default function Gallery({ initialOnlyUnbookmarked = false }: Props) {
  const [searchParams] = useSearchParams();
  const [query, setQuery] = useState<GalleryQuery>(() => {
    const tag = searchParams.get("tag") ?? undefined;
    return {
      offset: 0,
      limit: PAGE_SIZE,
      sort: "rank",
      tag,
      only_unbookmarked: initialOnlyUnbookmarked || undefined,
    };
  });
  const [notice, setNotice] = useState<string | null>(null);
  const { data, isLoading, isError, error } = useGallery(query);
  const selection = useSelection();
  const download = useStartDownload();

  const patch = (update: Partial<GalleryQuery>) =>
    setQuery((current) => ({ ...current, ...update }));

  const items = useMemo(() => data?.items ?? [], [data]);

  const downloadSelected = () => {
    const pids = Array.from(selection.selected);
    download.mutate(
      { scope: "selected", pids, with_thumbs: true },
      {
        onSuccess: () => {
          selection.clear();
          setNotice(`已开始下载 ${pids.length} 个作品`);
        },
      },
    );
  };

  const downloadAllMissing = () => {
    download.mutate(
      {
        scope: "filter",
        x_restrict: query.x_restrict,
        type: query.type,
        with_thumbs: true,
      },
      { onSuccess: () => setNotice("已开始下载筛选范围内的未下载作品") },
    );
  };

  return (
    <div className="flex min-h-full flex-col">
      <Toolbar
        query={query}
        onChange={patch}
        selectedCount={selection.count}
        onDownloadSelected={downloadSelected}
        onDownloadAllMissing={downloadAllMissing}
        downloadPending={download.isPending}
      />

      {notice ? (
        <div className="mx-4 mt-3 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">
          {notice}
        </div>
      ) : null}

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
        />
      </div>
    </div>
  );
}
