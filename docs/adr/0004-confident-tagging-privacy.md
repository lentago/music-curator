# ADR-0004: Confident tagging over completeness; the privacy line

**Status:** Accepted (2026-07-08; reconstructed 2026-08-13)

## Context

**Tagging.** The five-phase methodology's Phase 3 confronted a core tension: a rich taste profile requires tagged, categorized artists, but tagging under uncertainty introduces errors that propagate silently into every downstream analysis. With a 556-artist collection, completing every tag quickly would require making confident-sounding judgments about artists where the honest answer is "I haven't listened enough to know." A wrongly categorized artist biases the taste graph; an untagged artist simply doesn't appear yet.

**Privacy.** Introducing the streaming merge layer (PR [#35](https://github.com/lentago/music-curator/pull/35), 2026-07-13) brought in a data source with an unexpected property: the Spotify GDPR Extended Streaming History export records a per-play IP address for every stream event. In a public repo, committing this export would permanently expose years of network location history.

The worked example (the original triage run in `examples/`) is a separate consideration: music taste data that the author chose to publish as a demonstration fixture. This is deliberate and recorded, not accidental.

## Decision

**On tagging:**
- Phase 3 rule: "A 15%-tagged-but-correct inventory beats a 100%-tagged-with-errors one." Leaving an artist in the untagged reservoir is the correct state when the right category is uncertain. Mistagging pollutes analysis; a gap is honest.
- Discard pitches are predictions, framed honestly, not pronouncements. The methodology explicitly instructs: "Don't guess on tagging."
- The untagged reservoir is a first-class state, not a to-do list. Future sessions should inherit it and treat it as a holding area for artists that have not yet been triaged with sufficient confidence.

**On privacy:**
- The raw GDPR streaming export (`data/my_spotify_data/`) is gitignored unconditionally. The rule is enforced structurally: the pattern is in `.gitignore` with an explanatory comment, documented in the main README, described in CLAUDE.md, and noted in `streaming_merge.py`'s documentation. Multiple layers because a single accidental commit to a public repo is permanent.
- The committed artifact is the derived sidecar only: `data/streaming-summary.json` contains aggregated per-artist play counts, minutes, rotation class, and per-year histograms — no raw play events, no IP addresses.
- The worked example in `examples/` (`chris-music-profile.md`, `music-tree`) is a deliberate, recorded exception: personal taste data published with the author's knowledge as a demonstration. It contains no credentials or PII beyond music preferences.

## Alternatives

**Tag everything; tolerate errors; clean up in later passes** *(explicitly rejected in the methodology):* Errors in tagging are qualitatively different from gaps. An untagged artist is a known unknown; a mistagged artist looks authoritative until manually audited and is easy to miss. The methodology's Phase 4 (discard triage) depends on category signals being trustworthy; errors there compound into wrong discard decisions. *Assessment: worse — error propagation, not just noise.*

**Store the GDPR export in a private submodule** *(retrospective — not considered at the time):* A private submodule or private sibling repo could hold the raw export for re-runs without exposing it in the public repo. *Assessment: lateral.* The raw export is a one-time input: `streaming_merge.py` is idempotent against the same export, and a new export can be downloaded from Spotify if needed. The added credential management for a private submodule outweighs the benefit. The gitignore approach is simpler and structurally enforced.

**Make the entire repo private** *(retrospective — not considered at the time):* A private repo eliminates all public-data concerns at the cost of the repo's primary purpose. *Assessment: worse for the project's goals.* The repo exists in part as a learning-lab exhibit: the ops patterns (tiered auto-merge, drift enforcement, unconditional required checks, generated-artifact CI) are only demonstrable in a public repo where the CI runs and diff history are visible. A private repo would preserve the data layers but lose the exhibit.

## Consequences

- The untagged reservoir is load-bearing: it represents real uncertainty, not incomplete work. Future automation or session-inherited triage should not attempt to tag reservoir entries wholesale without genuine confidence.
- The "derived data committed, raw source gitignored" pattern generalizes to any future data source that might carry PII. A new source (e.g., Last.fm scrobble export) would follow the same rule: write the merge tool, commit the derived sidecar, gitignore the raw input.
- The worked-example taste data is public and should remain taste data only. CLAUDE.md records this: "if a future run would add anything sensitive (account exports with tokens, etc.), scrub it before it lands."
