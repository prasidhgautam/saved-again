# Local operation

Let SKILL be the absolute installed skill directory. Run commands with a Python 3.11+ executable; `python` below is a placeholder for that executable, not a shell variable. Quote paths with spaces. The manager uses only Python's standard library before setup.

```
python "SKILL/scripts/savedagain.py" setup
python "SKILL/scripts/savedagain.py" doctor
python "SKILL/scripts/savedagain.py" start
python "SKILL/scripts/savedagain.py" status
python "SKILL/scripts/savedagain.py" key
python "SKILL/scripts/savedagain.py" install-analysis
```

Replace SKILL with the actual path. Global `--workspace PATH` and optional `--data PATH` go before the command. Defaults are `~/SavedAgain/app` and `~/SavedAgain/library`. `setup --node PATH` selects a Node executable. Node 24+ and npm must already be available; setup creates an app-local virtual environment, installs pinned Python dependencies and npm lockfile dependencies, and builds the frontend. Setup updates recognized app files without touching library data; it refuses an unrecognized nonempty app directory. Back up before updating an existing app.

`start --port 8765` launches the server in the background on loopback. If occupied it tries the next ten ports and prints the actual URL. It never stops another service. `status` reports this workspace's recorded instance; `stop` stops only the matching instance. A public health response contains only application/version and a per-start instance identifier. Private data requires the local key. Read `library/server.log` when startup fails; never publish it blindly.

`doctor [--json]` checks Python, Node/npm, setup state, writable library storage, FFmpeg/ffprobe, VoiceStudio’s live transcription contract, configured model paths and cloud configuration. Required toolchain failures return a nonzero status. Optional analysis/cloud findings are reported without blocking the core dashboard. `models [--json]` checks configured model paths and pinned SHA-256 values recorded in `models-manifest.json`; it never downloads a model.

```
python "SKILL/scripts/savedagain.py" --workspace "MY WORKSPACE" import "PRIVATE BATCH.json" --browser-capture
python "SKILL/scripts/savedagain.py" --workspace "MY WORKSPACE" backup --output "PRIVATE BACKUP.tar.gz"
python "SKILL/scripts/savedagain.py" restore "PRIVATE BACKUP.tar.gz" --to "EMPTY LIBRARY DIRECTORY"
```

The import command is an agent/operator bridge for actual browser-captured records, not a manual user import fallback. Keep input files outside the source repository. Each batch must have no more than 25 records. Confirm the returned batch ID. The UI's JSON export includes records, personal edits, categories and reminder history; full backups additionally include locally cached previews, checkpoints and the access key. Restore a full backup to an empty directory and select it with `--data` when starting a separate workspace. Never restore over a running library.

`install-analysis` explicitly installs optional analyzer code but never model weights. Put user-owned reel files in the private `library/inbox` with a shortcode in the filename or sidecar, then use `scan-inbox`, or attach a file from the local item panel. Read [private local reel analysis](local-analysis.md) before configuring model paths or VoiceStudio.

Use `configure-cloud --url HTTPS_URL --access-client-id ID` to save Cloudflare sync credentials in a mode-600 private library file, then restart and use `sync`. Read [private Cloudflare dashboard](cloud-dashboard.md) for D1/R2, Access, secrets and first-sync validation.

The skill requires a local runtime accessible from the user's browser. A remote chat sandbox cannot automatically access the user's localhost or Chrome profile. Do not promise otherwise. Windows paths and virtual environment layout are handled by the Python manager; native Windows is supported by design but only claim it tested if actually run there. Browser tool availability is independent of operating system support.

Docker alternative: run `docker compose up --build -d` from `assets/dashboard`. Compose uses a named data volume and loopback port 8765. Get the local key with `docker compose exec savedagain cat /data/.access-key`. The Cloudflare Worker is a filtered mirror, not a replacement for the FastAPI analysis layer. Scheduled notifications are outside this version.

After updating a recognized installation, refresh the running frontend and confirm it serves the newly built assets. Follow [visual checks](visual-checks.md) before calling the updated dashboard verified. Keep screenshots and private audit notes outside installed skill/source; public screenshots must use synthetic data.
