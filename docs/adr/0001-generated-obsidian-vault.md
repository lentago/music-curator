# ADR-0001: Productize the methodology into a generated Obsidian vault

**Status:** Accepted (2026-07-08; reconstructed 2026-08-13)

## Context

The project began as a methodology specification — a document (`music-curation-methodology.md`) describing how to triage a personal music collection into a queryable taste profile. The worked example lived under `examples/`; the whole deliverable was a prompt/document, not running software.

As the worked example grew, several pressures emerged:

- The cleaned inventory needed to be queryable across sessions, not just readable — a flat file is fine, but relationships (collaborations, shared personnel, streaming rotation) are graph-shaped data that benefit from visualization.
- Each new data dimension (streaming history, discography research, Spotify follows, per-album credits) added enough surface area that a monolithic script would be difficult to evolve independently across dimensions.
- A database would require setup and can't be inherited by a future LLM session that just opens the repo.

The choice of tooling was also constrained: stdlib-only Python, no external dependencies beyond CI-installed packages, so any machine (or agent) with Python 3 can run the pipeline without a `pip install` step.

## Decision

Convert the methodology from a spec into a Python toolchain that renders `data/music-inventory.json` into a generated Obsidian vault. Key sub-decisions within this:

- **Sidecar architecture over a monolith.** Each data dimension is a separate merge tool and output file (`streaming_merge.py` → `data/streaming-summary.json`, `harvest_merge.py` → `data/follows.json`, etc.), all keyed to the roster through the shared `alnum()` dedup function in `curator_lib.py`. Dimensions can be added, re-run, or replaced independently.
- **Git as the audit log.** The inventory and all sidecar files are committed JSON. Every change is diffable, reviewable, and revertible without any database tooling.
- **Generated artifacts are drift-enforced in CI.** `integrity.yml` (PR [#65](https://github.com/lentago/music-curator/pull/65), 2026-07-25) runs `obsidian_driver.py` unconditionally on every PR and asserts `vault/` exactly matches the output. The `vault/.generated-by-music-curator` marker guards the directory against confusion with hand-authored content. A single artist recategorization changes seven files in the vault; the honor-system alternative would drift silently.
- **The methodology is preserved as the conceptual core.** Issue [#63](https://github.com/lentago/music-curator/issues/63) / PR [#64](https://github.com/lentago/music-curator/pull/64) (2026-07-25) formally recognized the pivot from "the whole deliverable is a prompt-spec" to "a toolchain with the methodology as its conceptual foundation."

The vault was first added in PR [#10](https://github.com/lentago/music-curator/pull/10) (2026-07-08) and promoted from `examples/` to a top-level `vault/` in PR [#28](https://github.com/lentago/music-curator/pull/28) (2026-07-09).

## Alternatives

**Pure static export without CI drift enforcement** — The `vault/` could be regenerated manually before each PR and committed as-is. This was the implicit approach before `integrity.yml`. *Rejected:* the drift risk was real and not hypothetical — PR [#65](https://github.com/lentago/music-curator/pull/65) proved it in three test scenarios before landing. An honor-system convention is not an enforcement mechanism.

**A relational database + web app** *(retrospective — not considered at the time):* Would offer richer ad-hoc queries and potentially a nicer UI. *Assessment: worse for the intended use case.* The inventory's primary consumer is an LLM session, not a browser. A database requires running infrastructure and credentials; the committed JSON opens in any text editor or agent context. The Obsidian vault is self-hosted and requires no server. Greppability and diffability are first-class requirements here.

**A single monolithic driver script** *(retrospective — not considered at the time):* One script that ingests all sources and renders the vault. *Assessment: lateral at small scale, but the sidecar pattern has already paid for itself.* The streaming, follows, discography, and credits dimensions were added at different times and each required iteration. A monolith would have coupled those iteration cycles together. The sidecar approach also means a credits re-run doesn't touch streaming data and a follows fold doesn't require re-ingesting the GDPR export.

## Consequences

- Every merged PR guarantees `vault/` exactly reflects the data that generated it — no post-merge reconciliation job needed.
- New data dimensions slot in as new sidecar merge tools without touching the driver or CI pipeline.
- The `alnum()` function in `curator_lib.py` is the universal join key. Any change to that normalization function requires re-running all merge layers and regenerating the vault.
- The methodology document remains the session-inheritable guide for running a triage on a new collection; the toolchain is what keeps that triage's output alive over time.
