import { ArrowUpRight, Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { type Category } from "@/data/articles";

interface Props {
  query: string;
  reviewing: boolean;
  onReview: () => void;
  onQuery: (query: string) => void;
  onCategory: (category: Category) => void;
}
export function NewsHeader({
  query,
  onQuery,
  onCategory,
  reviewing,
  onReview,
}: Props) {
  return (
    <header className="site-header">
      <div className="utility-bar container">
        <span>Một góc nhìn, nhiều câu chuyện.</span>
        <span>
          Ấn bản trải nghiệm <span className="utility-dot">•</span> Tiếng Việt
        </span>
      </div>
      <div className="main-header container">
        <a
          className="wordmark"
          href="#"
          aria-label="Góc Việt — Trang chủ"
          onClick={() => {
            onCategory("Tất cả");
            onQuery("");
          }}
        >
          góc<span>việt</span>
          <i>.</i>
        </a>
        <nav className="desktop-nav" aria-label="Điều hướng chính">
          <a
            href="#tin-moi"
            onClick={() => {
              onCategory("Tất cả");
              onQuery("");
            }}
          >
            Khám phá
          </a>
          <a href="#tin-moi" onClick={() => onCategory("Chính trị")}>
            Chính trị
          </a>
          <a href="#tin-moi" onClick={() => onCategory("Xã hội")}>
            Xã hội
          </a>
          <a
            href="#duyet-bai"
            aria-current={reviewing ? "page" : undefined}
            onClick={onReview}
          >
            Duyệt bài
          </a>
          <a href="#ve-goc-viet">
            Về Góc Việt <ArrowUpRight aria-hidden="true" />
          </a>
        </nav>
        <div className="header-actions">
          {!reviewing && (
            <div className="search-field" role="search">
              <Search aria-hidden="true" />
              <Input
                type="search"
                aria-label="Tìm kiếm tin tức"
                placeholder="Tìm điều bạn quan tâm..."
                value={query}
                onChange={(e) => onQuery(e.target.value)}
              />
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
