# GitHub publication checklist

The repository files automate tests, history/privacy audits, CodeQL and tagged releases. Repository-level security switches cannot be enabled before a GitHub remote exists, so the owner must complete this checklist immediately after creating the public repository.

## Before the first push

- Run `python scripts/audit_history.py --private-library "PRIVATE_LIBRARY_PATH"`.
- Run Gitleaks 8.30.1 across all Git history and verify the downloaded binary/archive checksum against its official release.
- Run `python scripts/build_release.py --private-library "PRIVATE_LIBRARY_PATH"`.
- Confirm `docs/ASSET_PROVENANCE.md` hashes match and every demo record/screenshot is synthetic.
- If any real secret ever appears, rotate it first, remove it from every ref with `git filter-repo`, rerun both scanners, and force-push only after every collaborator is told to reclone.

## Repository settings

In **Settings → Security / Code security and analysis**, enable:

- Dependency graph.
- Dependabot alerts and security updates.
- Secret scanning and push protection when available for the repository/account.
- Private vulnerability reporting.
- Code scanning; the committed CodeQL workflow covers Python and JavaScript/TypeScript.

In **Settings → Actions**, allow only required actions and keep the default workflow token read-only. Protect `main`: require pull requests, required checks, resolved conversations and no force pushes/deletions. Require signed commits/tags if that matches the owner’s release process.

## Release process

1. Update `CHANGELOG.md` and version constants/package metadata.
2. Run the complete local validation suite and privacy audits.
3. Create a signed annotated tag such as `v1.1.0` on the reviewed commit and push the tag.
4. The tagged-release workflow reruns tests/audits, builds the allowlisted source and skill ZIPs, generates `SHA256SUMS`, and creates release notes.
5. Download the published artifacts once, verify checksums, inspect ZIP contents, and smoke-test the skill ZIP in a clean directory.

GitHub’s automatically generated source archives are repository snapshots. They do not replace SavedAgain’s curated, allowlisted skill ZIP.
