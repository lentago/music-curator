# ADR-0002: Live Spotify harvest on n8n; data lands only via PR; inventory folding is human-in-the-loop

**Status:** Accepted (2026-07-12; reconstructed 2026-08-13)

## Context

The original curation run ended at a dead end: the Spotify Web API's "recently played" endpoint returned too thin a sample to be meaningful. The GDPR Extended Streaming History export (63,471 rows, 2011→2026) became the batch spine (PR [#35](https://github.com/lentago/music-curator/pull/35)), but it is a one-time snapshot — once it ages out, rotation data would freeze.

A live harvest was needed, but the Spotify API surface had narrowed significantly in Nov-2024 and Feb-2026. PR [#32](https://github.com/lentago/music-curator/pull/32) (2026-07-12) documented what remained accessible in 2026: library reads work in Dev Mode for operator apps, but **playlist track contents are blocked** — operator apps receive a 403 on those endpoints (confirmed in PR [#39](https://github.com/lentago/music-curator/pull/39), fixing issue [#34](https://github.com/lentago/music-curator/issues/34)). The harvester had to be designed around what the API actually permits.

Two early design attempts shaped the final architecture:

**The NAS bind-mount approach** — the first implementation wrote daily JSON snapshots to a NAS share, intending to mount it into the n8n LXC and into the workstation. Abandoned after Proxmox's API token permissions block bind-mounts to LXC containers; an attempt to work around this destroyed the container. Documented in `harvest/README.md`.

**Direct-push-to-main** — the monthly consumer's first implementation committed the roll-up directly to `main` from an n8n Code node via the GitHub API. Blocked at activation: `main`'s branch protection ruleset requires pull requests with zero bypass actors. Direct pushes are not permitted (PR [#51](https://github.com/lentago/music-curator/pull/51)).

**Issue [#47](https://github.com/lentago/music-curator/issues/47)** — ten days after the harvester was first deployed, the expected daily snapshots had not arrived. The investigation surfaced a distinction that shaped subsequent design: code being merged into the repo is not evidence that the external system is running correctly. Deployment (the live workflow on the external host) is a separate state from the merge.

## Decision

- **All harvesting runs on n8n** (on LXC 113, outside the repo's CI) — three workflows generated from Python source-of-truth scripts in `harvest/`. Edit the generator; never the emitted JSON.
- **Redis as the durable queue.** Raw daily snapshots accumulate in Redis, not a shared filesystem. The monthly consumer drains the queue once per month and commits a single roll-up. This eliminates the shared-filesystem dependency and earns the queue as a month-long buffer between daily capture and committed data.
- **The PR gate is mandatory.** `main`'s branch protection ruleset forces all writes through PRs. This constraint, imposed by infrastructure, also provides the intended benefit: every data ingestion has an audit trail, a merge timestamp, and a diff. The monthly consumer opens a PR and arms auto-merge; the follow drain opens a PR but does **not** arm auto-merge — `follow-fold.yml` decides eligibility after running the fold.
- **Raw data is never committed.** Daily snapshots and GDPR exports are gitignored. Only committed roll-ups (`data/harvests/YYYY-MM.json`) and derived sidecars (`data/streaming-summary.json`, `data/follows.json`) land in the repo.
- **Folding harvested data into the inventory is always human-in-the-loop.** The monthly roll-up is raw facts; writing to `data/music-inventory.json` requires running `harvest_merge.py` explicitly and opening a deliberate PR. The harvest landing and the inventory update are separate acts, not a single automatic pipeline.

## Alternatives

**NAS file-share as the sink** *(tried and abandoned):* The initial design wrote `spotify-YYYY-MM-DD.json` to a NAS bind-mount. Abandoned because Proxmox API tokens cannot authorize bind-mounts into an LXC, and a workaround attempt destroyed the container. The Redis queue design requires no shared filesystem between the n8n host and the repo. *Assessment: worse — fragile infrastructure dependency; single destructive failure.*

**Direct push to `main` from n8n** *(tried and blocked):* The monthly consumer originally used the GitHub git data API to commit directly to `main`. Blocked by branch protection (ruleset: PR required, zero bypass actors). Even if the ruleset were loosened, the PR trail is the intended audit record. *Assessment: worse — loss of the change record, and blocked by the enforced ruleset.*

**Batch-only (GDPR export, no live harvest)** *(retrospective — not considered at the time):* Rely solely on the GDPR lifetime export for rotation data, with no ongoing live signal. *Assessment: worse for long-term utility.* The GDPR export ages: by 2027 the oldest plays in a 2026 export are 15 years old and the "current rotation" signal has frozen. The live harvest keeps the rotation dimension meaningful over time.

**Fully automated inventory folding** *(retrospective — not considered at the time):* Auto-apply harvested follows directly to the inventory without a human decision step. *Assessment: worse.* The follow event signals what was playing when a follow happened, not a considered curation judgment. A deliberate fold step (running `harvest_merge.py` and reviewing what changes) preserves the human-in-the-loop that the methodology requires for inventory writes.

## Consequences

- The two-runtime architecture (n8n for capture, GitHub Actions for fold) cleanly separates responsibilities: n8n handles scheduled HTTP calls and Redis; Actions runs the Python toolchain and git operations.
- The API constraint — playlist contents blocked for operator apps — is permanently documented in `roadmap/spotify-data-availability.md`, preventing future attempts to harvest that data without first checking the API surface.
- Adding a required status check to `main` (issue [#9](https://github.com/lentago/music-curator/issues/9)) must be sequenced carefully with the follow-fold automation: see ADR-0003 and the header comment in `.github/workflows/follow-fold.yml`.
- Harvester secrets (Spotify client credentials, GitHub PAT) live only on the n8n host and in Bitwarden; the `.spotify` and `.env` patterns are gitignored with a comment explaining the rule.
