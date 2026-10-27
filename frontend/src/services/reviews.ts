import type { ArticleCategory, SourceRead } from "./api";
export type ReviewDecision = "accept" | "decline";
export type ReviewFilter = "pending" | ReviewDecision;
export interface ReviewItem {
  id: number;
  title: string;
  source: SourceRead;
  has_draft: boolean;
  can_review: boolean;
  decision: ReviewDecision | null;
}
export interface ReviewPageData {
  items: ReviewItem[];
  total: number;
  page: number;
  page_size: number;
}
export interface ReviewDetail extends ReviewItem {
  original_url: string;
  source_text: string | null;
  content_origin: "extracted" | "rss_excerpt" | null;
  reason: string | null;
  version: string;
  note: string | null;
  draft: {
    text: string;
    category: ArticleCategory;
    keywords: string[];
    ai_feedback: string | null;
    attempts: number;
    input_truncated: boolean;
  } | null;
}
export class ReviewError extends Error {
  status: number;
  constructor(status: number) {
    super(
      status === 409
        ? "Bản nháp đã thay đổi hoặc đã được duyệt ở nơi khác. Hãy tải lại trước khi quyết định."
        : status === 403
          ? "Chức năng duyệt chỉ khả dụng trên máy đang chạy ứng dụng."
          : "Không thể tải hoặc lưu quyết định duyệt. Vui lòng thử lại.",
    );
    this.status = status;
  }
}
async function request<T>(path: string, options: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1/reviews${path}`, options);
  if (!response.ok) throw new ReviewError(response.status);
  return response.json() as Promise<T>;
}
export const getReviews = (
  filter: ReviewFilter,
  page: number,
  signal: AbortSignal,
) =>
  request<ReviewPageData>(`?decision=${filter}&page=${page}&page_size=20`, {
    signal,
  });
export const getReview = (id: number, signal: AbortSignal) =>
  request<ReviewDetail>(`/${id}`, { signal });
export const submitReview = (
  id: number,
  decision: ReviewDecision,
  version: string,
  note: string,
) =>
  request<ReviewDetail>(`/${id}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision, expected_version: version, note }),
  });
