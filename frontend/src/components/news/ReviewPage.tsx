import { useEffect, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  Check,
  LoaderCircle,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Empty,
  EmptyHeader,
  EmptyTitle,
  EmptyDescription,
} from "@/components/ui/empty";
import {
  Field,
  FieldGroup,
  FieldLabel,
  FieldDescription,
  FieldError,
} from "@/components/ui/field";
import { Textarea } from "@/components/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { categoryLabels, originalArticleUrl } from "@/data/articles";
import { cn } from "@/lib/utils";
import {
  getReviews,
  getReview,
  submitReview,
  ReviewError,
  type ReviewFilter,
  type ReviewPageData,
  type ReviewDetail,
  type ReviewDecision,
} from "@/services/reviews";

const filters: { value: ReviewFilter; label: string }[] = [
  { value: "pending", label: "Chờ duyệt" },
  { value: "accept", label: "Đã chấp nhận" },
  { value: "decline", label: "Đã từ chối" },
];
export function ReviewPage({ onReviewed }: { onReviewed: () => void }) {
  const [filter, setFilter] = useState<ReviewFilter>("pending");
  const [page, setPage] = useState(1);
  const [generation, setGeneration] = useState(0);
  const [message, setMessage] = useState("");
  const onDecided = (decision: ReviewDecision) => {
    setMessage(
      decision === "accept"
        ? "Đã chấp nhận. Bản tóm tắt đã được xuất bản trong trình đọc tin."
        : "Đã từ chối. Bản tóm tắt được giữ lại để tra cứu và không được xuất bản.",
    );
    setPage(1);
    setGeneration((value) => value + 1);
    onReviewed();
  };
  return (
    <section
      id="duyet-bai"
      className="review-page"
      aria-labelledby="review-heading"
    >
      <div className="review-heading">
        <div className="eyebrow">
          <span className="red-dot" /> BIÊN TẬP & KIỂM CHỨNG
        </div>
        <h1 id="review-heading">
          Duyệt bản tóm tắt<span>.</span>
        </h1>
        <p>
          Đối chiếu với nguồn gốc trước khi chấp nhận hoặc từ chối bản nháp.
        </p>
      </div>
      {message && (
        <Alert role="status">
          <Check />
          <AlertTitle>Đã lưu quyết định</AlertTitle>
          <AlertDescription>{message}</AlertDescription>
        </Alert>
      )}
      <ToggleGroup
        aria-label="Trạng thái duyệt"
        value={[filter]}
        onValueChange={(values) => {
          if (values.length) {
            setFilter(values[0] as ReviewFilter);
            setPage(1);
            setMessage("");
          }
        }}
      >
        {filters.map((item) => (
          <ToggleGroupItem value={item.value} key={item.value}>
            {item.label}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
      <ReviewQueue
        key={`${filter}-${page}-${generation}`}
        filter={filter}
        page={page}
        onPage={setPage}
        onDecided={onDecided}
      />
    </section>
  );
}
function ReviewQueue({
  filter,
  page,
  onPage,
  onDecided,
}: {
  filter: ReviewFilter;
  page: number;
  onPage: (page: number) => void;
  onDecided: (decision: ReviewDecision) => void;
}) {
  const [data, setData] = useState<ReviewPageData | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    getReviews(filter, page, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) {
          setData(result);
          setError("");
          setSelected(
            (result.items.find((item) => item.can_review) ?? result.items[0])
              ?.id ?? null,
          );
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted)
          setError(
            error instanceof Error
              ? error.message
              : "Không thể tải danh sách duyệt.",
          );
      });
    return () => controller.abort();
  }, [filter, page, attempt]);
  if (error)
    return (
      <Alert variant="destructive">
        <AlertTitle>Không thể tải danh sách</AlertTitle>
        <AlertDescription>
          {error}
          <Button
            variant="outline"
            onClick={() => {
              setError("");
              setAttempt((value) => value + 1);
            }}
          >
            Thử lại
          </Button>
        </AlertDescription>
      </Alert>
    );
  if (!data)
    return (
      <div
        role="status"
        aria-label="Đang tải danh sách duyệt"
        className="flex flex-col gap-4"
      >
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  if (!data.items.length)
    return (
      <Empty className="py-20">
        <EmptyHeader>
          <EmptyTitle>Không có bài viết trong danh sách này</EmptyTitle>
          <EmptyDescription>
            Chọn một trạng thái khác để xem các bản nháp.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  return (
    <>
      <p className="review-count" role="status">
        {data.total} bài viết · Trang {data.page}/
        {Math.ceil(data.total / data.page_size)}
      </p>
      <div className="review-layout">
        <aside className="review-queue" aria-label="Danh sách bài cần duyệt">
          {data.items.map((item) => (
            <button
              key={item.id}
              className={cn(
                "review-queue-item",
                selected === item.id && "review-queue-selected",
              )}
              aria-pressed={selected === item.id}
              onClick={() => setSelected(item.id)}
            >
              <span>{item.source.name}</span>
              <strong>{item.title}</strong>
              <Badge variant="outline">
                {item.decision === "accept"
                  ? "Đã chấp nhận"
                  : item.decision === "decline"
                    ? "Đã từ chối"
                    : item.can_review
                      ? "Có bản nháp"
                      : item.has_draft
                        ? "Chưa thể duyệt"
                        : "Chưa có bản nháp"}
              </Badge>
            </button>
          ))}
        </aside>
        {selected && (
          <ReviewEditor key={selected} id={selected} onDecided={onDecided} />
        )}
      </div>
      <div className="review-pagination">
        <Button
          variant="outline"
          disabled={page === 1}
          onClick={() => onPage(page - 1)}
        >
          <ArrowLeft data-icon="inline-start" />
          Trang trước
        </Button>
        <Button
          variant="outline"
          disabled={page * data.page_size >= data.total}
          onClick={() => onPage(page + 1)}
        >
          Trang sau
          <ArrowRight data-icon="inline-end" />
        </Button>
      </div>
    </>
  );
}
function ReviewEditor({
  id,
  onDecided,
}: {
  id: number;
  onDecided: (decision: ReviewDecision) => void;
}) {
  const [detail, setDetail] = useState<ReviewDetail | null>(null);
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [note, setNote] = useState("");
  const [validation, setValidation] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    getReview(id, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) {
          setDetail(result);
          setError("");
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted)
          setError(
            error instanceof Error ? error.message : "Không thể tải bản nháp.",
          );
      });
    return () => controller.abort();
  }, [id, attempt]);
  const reload = () => {
    setDetail(null);
    setError("");
    setConflict(false);
    setValidation("");
    setNote("");
    setAttempt((value) => value + 1);
  };
  const decide = async (decision: ReviewDecision) => {
    if (!detail || saving || conflict) return;
    if (decision === "decline" && !note.trim()) {
      setValidation("Vui lòng nhập lý do từ chối.");
      document.getElementById("review-note")?.focus();
      return;
    }
    setSaving(true);
    setError("");
    setValidation("");
    try {
      await submitReview(id, decision, detail.version, note);
      onDecided(decision);
    } catch (error) {
      setError(
        error instanceof Error ? error.message : "Không thể lưu quyết định.",
      );
      setConflict(error instanceof ReviewError && error.status === 409);
    } finally {
      setSaving(false);
    }
  };
  const original = detail ? originalArticleUrl(detail.original_url) : undefined;
  return (
    <section className="review-editor" aria-label="Nội dung duyệt">
      {error && (
        <Alert variant="destructive">
          <AlertTitle>
            {conflict ? "Bản nháp đã thay đổi" : "Không thể hoàn tất"}
          </AlertTitle>
          <AlertDescription>
            {error}
            <Button variant="outline" onClick={reload} disabled={saving}>
              Tải lại bản nháp
            </Button>
          </AlertDescription>
        </Alert>
      )}
      {!detail ? (
        !error && (
          <div
            role="status"
            aria-label="Đang tải bản nháp"
            className="flex flex-col gap-4"
          >
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-64 w-full" />
          </div>
        )
      ) : (
        <>
          <header>
            <h2>{detail.title}</h2>
            {original && (
              <a
                className="reader-source-link"
                href={original}
                target="_blank"
                rel="noopener noreferrer"
              >
                Đọc bài gốc trên {detail.source.name}
                <ArrowUpRight aria-hidden="true" />
                <span className="sr-only"> (mở trong tab mới)</span>
              </a>
            )}
          </header>
          {detail.reason && (
            <Alert>
              <AlertTitle>
                {detail.has_draft
                  ? "Chưa thể duyệt"
                  : "Chưa có bản tóm tắt để duyệt"}
              </AlertTitle>
              <AlertDescription>{detail.reason}</AlertDescription>
            </Alert>
          )}
          {detail.decision && (
            <Alert>
              <AlertTitle>
                {detail.decision === "accept" ? "Đã chấp nhận" : "Đã từ chối"}
              </AlertTitle>
              <AlertDescription>
                {detail.note || "Quyết định đã được lưu."}
              </AlertDescription>
            </Alert>
          )}
          <div className="review-comparison">
            <section>
              <h3>Văn bản nguồn</h3>
              <p className="review-context">
                {detail.content_origin === "rss_excerpt"
                  ? "Chỉ có trích đoạn RSS"
                  : "Nội dung đã thu thập từ bài gốc"}
              </p>
              <p className="review-text">
                {detail.source_text || "Chưa thu thập được văn bản nguồn."}
              </p>
            </section>
            <section>
              <h3>Bản nháp tóm tắt</h3>
              {detail.draft ? (
                <>
                  <Badge variant="secondary">
                    {categoryLabels[detail.draft.category]}
                  </Badge>
                  <p className="review-text">{detail.draft.text}</p>
                  <div className="flex flex-wrap gap-2">
                    {detail.draft.keywords.map((keyword) => (
                      <Badge key={keyword} variant="outline">
                        {keyword}
                      </Badge>
                    ))}
                  </div>
                  <h4>Nhận xét từ AI</h4>
                  <p className="review-context">
                    {detail.draft.ai_feedback || "Không có nhận xét."}
                  </p>
                  <p className="review-context">
                    Đã tạo {detail.draft.attempts} lần
                    {detail.draft.input_truncated &&
                      " · Văn bản đầu vào đã bị cắt ngắn"}
                    .
                  </p>
                </>
              ) : (
                <p className="review-context">
                  Chưa có bản nháp. Không thể chấp nhận hoặc từ chối.
                </p>
              )}
            </section>
          </div>
          {detail.can_review && (
            <form onSubmit={(event) => event.preventDefault()}>
              <FieldGroup>
                <Field data-invalid={!!validation}>
                  <FieldLabel htmlFor="review-note">Ghi chú duyệt</FieldLabel>
                  <Textarea
                    id="review-note"
                    value={note}
                    maxLength={1000}
                    disabled={saving}
                    aria-invalid={!!validation}
                    aria-describedby="review-note-help"
                    onChange={(event) => {
                      setNote(event.target.value);
                      setValidation("");
                    }}
                    placeholder="Ghi lý do từ chối hoặc nhận xét của bạn…"
                  />
                  <FieldDescription id="review-note-help">
                    Bắt buộc khi từ chối. Tối đa 1.000 ký tự.
                  </FieldDescription>
                  {validation && <FieldError>{validation}</FieldError>}
                </Field>
              </FieldGroup>
              <div className="review-actions">
                <Button
                  type="button"
                  variant="outline"
                  disabled={saving || conflict}
                  onClick={() => void decide("decline")}
                >
                  <X data-icon="inline-start" />
                  Từ chối
                </Button>
                <Button
                  type="button"
                  disabled={saving || conflict}
                  onClick={() => void decide("accept")}
                >
                  {saving ? (
                    <LoaderCircle
                      data-icon="inline-start"
                      className="animate-spin"
                    />
                  ) : (
                    <Check data-icon="inline-start" />
                  )}
                  {saving ? "Đang lưu…" : "Chấp nhận & xuất bản"}
                </Button>
              </div>
            </form>
          )}
        </>
      )}
    </section>
  );
}
