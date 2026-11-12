# Private Cloudflare dashboard

The cloud deployment is an always-available disposable mirror. The local SQLite library remains canonical and can rebuild it. Never upload source videos, extracted frames/audio, raw captions, OCR, transcripts, embeddings, prompts or source paths.

## Create resources

From `assets/dashboard`, install the exact lockfile and authenticate the pinned Wrangler version to the user’s Cloudflare account, then create the resources:

```sh
npm ci
npx wrangler d1 create savedagain
npx wrangler r2 bucket create savedagain-previews
```

Generate the ignored user-specific configuration from committed `wrangler.example.toml`. The UUID must be the D1 ID returned above; no account IDs or secrets are written:

```sh
python "SKILL/scripts/savedagain.py" --workspace "MY WORKSPACE" cloud-template \
  --database-id 12345678-1234-5678-1234-567812345678
```

When working directly from this source checkout, add `--output "skills/saved-again/assets/dashboard/wrangler.toml"`. Review the generated file before using `--force` to replace one. Apply the schema and build:

```sh
npx wrangler d1 migrations apply savedagain --remote
npm ci
npm run build
npm run cloud:dry-run
```

Create four Worker secrets; do not commit their values:

```sh
npx wrangler secret put ACCESS_TEAM_DOMAIN
npx wrangler secret put ACCESS_AUD
npx wrangler secret put ALLOWED_EMAIL
npx wrangler secret put SYNC_SECRET
```

Deploy with `npx wrangler deploy`. The configuration disables `workers.dev`; attach a custom domain in Cloudflare and leave the R2 bucket private. Never commit generated `wrangler.toml`, `.wrangler/`, credentials or Cloudflare resource identifiers.

## Cloudflare Access

Create a self-hosted Access application for the exact custom hostname. Add an Allow policy for the single user email using One-time PIN. Add a separate Service Auth policy and service token for the Mac sync client. Use the application audience tag as `ACCESS_AUD`. Keep any bypass policy off the hostname.

The Worker verifies the Access JWT signature, audience, expiration and allowed email for human requests. Sync routes additionally require `SYNC_SECRET`; the service token is still enforced by Access before the Worker runs.

## Connect the Mac

Store credentials in the private library with:

```sh
python skills/saved-again/scripts/savedagain.py configure-cloud \
  --url https://saved.example.com \
  --access-client-id SERVICE_TOKEN_CLIENT_ID
```

The command prompts without echo for the Access client secret and sync secret. Restart SavedAgain so its private server environment loads the configuration, then run `savedagain.py sync`. While the Mac service is running it scans the inbox every minute and synchronizes at most every 15 minutes.

Sync pulls cloud mutations first, applies them locally, then pushes the privacy-filtered projection and metadata-stripped WebP previews (maximum 640 px, quality 75). UUID mutation IDs, cursors, revision checks and projection hashes make retries idempotent. Cloud conflicts remain visible and are never resolved by blindly overwriting the remote edit.

## Initial rollout

1. Create a local backup.
2. Deploy an empty D1/R2 environment behind Access.
3. Run one sync and compare cloud/local item and category counts.
4. Inspect several thumbnails and edits in both directions.
5. Keep bulk reclassification in preview mode until the labelled evaluation gate passes.

If the mirror is lost or corrupted, recreate D1/R2 and sync again from the local library. Do not treat D1 or R2 as the only copy of private state.
