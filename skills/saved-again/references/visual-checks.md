# Visual checks before dashboard handoff

Use this after first setup, layout updates, imports introducing new categories/long labels, or a reported visual defect. Routine retrieval from an unchanged, verified library does not need a fresh full audit. Use the host's documented browser controls; no separate design plugin is required.

## Capture the actual running app

Confirm the intended workspace and printed local URL. Inspect the current rendered page before changing it. After rebuilding, refresh and wait for the intended content and images to settle. Verify the actual DOM viewport dimensions when available: a requested viewport can differ from the captured one because of browser zoom, density or an inactive tab.

Check the user's current width, narrow phone (320 px), typical phone (390 px), tablet/small laptop (1024 px) and laptop (1440 px) when responsive controls are available. Preserve and reset temporary viewport overrides. If a width or screen cannot be inspected, report it as unverified instead of claiming a complete visual pass.

Save and open screenshots of the checked screens. Reject wrong-tab, stale, loading or incorrectly cropped frames. Keep personal screenshots outside source and release artifacts. Compare before/after screenshots together at the same width and state when fixing a reported defect.

## Inspect four surfaces

1. **Library:** inspect the complete category grid through its last row. Check every cover, especially custom categories. Titles stay inside the printed frame, headings remain readable, subtopics wrap without collisions, and preview captions/actions align within a row. Check header/search spacing, missing-preview fallbacks and the footer. Looking only at the first three categories is insufficient.
2. **Collections and search:** open a custom category, a nested filter and search results. Check long headings, breadcrumbs, filter chips, result titles and pagination where present. A short caption or a single result must not break spacing.
3. **Item details:** inspect the title, category evidence, preview, actions, notes and filing/reminder controls on a narrow phone. The close button stays separate. Vertical dialog scrolling is expected; horizontal scrolling, overlapping buttons and clipped fields are defects.
4. **Settings and page end:** inspect coverage counts, export and category management. Scroll to the real end of the library and ensure the final item's title/actions can clear the fixed navigation. Full-page screenshots can place fixed navigation at the original viewport position; inspect the actual scrolled viewport before treating that capture artifact as an overlap.

## Dynamic text and cover safeguards

Inspect the longest actual category/subcategory names. For layout changes, also test a long multiword name and an unbroken name approaching the 80-character category limit in an isolated synthetic workspace. Never rename a user's real categories or insert demo items into their library just to test layout.

Custom cover labels and missing-art fallbacks need separate scoped styles. A broad `.art > span` selector previously applied fallback font size, padding, color and aspect ratio to an absolute custom label, causing it to cross the matchbox border. Preserve the bundled fix: size text relative to the cover, constrain it to the inset frame, and bound line count. Keep the full name available through the heading/navigation and accessible label. Do not solve an overlap by obscuring other content or making all labels unreadable.

Where DOM inspection is supported, check that document scrollWidth does not exceed viewport width, visible controls stay within the viewport, cover labels/text stay inside the cover's safe bounds, and detail scrollWidth fits its clientWidth. Confirm these checks visually; geometry or screenshots alone can miss text clipping. Preserve the cream/red/mustard/green Matchbox design and original Instagram previews.

## Finish

Fix layout issues within the requested scope, rebuild, and inspect fresh renders. For frontend source changes, run `npm run build` and `npm run test:sites` in the app workspace. For backend changes, install `backend/requirements-dev.txt` in its virtual environment and run `python -m pytest tests/backend`. A data-only import does not require rebuilding unchanged code. Preserve personal edits and data during updates. Report the four checked surfaces, actual widths, fixes and remaining visual gaps. Do not claim universal browser support or full accessibility compliance from this check.
