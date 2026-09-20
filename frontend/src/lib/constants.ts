export const PAGE_SIZE = 60;

export const SORT_OPTIONS = [
  { value: "rank", label: "收藏顺序" },
  { value: "create_date", label: "发布时间" },
  { value: "bookmarks", label: "收藏数" },
  { value: "views", label: "浏览量" },
] as const;

export const TYPE_OPTIONS = [
  { value: "", label: "全部类型" },
  { value: "illust", label: "插画" },
  { value: "ugoira", label: "动图" },
] as const;

export const DOWNLOAD_OPTIONS = [
  { value: "", label: "全部状态" },
  { value: "yes", label: "已下载" },
  { value: "no", label: "未下载" },
] as const;

export const RESTRICT_OPTIONS = [
  { value: "", label: "全部收藏夹" },
  { value: "public", label: "公开" },
  { value: "private", label: "私密" },
] as const;

export const R18_OPTIONS = [
  { value: "", label: "不限分级" },
  { value: "0", label: "全年龄" },
  { value: "1", label: "R-18" },
] as const;
