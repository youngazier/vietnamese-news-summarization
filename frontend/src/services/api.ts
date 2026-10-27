// Public REST fields only. Supabase and model credentials stay in the backend.
export type ArticleCategory =
  | "politics"
  | "economy"
  | "technology"
  | "society"
  | "sports"
  | "other";
export type ProcessingStatus =
  | "pending"
  | "processing"
  | "ready"
  | "needs_review"
  | "failed";
export interface SourceRead {
  id: number;
  name: string;
  rss_url: string;
  last_fetched_at: string | null;
}
export interface ArticleRead {
  id: number;
  title: string;
  original_url: string;
  image_url: string | null;
  review_decision: "accept" | "decline" | null;
  source: SourceRead;
  published_at: string | null;
  created_at: string;
  content_origin: "extracted" | "rss_excerpt" | null;
  processing_status: ProcessingStatus;
  category: ArticleCategory | null;
  summary_preview: string | null;
  input_truncated: boolean | null;
}
export interface ArticleDetail extends ArticleRead {
  ai_generated: boolean;
  summary: {
    summary_text: string;
    keywords: string[];
    summarize_model_name: string;
    agent_model_name: string;
    created_at: string;
    input_truncated: boolean;
  } | null;
}
interface ArticlePage {
  items: ArticleRead[];
  total: number;
  page: number;
  page_size: number;
}
async function get<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    signal,
    headers: { Accept: "application/json" },
  });
  if (!response.ok)
    throw new Error("Không thể tải tin tức. Vui lòng thử lại sau.");
  return response.json() as Promise<T>;
}
// Load every page so client-side search/filtering covers the complete stored feed.
export async function getArticles(signal: AbortSignal): Promise<ArticleRead[]> {
  const first = await get<ArticlePage>(
    "/articles?page=1&page_size=100",
    signal,
  );
  const items = [...first.items];
  const pages = Math.ceil(first.total / first.page_size);
  for (let page = 2; page <= pages; page++) {
    const result = await get<ArticlePage>(
      `/articles?page=${page}&page_size=100`,
      signal,
    );
    items.push(...result.items);
  }
  return [...new Map(items.map((article) => [article.id, article])).values()];
}
export const getArticle = (id: number, signal: AbortSignal) =>
  get<ArticleDetail>(`/articles/${id}`, signal);
