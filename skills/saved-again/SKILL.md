---
name: saved-again
description: Analyze and organize a personal Instagram Saved library into a private Matchbox Collection dashboard with nested topics, search and useful revisit reminders. Use for importing saved reels/posts, resuming a browser capture, categorizing the library, improving category accuracy, or finding saved references.
license: Personal noncommercial terms in LICENSE
metadata:
  requirements: Requires Python 3.11+, Node.js 24+, local command execution and filesystem access. Local reel analysis additionally requires FFmpeg and explicitly installed local analyzer models. Instagram imports require supported browser tools connected to the user's logged-in session. No paid AI API is required.
---

# SavedAgain

Turn Instagram saves into useful, navigable collections. The complete dashboard is bundled in [assets/dashboard](assets/dashboard). Use the assistant's existing reasoning for organization; do not require another AI service.

SavedAgain is an independent personal project, not affiliated with, endorsed by or sponsored by Instagram or Meta. It is free for personal, noncommercial use only under [LICENSE](LICENSE). Users remain responsible for platform terms, privacy and content rights.

## Start or reopen

1. Check terminal/filesystem capabilities and read [local operation](references/local-operation.md). Resolve bundled paths relative to this skill, never a previous user's machine. Use `doctor` when diagnosing a new installation; it reports optional capabilities without silently installing models.
2. Run the manager's `status` command for the selected workspace. If needed, run `setup`, then `start`. Default workspace: `~/SavedAgain`; app and private library are separate subdirectories. Do not copy data into this skill.
3. Open the returned local URL through the available supported browser tool. Retrieve this installation's key with `key` only when needed to unlock the local app. Keep the key out of URLs, public artifacts and logs.
4. For import/resume, read [browser capture](references/browser-capture.md). Check the host's browser documentation and confirm access to the user's logged-in Instagram session. If tools/login are missing, report the missing capability and pause importing. Do not substitute pasted links/captions, exported Instagram files, cookie extraction, private APIs or an automated downloader.

## Import and organize

Confirm the visible account is the intended account. Read [capture format and API](references/capture-format.md) before submitting batches. Capture the complete accessible Saved grid in batches of at most 25, preserve stable shortcodes, collection memberships and capture order, and acknowledge each durable batch before advancing. Resume from checkpoints rather than starting over blindly.

Read [classification](references/classification.md) before assigning or revising categories. Use only inspected captions, visible thumbnails and inspected carousel slides as evidence. Write short descriptive titles, takeaways, suggested uses and tags. Use nested categories, create suitable new categories when the saves justify them, and preserve manual corrections and notes. Generic captions, conflicting evidence and unclear previews belong in Needs review. Mark suggestions as suggestions. Do not claim to have watched a video or heard audio that was not inspected.

For deeper analysis of a large Needs review queue, on-screen text, speech or representative video frames, read [optional local analysis](references/local-analysis.md). These analyzers enrich evidence; they do not authorize obtaining media, bypassing Instagram controls or silently replacing user corrections.

When the user chooses an always-available private mirror, read [Cloudflare dashboard](references/cloud-dashboard.md). Keep the Mac canonical, filter the cloud projection, protect the custom domain with Cloudflare Access and use D1/R2 only for safe metadata and compressed previews. Pull cloud mutations before pushing local state. Never upload raw captions, OCR, transcripts, embeddings, frames, audio or source reels.

Stop browser requests on HTTP 429, challenges or interrupted access. A global access limit is not proof that individual posts are unavailable. Report partial results with the resumable queue. Do not claim complete traversal from a stalled scroll; confirm the settled end repeatedly and check named collections for omissions.

## Revisit and maintain

Use search and category/subcategory filters to retrieve a small useful set. Use the existing digest for diverse reminders; respect snooze, dismissal and Tried it. Update favourites, notes and corrections only within the user's request. Back up before a requested restore/update that affects an existing installation. Downloads remain optional user-selected shortcuts. Keep Analyze deeper removed.

## Verify the dashboard

After first setup, dashboard updates, or imports that introduce new categories or unusually long labels, follow [visual checks](references/visual-checks.md) before handoff. Inspect the complete category grid and custom covers, plus collections/search, item details and settings at phone and laptop widths. Keep cover text inside its frame and check the actual page end above fixed navigation. Correct supported layout defects and verify the new render. For an unchanged library lookup, reuse the existing verification unless the user reports a problem.

## Handoff

Provide the running URL, distinct captured count, organized/Needs review counts, missing previews, incomplete context and access gaps. Explain that category counts can overlap. Separate complete grid traversal from incomplete enrichment. Report which views and actual viewport widths were visually checked, along with any unverified surfaces; a passing build alone does not establish visual correctness. Leave the dashboard available through the host's supported handoff mechanism. Keep Instagram read-only and leave its credentials in the browser.
