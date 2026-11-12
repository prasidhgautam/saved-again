# Security policy

## Reporting a vulnerability

Use GitHub’s **Report a vulnerability** button to open a private security advisory for this repository. Do not open a public issue for a suspected vulnerability. If private vulnerability reporting is not yet enabled, wait for the repository owner to enable it rather than publishing exploit details.

Never attach a real SavedAgain database, caption, transcript, thumbnail, reel, access key, Cloudflare token, service-token secret or `.env` file. Reproduce with synthetic data and redact absolute paths and account identifiers from logs. The maintainer will acknowledge a complete report when repository maintenance capacity permits; no guaranteed response or remediation SLA is offered for this personal-use project.

## Supported versions

Only the newest tagged release is supported. Development snapshots and older tags may receive fixes only when the maintainer chooses to backport them.

## Security boundaries

SavedAgain does not extract Instagram cookies, call private Instagram APIs or automatically download reels. Source media and raw analysis artifacts remain local. Cloudflare deployments are user-operated and must be protected by Cloudflare Access; publishing an unprotected dashboard is unsupported.
