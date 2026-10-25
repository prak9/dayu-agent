# Recover Research PDFs Without Losing Evidence

Use when a material filing, earnings-call transcript, presentation or specialist report cannot be read through the current web/PDF tool. A tool's `Internal Error`, 403, truncated extract or blank text does not establish that the document is unavailable or undisclosed. Recover the original when feasible before substituting a secondary transcript.

## Download Separately From Reading

Resolve the actual PDF link from the publisher's document inventory or download link; do not guess a CDN filename. A report landing page and its attachment are different resources. Preserve the publisher page as provenance, and check issuer, title, period, language and version after downloading. Do not silently replace a call/Q&A with the earnings press release.

Use the bundled helper when direct web reading fails:

```bash
python3 invest/scripts/read_research_pdf.py 'https://publisher.example/report.pdf' --output-dir /path/to/research-artifacts
```

It uses a bounded GET, follows HTTP(S) redirects, encodes literal URL spaces without double-encoding existing `%20`, and identifies itself as `InvestResearch/1.0 (public document retrieval)`. It does not impersonate a browser. Some public CDNs reject curl's default user agent while serving a clearly identified document client; this was reproduced with Alibaba's official June 2026 call PDF. HEAD failure alone is not a GET result. No repeated UA rotation, proxy rotation, credentials or security-control bypass is part of this helper. Persistent 401/403, CAPTCHA, paywall or rate-limit responses call for another authorized source, not an infinite retry loop.

Each invocation creates a fresh artifact directory and preserves the raw PDF, response headers, final URL, fetch time, SHA-256, extraction warnings and a manifest. The fetch time is **not** the publication date; HTTP `Last-Modified` alone does not prove first public availability. Headers/URLs can contain tokens: retain artifacts privately and outside git; publish only suitable original-source links, never authentication data.

Requires existing `curl` and Poppler's `pdftotext`; it does not install packages or change machine configuration. A browser-downloaded/local PDF can be passed as `source` to use the same checks and extraction. Local-file provenance must still be supplied by the researcher.

## Interpret The Result, Then Inspect Relevant Pages

| Status | Meaning and next action |
|---|---|
| `text_extracted` | Nonempty text on every extracted page, **not proof of complete reading**. Read the required prepared remarks/Q&A or statement context; visually inspect material tables/charts and doubtful text. |
| `partial_text` | Some physical pages have no extracted text; use `empty_pages` to inspect them. A blank separator is not necessarily a failed page. |
| `needs_ocr` | No useful text layer. Render the relevant pages and read visually or use an already available OCR tool; label OCR and verify important numbers against the image. |
| `not_pdf` | Often an HTTP 200 HTML error/login/landing page. Do not parse it as the report or cite it as read. Resolve the actual attachment or another source. |
| `fetch_failed` / `fetch_unavailable` | Record HTTP/network/tool reason. A partial 206 response is not accepted as a full document. Use a verified alternative route. |
| `parse_failed` / `parser_unavailable` | Bytes may be available even though text is not. Inspect the retained PDF with an available PDF viewer/rendering tool, or use another parser already installed. |

Exit `0` means `text_extracted`; all other statuses exit `2` with a JSON result and manifest. Inspect the status/artifacts rather than treating failure as an absent source. Even a page with text can have an image-only financial table; blank-page detection cannot certify completeness.

`pages.txt` labels **1-based physical PDF pages**, which may differ from printed page numbers. To inspect physical pages 10–11 using installed Poppler:

```bash
pdftoppm -f 10 -l 11 -scale-to 1800 -png /path/to/source.pdf /path/to/page
```

View those images with the available image tool. OCR only the relevant pages when useful; do not require a full-document OCR pass or an upload to an unapproved third-party service. Preserve signs, units, column dates and footnotes, and label physical versus printed page locators. Encrypted documents requiring a password need legitimate access, not a password-cracking workaround.

## Alternative Originals And Genuine Limits

When direct download remains unavailable, check the same issuer's IR archive and SEC/HKEX/local-exchange attachment inventory, or an already authorized browser session's ordinary download. Follow real links. An alternate original must match the period/document type and relevant content; an amended filing is new evidence, not a silent replacement for a historical version. Use a secondary publisher only with explicit attribution and the remaining original-access limitation.

If an original becomes available after an earlier secondary-source analysis, compare the decisive passages, especially units, speaker attribution, prepared remarks versus Q&A and forward targets. Correct only affected claims, models and summaries; report whether the old conclusion changes. Retrieving a PDF does not itself authorize updating a previously archived Notion report.

Retain the successful route, verified title/period, pages read, hash and unresolved image/OCR gaps in existing research artifacts. A failed first request is not a stopping criterion; conversely, an actual access boundary is not something a skill can guarantee away.
