export interface GalleryItem {
  pid: number;
  index: number;
  title: string;
  author_id: number;
  author_name: string;
  page_count: number;
  type: "illust" | "ugoira" | string;
  x_restrict: number;
  width: number;
  height: number;
  create_date: string | null;
  rank: number;
  has_original: boolean;
  page_downloaded_count: number;
  preview_url: string;
  thumb_url: string;
  restrict: "public" | "private" | string;
  unbookmarked: boolean;
  state: string;
}

export interface GalleryResponse {
  items: GalleryItem[];
  total: number;
  offset: number;
  limit: number;
}

export interface IllustPageOut {
  page_index: number;
  download_state: "pending" | "done" | "failed" | string;
  ext: string;
}

export interface IllustDetail {
  pid: number;
  index: number;
  title: string;
  description: string;
  author_id: number;
  author_name: string;
  author_account: string;
  page_count: number;
  type: "illust" | "ugoira" | string;
  x_restrict: number;
  sanity_level: number;
  width: number;
  height: number;
  create_date: string | null;
  total_view: number;
  total_bookmarks: number;
  state: string;
  has_original: boolean;
  page_downloaded_count: number;
  tags: string[];
  translated_tags: string[];
  pages: IllustPageOut[];
  restrict: string;
  bookmark_state: string;
  rank: number | null;
  pixiv_url: string;
  animation_available: boolean;
  frame_count: number | null;
  unbookmarked: boolean;
}

export interface AuthorOut {
  id: number;
  name: string;
  account: string;
  illust_count: number;
}

export interface TagOut {
  name: string;
  translated_name: string | null;
  illust_count: number;
}

export interface TaskOut {
  id: string;
  kind: "sync" | "download" | "export" | string;
  status: "running" | "completed" | "failed" | "cancelled" | string;
  started_at: string;
  finished_at: string | null;
  detail: Record<string, unknown>;
  error: string | null;
}

export interface StatsOut {
  total_illusts: number;
  unbookmarked: number;
  total_pages: number;
  downloaded_pages: number;
  failed_pages: number;
  pending_pages: number;
  total_bytes: number;
  thumbs_ready: number;
  ugoira_count: number;
  animation_ready: number;
  by_type: Record<string, number>;
  by_restrict: Record<string, number>;
}

export interface MeResponse {
  authenticated: boolean;
}

export interface ExportResponse {
  task_id: string;
  filename: string;
}

export interface GalleryQuery {
  offset?: number;
  limit?: number;
  sort?: "rank" | "create_date" | "bookmarks" | "views";
  author_ids?: number[];
  tags?: string[];
  q?: string;
  type?: "illust" | "ugoira";
  x_restrict?: number;
  downloaded?: boolean;
  restrict?: "public" | "private";
  only_unbookmarked?: boolean;
  include_unbookmarked?: boolean;
  only_deleted?: boolean;
  include_deleted?: boolean;
  page_min?: number;
  page_max?: number;
  bookmarks_min?: number;
  bookmarks_max?: number;
  views_min?: number;
  views_max?: number;
  rank_start?: number;
  rank_count?: number;
}

export interface DownloadRequest {
  scope: "all_missing" | "author" | "selected" | "rank_range" | "filter";
  pids?: number[];
  author_id?: number;
  start?: number;
  count?: number;
  x_restrict?: number;
  type?: "illust" | "ugoira";
  with_thumbs?: boolean;
  tags?: string[];
  author_ids?: number[];
  q?: string;
  restrict?: "public" | "private";
  downloaded?: boolean;
  page_min?: number;
  page_max?: number;
  bookmarks_min?: number;
  bookmarks_max?: number;
  views_min?: number;
  views_max?: number;
  only_unbookmarked?: boolean;
  include_unbookmarked?: boolean;
}

export interface ExportRequest {
  include_metadata: boolean;
  include_originals: boolean;
  pids?: number[];
  x_restrict?: number;
  only_downloaded?: boolean;
}
