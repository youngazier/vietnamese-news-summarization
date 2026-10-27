import { useEffect, useState } from "react";
import { ArrowUpRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { ArticleImage, ArticleMeta } from "./ArticleCard";
import {
  originalArticleUrl,
  statusLabels,
  type Article,
} from "@/data/articles";
import { getArticle, type ArticleDetail } from "@/services/api";

export function ArticleReader({ article }: { article: Article }) {
  const [detail, setDetail] = useState<ArticleDetail | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    getArticle(article.id, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) {
          setDetail(result);
          setFailed(false);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, [article.id, attempt]);
  const approved =
    detail?.processing_status === "ready" &&
    detail.ai_generated &&
    detail.summary;
  const url = originalArticleUrl(article.sourceUrl);
  return (
    <>
      <DialogHeader>
        <Badge variant="link">
          {article.category} · {statusLabels[article.status]}
        </Badge>
        <DialogTitle>
          {url ? (
            <a
              className="reader-title-link"
              href={url}
              target="_blank"
              rel="noopener noreferrer"
            >
              {article.title}
              <ArrowUpRight aria-hidden="true" />
              <span className="sr-only"> (đọc bài gốc, mở trong tab mới)</span>
            </a>
          ) : (
            article.title
          )}
        </DialogTitle>
        <DialogDescription>
          Đọc tóm tắt tại Góc Việt hoặc nhấn vào tiêu đề để xem bài đầy đủ trên{" "}
          {article.source}.
        </DialogDescription>
      </DialogHeader>
      {article.imageUrl && (
        <div className="reader-image">
          <ArticleImage article={article} eager />
        </div>
      )}
      <ArticleMeta article={article} />
      {failed ? (
        <div role="alert">
          <p>Không thể tải nội dung tóm tắt. Bạn vẫn có thể đọc bài gốc.</p>
          <Button
            variant="outline"
            onClick={() => {
              setFailed(false);
              setAttempt((value) => value + 1);
            }}
          >
            Thử lại
          </Button>
        </div>
      ) : !detail ? (
        <div
          role="status"
          aria-label="Đang tải tóm tắt"
          className="flex flex-col gap-3"
        >
          <Skeleton className="h-5 w-full" />
          <Skeleton className="h-5 w-4/5" />
        </div>
      ) : approved ? (
        <>
          <Badge variant="secondary">Tóm tắt bằng AI · Đã được duyệt</Badge>
          <p className="reader-body">{detail.summary!.summary_text}</p>
          <div className="flex flex-wrap gap-2" aria-label="Từ khóa">
            {detail.summary!.keywords.map((keyword) => (
              <Badge key={keyword} variant="outline">
                {keyword}
              </Badge>
            ))}
          </div>
        </>
      ) : (
        <p className="reader-body">
          {detail.review_decision === "decline"
            ? "Đã từ chối"
            : statusLabels[detail.processing_status]}
          . Bài viết chưa có bản tóm tắt được duyệt. Mời bạn đọc nội dung đầy đủ
          tại nguồn.
        </p>
      )}
      {(article.excerptOnly || article.inputTruncated) && (
        <p className="reader-context">
          {article.excerptOnly
            ? "Văn bản thu thập chỉ là trích đoạn RSS."
            : "Chỉ một phần văn bản được dùng để tạo tóm tắt."}
        </p>
      )}
      {url && (
        <a
          className="reader-source-link"
          href={url}
          target="_blank"
          rel="noopener noreferrer"
        >
          Đọc toàn văn trên {article.source}
          <ArrowUpRight aria-hidden="true" />
          <span className="sr-only"> (mở trong tab mới)</span>
        </a>
      )}
    </>
  );
}
