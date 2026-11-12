# Release validation

Last updated 2026-11-12. The original implementation baseline contained **51 passing Python tests**. Public-release hardening and expanded VoiceStudio failure coverage add 12 tests, so the current checkout runs **63 Python tests** in total: 47 dashboard/backend tests and 16 manager, release, history-audit and packaging tests. The Worker suite contains **5 passing Node tests**.

SavedAgain is not affiliated with, endorsed by or sponsored by Instagram or Meta. Users are responsible for platform terms, privacy and the rights governing every caption, preview and reel they process.

## Automated checks

- **47 backend tests pass:** existing library/authentication/import/search/persistence coverage plus analyzer ingestion, deterministic classification, multimodal score fusion, permanent manual-category protection, preview-only bulk reclassification, safe cloud projection and D1 migration coverage.
- **16 manager/release tests pass:** portable paths, prerequisites, browser-capture gate, batch acknowledgement, backup safety, generated Cloudflare configuration, offline model checksum validation, environment doctor output, release allowlisting/versioning, private fingerprint rejection and full-history audit detectors.
- **5 Worker tests pass:** static assets, SPA fallback, API/write-route isolation, missing Access rejection, cloud-payload privacy rejection and required deployment artifacts.
- Production Vite build passes. Wrangler 4.160.1 successfully dry-runs `wrangler.example.toml` and reports the expected D1, private R2 and static-asset bindings without deploying.
- The D1 migration executes in an in-memory SQLite database and creates `posts`, `categories`, `mutations`, `sync_clients` and `sync_requests` with the expected starter taxonomy.
- The curated release builder checks its explicit allowlist, required skill/app files, ZIP integrity and checksums. With the private pilot library supplied, it rejects matching account/key/caption/thumbnail fingerprints.

## VoiceStudio transcription contract

Mock-contract tests confirm that SavedAgain calls only:

1. `GET /health`;
2. `GET /openapi.json`; and
3. `POST /v1/audio/transcriptions` with `model=whisper-1` and `response_format=verbose_json`.

They cover a healthy verbose response and segment parsing, a missing route, an unavailable server, connection timeout, malformed OpenAPI JSON, a transcription backend/model 503, malformed transcription JSON and partial-analysis continuation. When transcription fails, the job remains `waiting_for_transcription` while independent media/classification artifacts survive. No test or implementation calls VoiceStudio speech generation, cloning, dubbing, design or model-install endpoints, and there is no whisper.cpp or cloud fallback.

These are mock server/contract tests. A live VoiceStudio backend and a live ASR model were **not** run end-to-end during this validation.

## Analyzer implementation versus successful model execution

“Adapter implemented” means SavedAgain validates configuration, loads only an explicitly configured local model/runtime, exposes missing-stage status and has deterministic/mocked tests around its boundary. It does **not** mean the heavyweight model has successfully executed on every supported machine.

| Analyzer | Adapter implemented | Successfully run end-to-end in this validation |
| --- | --- | --- |
| Sentence Transformers multilingual MiniLM | Yes; local-only path and pinned manifest/checksum | No model weights loaded |
| OpenCLIP ViT-B/32 | Yes; explicit checkpoint path | No model weights loaded |
| PaddleOCR Latin + Devanagari | Yes; explicit detection/recognition directories and script routing | No OCR weights loaded |
| PySceneDetect | Yes; maximum-eight-frame selection with uniform fallback | Adapter unit coverage only; no production reel corpus |
| BERTopic | Yes; explicit Needs Review discovery action | No model run |
| Ollama Qwen3 4B | Yes; opt-in running-server/model check, never pull | No Ollama model run |
| FFmpeg/ffprobe | Yes; validation/audio/frame commands | Media paths are mocked in automated tests; no private reel used |
| Deterministic keyword classifier and fusion thresholds | Yes | Yes, with synthetic fixtures |
| VoiceStudio transcription | Yes, transcription-only contract | Mock contract only; not live ASR |

No hosted AI provider was configured, and no model was silently downloaded. The manifest pins immutable MiniLM/OpenCLIP revisions and hashes plus the Ollama registry digest; Paddle model directories remain explicit operator-provided inputs because their selected exported directory must match the user’s platform/runtime.

## Cloud privacy and synchronization coverage

Tests reject raw captions, transcripts, OCR, embeddings, prompts, source paths, frames/audio/source video and nested analysis payloads from the cloud projection. The migration/schema test covers D1 table creation. Local synchronization tests cover safe projection construction; Worker tests verify unauthenticated API rejection and privacy filtering.

Access JWT verification code is implemented, but a real Cloudflare Access tenant, OTP policy, service token, D1 database, R2 bucket, custom domain and live two-way conflict session were not provisioned in this local run. Wrangler validation is a dry-run, not a production deployment.

## History, secrets and synthetic assets

- Official Gitleaks 8.30.1 was downloaded for macOS ARM64 and its SHA-256 was verified against the official GitHub release digest. It scanned all 3 commits (about 818 kB at the time of the scan) and found no leaks.
- `scripts/audit_history.py` scanned every historical Git blob plus the working tree for forbidden runtime files, private keys/tokens, absolute user paths and private-library caption/account/key/thumbnail fingerprints. It passed with the private pilot library supplied.
- Because neither scanner found a historical secret, no `git filter-repo` rewrite or credential rotation was required.
- Every committed screenshot/demo record is synthetic and uses project artwork, not an Instagram preview. Reviewed hashes and origin are recorded in `ASSET_PROVENANCE.md`.

## Installation and platform coverage

A clean skill-ZIP installation was previously exercised on macOS ARM64 with Python 3.11.18 and an official Node 24 toolchain, including a path containing spaces, fresh key/database, occupied-port fallback, persistence and backup/restore. The current release-hardening run repeated Python 3.11 tests, the production build, 5 Worker tests and a Wrangler 4.160.1 dry-run on the same macOS ARM64 host.

The host had less than 500 MB free during the final npm check, so a new full `npm ci` stopped with `ENOSPC`. The lockfile was regenerated successfully; the production build reused an already-installed dependency tree with the exact committed React 19.2.0, React DOM 19.2.0, Vite 6.4.2 and plugin 5.0.4 versions, and the Cloudflare dry-run used exact Wrangler 4.160.1. The tagged-release workflow performs a clean `npm ci` on GitHub-hosted Ubuntu and publication should wait for that job to pass.

The committed GitHub Actions matrix targets current Ubuntu, macOS and Windows runners with Python 3.11 and Node 24, but those remote jobs have not run until the repository is pushed. Native Windows, native Linux, Docker, Intel macOS, non-x64 Linux, Claude Code and other assistant/browser integrations remain untested locally. PaddlePaddle 3.3.1 publishes relevant Python 3.11 wheels for macOS ARM64, Linux x64 and Windows x64; published wheels are not equivalent to SavedAgain end-to-end validation.

Instagram layout/login/challenge/rate-limit scenarios are instruction reviews and synthetic checkpoint fixtures, not a fresh live scrape. Import still depends on supported logged-in browser tools and localhost access. No claim is made that every assistant, browser tool, Instagram layout or account state works.

## Browser and visual checks

The dashboard was inspected at laptop and phone widths with a separate synthetic 13-record library. No horizontal overflow was observed at 320, 390, 1024 and 1440 px. Custom category navigation, category editing, item filing and notes persistence were exercised. The complete screenshots and measured custom-cover correction are documented in `visual-audit.md`; public media provenance is in `ASSET_PROVENANCE.md`.

Repository-level GitHub settings—dependency graph, Dependabot alerts, secret scanning, push protection, private vulnerability reporting and branch protection—cannot be enabled before a remote repository exists. The owner steps are recorded in `GITHUB_RELEASE_CHECKLIST.md`; workflows and configuration files are already committed for CI, CodeQL, Dependabot and curated tagged releases.
