import type {
  ArticleRead,
  ArticleCategory,
  ProcessingStatus,
} from "@/services/api";

export const categoryLabels = {
  politics: "Chính trị",
  economy: "Kinh tế",
  technology: "Công nghệ",
  society: "Xã hội",
  sports: "Thể thao",
  other: "Khác",
} as const satisfies Record<ArticleCategory, string>;
export const categories = ["Tất cả", ...Object.values(categoryLabels)] as const;
export type Category = (typeof categories)[number];
export interface Article {
  id: number;
  title: string;
  category: Exclude<Category, "Tất cả"> | "Chưa phân loại";
  summary: string | null;
  source: string;
  sourceUrl: string;
  imageUrl: string | null;
  timestamp: string;
  collectedAt: boolean;
  status: ProcessingStatus | "rejected";
  excerptOnly: boolean;
  inputTruncated: boolean;
}
export const statusLabels: Record<ProcessingStatus | "rejected", string> = {
  pending: "Chờ xử lý",
  processing: "Đang xử lý",
  ready: "Đã xử lý",
  needs_review: "Cần duyệt",
  rejected: "Đã từ chối",
  failed: "Xử lý chưa thành công",
};
export function toArticle(item: ArticleRead): Article {
  const approved =
    item.processing_status === "ready" && item.summary_preview !== null;
  return {
    id: item.id,
    title: item.title,
    category:
      approved && item.category
        ? categoryLabels[item.category]
        : "Chưa phân loại",
    summary: approved ? item.summary_preview : null,
    source: item.source.name,
    sourceUrl: item.original_url,
    imageUrl: item.image_url,
    timestamp: item.published_at ?? item.created_at,
    collectedAt: !item.published_at,
    status:
      item.review_decision === "decline" ? "rejected" : item.processing_status,
    excerptOnly: item.content_origin === "rss_excerpt",
    inputTruncated: approved && item.input_truncated === true,
  };
}
export const formatArticleTime = (value: string) =>
  new Intl.DateTimeFormat("vi-VN", {
    timeZone: "Asia/Ho_Chi_Minh",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(new Date(value));
export const normalizeSearch = (value: string) =>
  value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/đ/g, "d")
    .replace(/Đ/g, "D")
    .toLocaleLowerCase("vi")
    .trim();
export function filterArticles(
  articles: Article[],
  category: Category,
  query: string,
) {
  const term = normalizeSearch(query);
  return articles.filter(
    (article) =>
      (category === "Tất cả" || article.category === category) &&
      normalizeSearch(
        `${article.title} ${article.summary ?? ""} ${article.category} ${article.source}`,
      ).includes(term),
  );
}
// Source URLs are external data; only allow normal web navigation.
export function originalArticleUrl(value: string): string | undefined {
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) ? url.href : undefined;
  } catch {
    return undefined;
  }
}
