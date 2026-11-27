import { expect, test } from "@playwright/test";

const rss = "Mô tả đầy đủ từ báo & thông tin đã công bố.";
const ai = "Bản tóm tắt đầy đủ do AI tạo.\n\nĐoạn cuối không bị cắt.";
const card = {
  id: 1,
  title: "Tin thử nghiệm về giao thông",
  original_url: "https://example.com/news",
  rss_description: rss,
  image_url: null,
  source: { id: 1, name: "Báo thử nghiệm", rss_url: "https://example.com/rss", last_fetched_at: null },
  published_at: "2026-11-27T01:00:00Z",
  created_at: "2026-11-27T01:00:00Z",
  content_origin: "extracted",
  processing_status: "ready",
  category: "society",
  summary_preview: "Bản tóm tắt để mở trình đọc.",
  input_truncated: false,
};
const summary = {
  summary_text: ai,
  keywords: ["giao thông"],
  summarize_model_name: "vit5-fixture",
  agent_model_name: "review-fixture",
  created_at: card.created_at,
  input_truncated: false,
};

for (const scenario of ["both", "rss missing", "ai missing", "both missing", "hidden summary", "not ready", "long text", "literal markup"] as const) {
  test(scenario, async ({ page }, testInfo) => {
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    page.on("console", msg => { if (msg.type() === "error") errors.push(msg.text()); });
    const hasRss = !["rss missing", "both missing"].includes(scenario);
    const hasAi = !["ai missing", "both missing", "hidden summary", "not ready"].includes(scenario);
    const description = scenario === "long text" ? rss.repeat(150) + "END_RSS" :
      scenario === "literal markup" ? '<img src=x onerror="alert(1)"> Literal text' : rss;
    const summaryText = scenario === "long text" ? ai.repeat(150) + "END_AI" : ai;
    const detail = {
      ...card,
      rss_description: hasRss ? description : null,
      processing_status: scenario === "not ready" ? "pending" : "ready",
      ai_generated: scenario !== "hidden summary",
      // Deliberately inconsistent payload in hidden case tests the reader's own guard.
      summary: hasAi || scenario === "hidden summary" || scenario === "not ready" ? { ...summary, summary_text: summaryText } : null,
    };
    await page.route("**/api/v1/articles**", async route => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith("/1")) await new Promise(resolve => setTimeout(resolve, 350));
      return route.fulfill({ json: path.endsWith("/1") ? detail :
        { items: [card], total: 1, page: 1, page_size: 100 } });
    });
    await page.goto("/", { waitUntil: "domcontentloaded" });
    const detailResponse = page.waitForResponse(response =>
      new URL(response.url()).pathname === "/api/v1/articles/1");
    await page.getByRole("button", { name: "Đọc bài viết nổi bật", exact: true }).click();
    const dialog = page.getByRole("dialog");
    const loading = dialog.getByRole("status", { name: "Đang tải tóm tắt" });
    await expect(loading).toBeVisible();
    await detailResponse;
    await expect(loading).toHaveCount(0);
    const rssBlock = dialog.getByRole("region", { name: "Mô tả từ báo", exact: true });
    const aiBlock = dialog.getByRole("region", { name: "Tóm tắt AI", exact: true });
    await expect(dialog.getByRole("link", { name: /Đọc toàn văn trên/ })).toHaveAttribute("href", card.original_url);
    if (hasRss) {
      await expect(rssBlock).toBeVisible();
      await expect(rssBlock.locator(".reader-body")).toHaveText(description);
      await expect(rssBlock.getByText("Nguồn: Báo thử nghiệm", { exact: true })).toBeVisible();
      await expect(rssBlock.locator("img, script, iframe")).toHaveCount(0);
    } else await expect(rssBlock).toHaveCount(0);
    if (hasAi) {
      await expect(aiBlock).toBeVisible();
      await expect(aiBlock.locator(".reader-body")).toHaveText(summaryText);
    } else await expect(aiBlock).toHaveCount(0);
    if (!hasAi && !hasRss) await expect(dialog.getByText(/Bài viết chưa có bản tóm tắt/)).toBeVisible();
    if (scenario === "long text") {
      await aiBlock.locator(".reader-body").scrollIntoViewIfNeeded();
      expect(await dialog.evaluate(e => e.scrollHeight > e.clientHeight)).toBe(true);
      expect(await dialog.evaluate(e => e.scrollWidth <= e.clientWidth + 1)).toBe(true);
    }
    expect(errors).toEqual([]);
    if (scenario === "both" || scenario === "long text") {
      await page.screenshot({ path: testInfo.outputPath("reader.png") });
    }
  });
}
