import { useEffect, useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Search,
  Sparkles,
} from "lucide-react";
import { NewsHeader } from "@/components/news/NewsHeader";
import {
  ArticleCard,
  ArticleImage,
  ArticleMeta,
} from "@/components/news/ArticleCard";
import { NewsSkeleton } from "@/components/news/NewsSkeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  Empty,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  EmptyDescription,
  EmptyContent,
} from "@/components/ui/empty";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import {
  categories,
  filterArticles,
  toArticle,
  statusLabels,
  type Article,
  type Category,
} from "@/data/articles";
import { ArticleReader } from "@/components/news/ArticleReader";
import { getArticles } from "@/services/api";
import { ReviewPage } from "@/components/news/ReviewPage";
import "./App.css";

function App() {
  const [reviewMode, setReviewMode] = useState(
    () => window.location.hash === "#duyet-bai",
  );
  useEffect(() => {
    const changed = () => setReviewMode(window.location.hash === "#duyet-bai");
    window.addEventListener("hashchange", changed);
    return () => window.removeEventListener("hashchange", changed);
  }, []);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<Category>("Tất cả");
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Article | null>(null);
  const [articles, setArticles] = useState<Article[]>([]);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    getArticles(controller.signal)
      .then((items) => {
        if (!controller.signal.aborted) {
          setArticles(items.map(toArticle));
          setError(false);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setError(true);
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [attempt]);
  const retry = () => {
    setLoading(true);
    setError(false);
    setAttempt((value) => value + 1);
  };
  const results = filterArticles(articles, category, query);
  const isFiltered = category !== "Tất cả" || query.trim() !== "";
  const featured =
    articles.find((article) => article.summary !== null) ?? articles[0];
  const remaining = articles.filter((article) => article.id !== featured?.id);
  const reset = () => {
    setQuery("");
    setCategory("Tất cả");
  };

  return (
    <>
      <a className="skip-link" href="#noi-dung">
        Đến nội dung chính
      </a>
      <NewsHeader
        query={query}
        onQuery={setQuery}
        reviewing={reviewMode}
        onCategory={(value) => {
          setCategory(value);
          setReviewMode(false);
        }}
        onReview={() => {
          setReviewMode(true);
          setSelected(null);
        }}
      />
      <main id="noi-dung" className="container">
        {reviewMode ? (
          <ReviewPage onReviewed={() => setAttempt((value) => value + 1)} />
        ) : (
          <>
            <section className="intro" aria-labelledby="page-title">
              <div>
                <div className="eyebrow">
                  <span className="red-dot" /> ĐỌC CHẬM. HIỂU SÂU.
                </div>
                <h1 id="page-title">
                  Việt Nam, qua từng câu chuyện<span>.</span>
                </h1>
                <p>Những tin tức đáng đọc. Những góc nhìn đáng nghĩ.</p>
              </div>
              <div className="edition">
                <BookOpen aria-hidden="true" />
                <span>
                  Gói gọn thông tin
                  <br />
                  <strong>Mở rộng góc nhìn</strong>
                </span>
              </div>
            </section>
            <div className="category-bar">
              <ToggleGroup
                value={[category]}
                onValueChange={(values) => {
                  if (values.length) setCategory(values[0] as Category);
                }}
                aria-label="Lọc theo chuyên mục"
              >
                {categories.map((item) => (
                  <ToggleGroupItem key={item} value={item}>
                    {item}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
              <span className="feed-note">
                <span className="red-dot" /> Dòng tin chọn lọc
              </span>
            </div>
            {loading ? (
              <NewsSkeleton />
            ) : error ? (
              <Empty className="py-20" role="alert">
                <EmptyHeader>
                  <EmptyTitle>Không thể tải tin tức</EmptyTitle>
                  <EmptyDescription>
                    Không thể kết nối nguồn tin lúc này. Vui lòng thử lại.
                  </EmptyDescription>
                </EmptyHeader>
                <EmptyContent>
                  <Button variant="outline" onClick={retry}>
                    Thử lại
                  </Button>
                </EmptyContent>
              </Empty>
            ) : articles.length === 0 ? (
              <Empty className="py-20">
                <EmptyHeader>
                  <EmptyTitle>Chưa có bài viết</EmptyTitle>
                  <EmptyDescription>
                    Những bài viết được thu thập sẽ xuất hiện tại đây.
                  </EmptyDescription>
                </EmptyHeader>
                <EmptyContent>
                  <Button variant="outline" onClick={retry}>
                    Tải lại
                  </Button>
                </EmptyContent>
              </Empty>
            ) : (
              <>
                {!isFiltered && featured && (
                  <section className="lead-layout" aria-label="Tin nổi bật">
                    <article className="featured-article">
                      <button
                        className="featured-image"
                        onClick={() => setSelected(featured)}
                        aria-label={`Đọc: ${featured.title}`}
                      >
                        <ArticleImage article={featured} eager />
                        <Badge>BÀI VIẾT NỔI BẬT</Badge>
                        <span className="feature-image-caption">
                          TIN TỪ NGUỒN BÁO · GÓC NHÌN MỖI NGÀY
                        </span>
                      </button>
                      <div className="featured-copy">
                        <div className="feature-topline">
                          <Badge variant="link">{featured.category}</Badge>
                          <span>
                            {featured.summary
                              ? "TÓM TẮT ĐÃ DUYỆT"
                              : statusLabels[featured.status]}
                          </span>
                        </div>
                        <h2>
                          <button
                            className="headline-button"
                            onClick={() => setSelected(featured)}
                          >
                            {featured.title}
                          </button>
                        </h2>
                        <p>
                          {featured.summary ??
                            "Bài viết chưa có bản tóm tắt được duyệt. Mời bạn đọc nội dung tại nguồn."}
                        </p>
                        <div className="feature-bottom">
                          <ArticleMeta article={featured} />
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label="Đọc bài viết nổi bật"
                            onClick={() => setSelected(featured)}
                          >
                            <ArrowUpRight />
                          </Button>
                        </div>
                      </div>
                    </article>
                    <aside className="digest">
                      <div className="section-label">
                        <span className="red-dot" />
                        <h2>Đáng chú ý</h2>
                        <span className="digest-label">GÓC NHÌN CHỌN LỌC</span>
                      </div>
                      <div className="digest-stories">
                        {remaining.slice(0, 3).map((article, index) => (
                          <article className="digest-story" key={article.id}>
                            <span className="digest-number">0{index + 1}</span>
                            <div>
                              <Badge variant="link">{article.category}</Badge>
                              <h3>
                                <button
                                  className="headline-button"
                                  onClick={() => setSelected(article)}
                                >
                                  {article.title}
                                </button>
                              </h3>
                              <ArticleMeta article={article} />
                            </div>
                          </article>
                        ))}
                      </div>
                      <div className="editor-note">
                        <Sparkles aria-hidden="true" />
                        <div>
                          <h3>Ít thời gian, nhiều góc nhìn.</h3>
                          <p>
                            Mỗi câu chuyện là một cơ hội để hiểu thêm về thế
                            giới quanh ta.
                          </p>
                        </div>
                      </div>
                    </aside>
                  </section>
                )}
                <section
                  id="tin-moi"
                  className="latest-section"
                  aria-labelledby="latest-title"
                >
                  <div className="latest-heading">
                    <div className="section-label">
                      <span className="red-dot" />
                      <h2 id="latest-title">
                        {isFiltered ? "Tin dành cho bạn" : "Bài viết chọn lọc"}
                      </h2>
                    </div>
                    <span className="results-count" role="status">
                      {isFiltered
                        ? `${results.length} bài viết phù hợp`
                        : "Thêm một câu chuyện, thêm một góc nhìn"}
                      <ArrowUpRight aria-hidden="true" />
                    </span>
                  </div>
                  {results.length ? (
                    <div className="article-grid">
                      {(isFiltered ? results : remaining).map((article) => (
                        <ArticleCard
                          key={article.id}
                          article={article}
                          onOpen={setSelected}
                        />
                      ))}
                    </div>
                  ) : (
                    <Empty className="py-20">
                      <EmptyHeader>
                        <EmptyMedia variant="icon">
                          <Search />
                        </EmptyMedia>
                        <EmptyTitle>
                          Chưa tìm thấy câu chuyện phù hợp
                        </EmptyTitle>
                        <EmptyDescription>
                          Thử một từ khóa khác hoặc khám phá tất cả chuyên mục.
                          Góc Việt vẫn còn nhiều điều để bạn đọc.
                        </EmptyDescription>
                      </EmptyHeader>
                      <EmptyContent>
                        <Button variant="outline" onClick={reset}>
                          Xem tất cả bài viết
                          <ArrowRight data-icon="inline-end" />
                        </Button>
                      </EmptyContent>
                    </Empty>
                  )}
                </section>
              </>
            )}
          </>
        )}
        <Separator />
        <footer id="ve-goc-viet">
          <div>
            <a className="wordmark footer-wordmark" href="#" onClick={reset}>
              góc<span>việt</span>
              <i>.</i>
            </a>
            <p>Đọc để hiểu. Hiểu để kết nối.</p>
          </div>
          <div className="footer-note">
            <span>Một không gian cho những câu chuyện Việt Nam.</span>
            <span>
              Tin từ nguồn báo · Tóm tắt bằng AI chỉ hiển thị khi đã được duyệt.
            </span>
          </div>
        </footer>
      </main>
      <Dialog
        open={selected !== null}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
      >
        <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
          {selected && <ArticleReader key={selected.id} article={selected} />}
        </DialogContent>
      </Dialog>
    </>
  );
}
export default App;
