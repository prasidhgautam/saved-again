# Public asset provenance

Every screenshot, demo record and illustration committed to this repository is synthetic. No image is an Instagram preview, no record came from a personal Saved library, and no screenshot contains a real Instagram account, caption or login state.

## Screenshots

The screenshots were rendered from `docs/demo.json`, whose invented account is `@synthetic_demo`, using the bundled project artwork. The visible “Synthetic demo” label is intentional. SHA-256 values make the reviewed public set auditable:

| File | SHA-256 |
| --- | --- |
| `docs/demo-laptop.jpg` | `0ec98fe13b044dab5aba037db5cf5dc5c19d1ecf12888e926c48c0ebb898c0d2` |
| `docs/demo-phone.jpg` | `fe87b5afb67d92a24780de12a0332b4e2d162456cb72e559209ed0d51ef89c73` |
| `docs/cover-spacing-check.jpg` | `6cbf620ba69637786496e61185463579211b3c3ca77bd7b4c7788817970ab440` |
| `docs/visual-audit/library-desktop.jpg` | `49116dfef7c3bfeee25d9b6f033633ca3caffc4a900c18d0bfe61fafed4584df` |
| `docs/visual-audit/collection-phone.jpg` | `83cad56b55282db1655b4d11b7b2b5df09d662bba49bedfeea4bd86118bbbb5c` |
| `docs/visual-audit/detail-phone.jpg` | `7561a67183e148689a966c54dff60a729199367d1af29a4dba3bafa4ff111eda` |
| `docs/visual-audit/page-end-phone.jpg` | `eee49e36822b86321882a81dadbc7f5c081a3df039aa02a86b0cdcabece74d75` |
| `docs/visual-audit/search-phone.jpg` | `1372ded3c1fca996c8e48e2e5f3d3bb6f504ec4d1c4846e3c7c34b155031c7be` |
| `docs/visual-audit/settings-phone.jpg` | `b2b1b5c23e1bb1c829935afa90cc564e7b5c54aafe63a7ab8cc6ef0e3d4d88e9` |

## Artwork

The WebP matchbox illustrations under `skills/saved-again/assets/dashboard/public/art/` are original project assets created for SavedAgain. They depict generic categories and contain no third-party posts, logos, people or account data. The release privacy audit compares packaged image hashes with the maintainer’s private thumbnail cache when that cache is available.

If any future contributor changes a screenshot, fixture or illustration, they must update this document, confirm the content is synthetic, and run both `scripts/audit_history.py` and `scripts/build_release.py` before submitting it.
