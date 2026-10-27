import { Skeleton } from "@/components/ui/skeleton";
export function NewsSkeleton() {
  return (
    <div role="status" aria-label="Đang tải tin tức" className="news-skeleton">
      <span className="sr-only">Đang tải tin tức…</span>
      <Skeleton className="h-96 w-full" />
      <div className="article-grid">
        {[1, 2, 3].map((id) => (
          <div key={id} className="flex flex-col gap-4">
            <Skeleton className="aspect-[16/10] w-full" />
            <Skeleton className="h-7 w-4/5" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-3/5" />
          </div>
        ))}
      </div>
    </div>
  );
}
