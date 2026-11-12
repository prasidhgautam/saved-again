# Capture format and local API

Use the printed localhost origin. All `/api/` and `/media/` endpoints require a local session cookie or `Authorization: Bearer LOCAL_ACCESS_KEY`, except `/api/session` and minimal `/api/health`. Keep keys in private files and request headers, never in URLs or committed examples. Mutations reject foreign browser origins.

`POST /api/import` accepts an object with `records`, an optional `coverage` patch and a unique `batch_id`. The CLI reads this object from a private file after real browser capture and verifies the same batch ID in the response. Repeating a batch deduplicates by shortcode and preserves user edits. The server saves the raw batch before upserting records, so a failed commit is recoverable.

Record fields:

- Required: `id` (observed shortcode), `url` (canonical https Instagram post/reel URL).
- Captured: `caption`, visible alt text, `thumbnail_url`, `creator`, `media_type` (`post`, `reel`, `video`, `carousel`), `collections` (names), `order` (capture index), and `capture_status` when the grid item needs later inspection.
- Inspection: `caption_source: post` for a recovered owner caption, `inspected_at` (ISO timestamp), `access_status` (`available`, `caption_unavailable`, `inaccessible`). Do not mark a failed rate-limited attempt inspected.
- Derived: `title`, `summary`, `use_when`, `tags`, primary `category` ID and `subcategory`, and `categories` as objects with those two keys. Set `curated: true` when supplying inspected, semantically organized content. Evidence is `caption`, `visual`, or limited `thumbnail` context. Missing source evidence must not become an invented summary.

Read `GET /api/categories` before organizing. Built-in categories are useful starters, not a mandatory taxonomy. `POST /api/categories` accepts `id` (lowercase hyphenated slug) and `name`; optional `art` must be a bundled cover and `color` a six-digit hex. New categories use neutral matchbox artwork by default. `PATCH /api/categories/{id}` renames or changes presentation without changing its stable ID. Subcategories are strings stored on item memberships. Create a custom category before importing its records.

Coverage patches may include `account`, `status` (`capturing`, `partial`, `complete`), `message`, `discovered`, `all_posts_end_confirmed`, `settled_end_checks`, `named_collections`, `collection_omissions`, `details_processed`, `caption_enrichment_remaining` and `browser_blocker`. Set complete only when requested traversal and enrichment are actually finished. A confirmed grid end may coexist with partial enrichment.

Useful endpoints:

- `GET /api/checkpoint`: persisted shortcode/capture positions and coverage.
- `GET /api/enrichment-queue`: captions still awaiting inspection; `?kind=previews` for missing preview URLs.
- `GET /api/library`: categories, primary organization counts, preview/cache and access counts.
- `GET /api/items?category=ID&subcategory=NAME&q=TEXT&page=1&size=24`; `GET /api/items/{id}`.
- `PATCH /api/items/{id}`: notes, favourite, tried, dismissed, snoozed_until, or manual category/subcategory. Manual filing wins over subsequent imports.
- `GET /api/digest`: up to three diverse eligible references. `POST /api/digest/seen` with `ids` records a viewed reminder.
- `GET /api/capabilities`: whether this is the local private service or cloud mirror and which analysis/upload features are available.
- `POST /api/items/{id}/media`: local multipart attachment for a user-provided reel. `GET /api/analysis/jobs?post_id=…` and `POST /api/analysis/jobs/{job}/retry` expose resumable stages.
- `POST /api/analysis/inbox/scan`: scan the private watched inbox without deleting originals.
- `GET /api/sync/status`; `POST /api/sync/run`: inspect or trigger the configured Cloudflare mirror.
- `GET /api/export`; `POST /api/restore` for the versioned JSON backup. Full archive backup/restore uses the manager.

Category memberships can overlap; their counts do not sum to the distinct library count. Full-text search covers titles, summaries, original captions, tags, creators, subcategories and suggested uses. Original thumbnails are cached only from observed allowed Instagram CDN image URLs. Missing images never block record import; videos are not automatically downloaded.
