# Contributing

SavedAgain welcomes thoughtful fixes and personal-use improvements. It is free for personal, noncommercial use under its custom source-available license; it is not OSI open source. By contributing, you agree that your contribution is distributed under that same license.

Before opening a pull request:

1. Use synthetic fixtures only. Never submit a real caption, account identifier, thumbnail, screenshot, source reel, transcript, database, key or token.
2. Keep Instagram access read-only and browser-mediated. Do not add cookie extraction, private APIs, automated downloads or access-control bypasses.
3. Keep model weights and runtime data out of Git. Adapters must work transparently when an optional model is absent and may never silently download one.
4. Run `python -m pytest tests -q`, backend tests, the dashboard build/Worker tests, `python scripts/audit_history.py` and `python scripts/build_release.py`.
5. Update documentation and `docs/ASSET_PROVENANCE.md` when behavior or public media changes.

Sign every commit with a Developer Certificate of Origin line:

```text
Signed-off-by: Your Name <your-email@example.com>
```

This certifies that you have the right to submit the work under the repository license. Follow the Code of Conduct and use the private reporting process in `SECURITY.md` for vulnerabilities.

SavedAgain is not affiliated with, endorsed by or sponsored by Instagram or Meta. Contributors and users are responsible for platform terms, privacy and content rights.
