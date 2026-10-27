import { useState } from "react";
import { ArrowUpRight, Newspaper } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  formatArticleTime,
  originalArticleUrl,
  statusLabels,
  type Article,
} from "@/data/articles";

export function ArticleImage({
  article,
  eager = false,
}: {
  article: Article;
  eager?: boolean;
}) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const url = article.imageUrl
    ? originalArticleUrl(article.imageUrl)
    : undefined;
  if (url && failedUrl !== url) {
    return (
      <img
        src={url}
        alt={article.title}
        loading={eager ? "eager" : "lazy"}
        decoding="async"
        referrerPolicy="no-referrer"
        onError={() => setFailedUrl(url)}
      />
    );
  }
  return (
    <div className="editorial-placeholder" aria-hidden="true">
      <Newspaper />
      <span>GÓC VIỆT / {article.category.toLocaleUpperCase("vi")}</span>
    </div>
  );
}
export function ArticleMeta({ article }: { article: Article }) {
  const url = originalArticleUrl(article.sourceUrl);
  return (
    <div className="article-meta">
      {url ? (
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`Nguồn: ${article.source} (mở trong tab mới)`}
        >
          {article.source}
        </a>
      ) : (
        <span>{article.source}</span>
      )}
      <span aria-hidden="true">·</span>
      <time dateTime={article.timestamp}>
        {article.collectedAt && "Thu thập: "}
        {formatArticleTime(article.timestamp)}
      </time>
    </div>
  );
}
export function ArticleCard({
  article,
  onOpen,
}: {
  article: Article;
  onOpen: (article: Article) => void;
}) {
  return (
    <article
      className="article-card"
      data-category={article.category}
      data-status={article.status}
      data-article-id={article.id}
    >
      <button
        className="article-image-button"
        onClick={() => onOpen(article)}
        aria-label={`Đọc: ${article.title}`}
      >
        <ArticleImage article={article} />
        <span className="image-arrow">
          <ArrowUpRight aria-hidden="true" />
        </span>
      </button>
      <div className="article-card-copy">
        <Badge variant="link">{article.category}</Badge>
        <h3>
          <button className="headline-button" onClick={() => onOpen(article)}>
            {article.title}
          </button>
        </h3>
        {article.summary ? (
          <p>{article.summary}</p>
        ) : (
          <p className="processing-note">
            {statusLabels[article.status]} · Chưa có bản tóm tắt được duyệt.
          </p>
        )}
        <ArticleMeta article={article} />
      </div>
    </article>
  );
}
