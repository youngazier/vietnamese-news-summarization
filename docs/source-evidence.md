# Publisher RSS and access evidence

Rechecked on **2026-10-14 (Asia/Ho_Chi_Minh)** for D1.10 and the later D3.1 source review. Scope: a local personal educational news reader. Reassess if the project becomes commercial or publicly hosted.

Official directories establish publisher provenance. Live HTTP checks establish availability. Neither alone establishes permission for full-article extraction, sending publisher text to Gemini, or publishing AI summaries. The decisions below are project interpretations of the cited evidence, not additional permissions granted by publishers.

## Verified feeds

| Publisher | Official directory | Selected feed | HTTP result | Parsed items | Proposed exact host allowlist |
| --- | --- | --- | --- | --- | --- |
| VnExpress | [RSS directory](https://vnexpress.net/rss) | [Latest news](https://vnexpress.net/rss/tin-moi-nhat.rss) | 200; `application/xml; charset=utf-8` | 54 | `vnexpress.net` |
| Tuổi Trẻ | [RSS directory](https://tuoitre.vn/rss.htm) | [Homepage](https://tuoitre.vn/home.rss) | 200; `text/xml` | 50 | `tuoitre.vn` |
| Thanh Niên | [RSS directory](https://thanhnien.vn/rss.html) | [Homepage](https://thanhnien.vn/rss/home.rss) | 200; `text/xml; charset=UTF-8` | 60 | `thanhnien.vn` |

On October 14, direct HTTP checks using `VietnameseNewsSummarization/0.1 (local educational RSS reader)` confirmed the three directories, feeds and robots files returned HTTP 200. Each feed parsed with feedparser without a malformed-feed flag; robots evaluation permitted each selected feed path for that user agent.

All selected URLs were found in their official directory HTML. Each selected feed returned directly without a redirect and parsed successfully as RSS. Counts are observations, not fixed acceptance values. Every observed article link belonged to its publisher's exact host. All feeds supplied title, link, description and publication-date elements; individual entries must still be validated during ingestion.

Tuổi Trẻ's previously suggested `/rss/tin-moi-nhat.rss` redirected to `/home.rss`; use the publisher-linked `/home.rss` URL above.

The proposed allowlists cover feed/article navigation only. They do not authorize fetching article pages, wildcard subdomains, image/CDN hosts, or cross-host redirects.

## VnExpress

**Evidence:** The official [RSS page](https://vnexpress.net/rss), under its usage terms, offers feeds free to individuals and nonprofit organizations, requires clear source information, and reserves the right to request cessation of distribution. Its RSS explanation describes reader access to headlines, excerpts and original links.

**Project interpretation:** Personal/nonprofit RSS reader use with attribution is supported. Display `Nguồn: VnExpress` and an original-article link on each item. The page does not explicitly authorize full-article extraction, third-party AI processing, or publication of generated summaries; those remain unverified.

**Robots observation:** [robots.txt](https://vnexpress.net/robots.txt) returned HTTP 200. The wildcard group allows `/`; several named crawlers have separate prohibitions. Evaluate the rules for the actual application's user agent before future requests.

**Decision:** Reviewed for attributed RSS-only reader ingestion within the stated scope. Keep article extraction disabled and resolve AI use separately before enabling the summarization pipeline for this source.

## Tuổi Trẻ

**Evidence:** The official [RSS page](https://tuoitre.vn/rss.htm), under its usage terms, offers feeds free to individuals and nonprofit organizations, requests clear source information, and reserves the right to stop redistribution. The footer retains copyright over website content.

**Project interpretation:** Personal/nonprofit RSS reader use with attribution is supported. Display `Nguồn: Tuổi Trẻ` and an original-article link. Full-article extraction, third-party AI processing and generated-summary publication are not explicitly covered by the reviewed RSS terms.

**Robots observation:** [robots.txt](https://tuoitre.vn/robots.txt) returned HTTP 200. The wildcard group allows `/` but excludes search, print, selected login/scripts and other paths. The selected `/home.rss` path is not excluded.

**Decision:** Reviewed for attributed RSS-only reader ingestion within the stated scope. Keep article extraction disabled and resolve AI use separately. Do not fetch subscriber-only content or bypass Tuổi Trẻ Sao access controls.

## Thanh Niên

**Evidence:** The official [RSS page](https://thanhnien.vn/rss.html) provides feed-reader instructions and requires attribution when reusing news: “Theo Báo Thanh Niên” or “Báo Thanh Niên”. Its footer also prohibits copying without written consent.

**Project interpretation:** Publisher-offered RSS reader access is documented, but the scope of permitted storage/redistribution is unclear alongside the broader copyright restriction. Attribution alone does not resolve that ambiguity. Use `Theo Báo Thanh Niên` and the original link if reuse is subsequently approved.

**Robots observation:** [robots.txt](https://thanhnien.vn/robots.txt) returned HTTP 200. The wildcard group allows `/`, excluding `/tim-kiem.htm` and `/news-*.htm`; `/rss/home.rss` is not excluded.

**Decision:** Feed provenance and availability verified; leave ingestion disabled pending clarification of reuse. Full-article extraction, third-party AI processing and generated-summary publication remain unverified. No publisher permission was requested during this review. The renewed official-page review did not resolve the conflicting reuse wording.

## Implementation decisions and outstanding gates

These are application safeguards and proposed defaults, not publisher-specified rate limits:

- Use HTTPS and the exact host allowlists above. Validate every redirect destination and reject unreviewed hosts.
- Identify the application honestly with a user agent; do not impersonate an allowed crawler.
- Begin with the planned 30-minute collection interval, modest concurrency, bounded timeouts and backoff. Honor access denials and any publisher request to stop.
- Preserve attribution and original links. Render cleaned plain text from RSS descriptions; do not fetch embedded images or render RSS HTML directly.
- Record RSS-only text as `content_origin=rss_excerpt`; never label it as a full article. Insufficient excerpts must not be summarized as if complete.
- Recheck terms and robots rules before activating collection and when behavior or deployment scope changes. Robots permissions describe crawler access, not a content reuse license.

| Gate | Status |
| --- | --- |
| D1.10: begin dated publisher feed/access evidence | Complete for these three candidates |
| Three publisher-offered feeds reachable as XML | Verified on the checked date |
| VnExpress/Tuổi Trẻ personal/nonprofit RSS-reader scope | Supported by reviewed RSS terms; attribution and cessation conditions apply |
| Thanh Niên ingestion/reuse scope | Unresolved; keep disabled |
| Full-article extraction for all three | Unresolved; keep disabled |
| Sending source text to Gemini / publishing generated summaries | Unresolved for all three |
| D3.1: three sources cleared for intended ingestion scope | Pending; do not mark complete from availability alone |

D3.2 stores all three reviews in `config/sources.json`. `app.seed_sources` validates the file before opening a database session and upserts only name, RSS URL and active status. VnExpress and Tuổi Trẻ are active for the reviewed personal RSS-reader scope; Thanh Niên remains inactive. The D3 collector enforces active/reviewed status, exact HTTPS host allowlists and redirect validation before fetching. Extraction and AI processing remain disabled in every configuration record and are not performed by the D3 ingestion path.

On 2026-10-14, the permitted live D3 check collected VnExpress only: 51 usable feed entries were parsed, 20 were inserted under the configured cap, replaying the same attempted entries inserted zero rows, and the stored pending article was returned through REST. This verifies the implemented feed path; it does not grant extraction or AI-processing permission and does not clear Thanh Niên.

On 2026-10-15, the Day 4 RSS-only adequacy check fetched the two active feeds:
VnExpress returned 51 usable entries (2 excerpts at least 200 cleaned characters),
and Tuổi Trẻ returned 50 (6 at least 200). No publisher article pages or AI services
were called. Existing VnExpress development rows were labeled from stored RSS
excerpts with `rss_excerpt` provenance: 1 pending, 19 needs review. Repeating
preparation changed zero rows. Article extraction and AI flags remain disabled;
these observations do not change permission decisions. See [Day 4 details](day-4-extraction.md).

## Reproduce availability checks

From the repository root, this standard-library check fetches only the three feeds and prints response metadata and XML item counts. It does not download article pages or prove reuse permission.

```sh
python - <<'PY'
import urllib.request
import xml.etree.ElementTree as ET

feeds = [
    "https://vnexpress.net/rss/tin-moi-nhat.rss",
    "https://tuoitre.vn/home.rss",
    "https://thanhnien.vn/rss/home.rss",
]
for url in feeds:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "VietnameseNewsSummarization/0.1 (local educational feed verification)"
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = response.read(2_000_001)
        if len(payload) > 2_000_000:
            raise ValueError("Feed exceeds verification size limit")
        root = ET.fromstring(payload)
        if root.tag != "rss" or root.find("channel") is None:
            raise ValueError("Expected an RSS channel")
        print(url, response.status, response.url,
              response.headers.get("Content-Type"),
              "items=", len(root.findall("./channel/item")))
PY
```

This manual diagnostic follows redirects using urllib and remains useful for evidence review. The implemented D3 collector disables automatic redirects, validates each destination against the exact configured HTTPS hosts, and counts redirects against its three-request budget.


## Day 6 user-authorized acceptance exception — 2026-10-15

After selecting VnExpress's World feed, the user explicitly authorized one linked
public article's full text for local ViT5 and Gemini review. The feed's official
link and robots access were verified; 60 RSS excerpts were all below the existing
200-character adequacy threshold. The one-off extraction policy was restricted to
[the selected article](https://vnexpress.net/sap-mai-truong-hoc-tai-pakistan-it-nhat-35-nguoi-chet-5132860.html)
and its public content container.

The real result is stored as source 4 / article 41, approved and visible through
REST after a controlled manual retry for an intermittent provider failure. The
previous rejected RSS candidate, article 5, stays hidden. See the [Day 6 evidence](day-6-review.md)
for source fidelity, bounds, failure/retry history and HTTP verification.

This records the user's one-off test authorization, not new publisher permission
for ongoing full-article extraction, Gemini processing or generated-summary
redistribution. The committed source configuration and unresolved policy gates
above are unchanged.
