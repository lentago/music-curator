# ADR-0003: Tiered auto-merge gated on change class

**Status:** Accepted (2026-07-23; reconstructed 2026-08-13)

## Context

Automating follow ingestion (PR [#60](https://github.com/lentago/music-curator/pull/60), 2026-07-23) created a spectrum of possible inventory mutations within a single automated pipeline. Not all of them carry the same risk:

- A follow of an artist not yet in the inventory → an untagged reservoir entry. Additive, reversible, non-judgmental. The follow is already the user's own signal.
- A follow of an artist already in the inventory → provenance stamp only. No data change.
- A follow of an artist marked `discard: true` → a conflict with a prior triage decision. Auto-applying this would silently reintroduce an artist the curator explicitly decided to exclude.
- An unfollow → may signal a deliberate de-emphasis, or may be accidental. Requires human interpretation.

Applying a single merge policy across all of these would mean either holding trivially safe changes for human review (slow, defeats the purpose of the automation) or auto-applying conflicts without review (silently overrides standing taste decisions that downstream analysis depends on).

A second structural constraint shaped the decision: at the time (2026-07-23), `main`'s branch protection ruleset had **no required status checks** — the gap tracked in issue [#9](https://github.com/lentago/music-curator/issues/9) (filed 2026-07-07, before follow ingestion existed: the then-current path-filtered `validate` workflow would have deadlocked every non-data PR had it been made required). The tiered approach was therefore, at decision time, also the mechanism by which unsafe PRs were held: no CI gate would have blocked them independently.

## Decision

Two tiers, strict separation — **mechanical sweeps auto-merge; changes that require taste judgment hold for a human:**

- **Auto-merge:** A follow of a new artist (reservoir seed) or a follow of an owned artist (provenance stamp). Both are additive and reversible; neither overrides a prior decision.
- **Human-gated:** A follow of a discarded artist; any unfollow. `follow-fold.yml` posts an explanatory bot comment on the PR and withholds the merge call.

Implementation details:
- The n8n drain workflow opens the PR but does **not** arm auto-merge. `follow-fold.yml` runs `harvest_merge.py` + `validate.py`, regenerates the vault, commits the fold onto the PR branch, and only then evaluates eligibility. The drain is the data landing; the workflow is the gate.
- `harvest_merge.py` emits a `--summary` JSON that `follow-fold.yml` reads to make the merge/hold decision without re-parsing the inventory.
- The fold is idempotent via an event ledger: a re-trigger from the fold's own push commit is a harmless no-op that finds no new events to process.
- The distinction between "mechanical" and "taste judgment" maps directly onto the methodology's Phase 2 / Phase 3 split: mechanical sweeps first, taste decisions second, always.

The no-required-checks gap closed two days later: the unconditional `integrity` check (plus `docs-check / docs-check`) became required on 2026-07-25, when issue [#9](https://github.com/lentago/music-curator/issues/9) was closed via PR [#65](https://github.com/lentago/music-curator/pull/65). The GITHUB_TOKEN sequencing tension documented in the `follow-fold.yml` header and #9 remains the live constraint on the bot-merge path: pushes made with `GITHUB_TOKEN` do not re-trigger workflow runs, so the fold's own push commit needs its required-check runs handled with care rather than assumed.

## Alternatives

**Auto-merge all follow events** *(explicitly rejected):* Would silently reintroduce discarded artists into the active inventory, overriding triage decisions that prior analysis was built on. The harm is qualitative — a discarded artist appearing in the taste graph biases the analysis, and the conflict may not be noticed until a session inherits the corrupted inventory.

**Manual merge for all follow events** *(explicitly rejected):* Reservoir seeds — follows of new artists — don't require human judgment; the follow itself is the curator's signal. Requiring a manual merge for these makes the automation useless for the common case and creates a queue of trivial approvals.

**Review comments without blocking** *(retrospective — not considered at the time):* The bot could post a flag on borderline events while still auto-merging. *Assessment: lateral, but a weaker guarantee.* A held PR requires the human to take action; a comment can be missed or dismissed. For conflicts with prior triage decisions, the stronger signal is the right choice.

**Separate PR tracks per change class** *(retrospective — not considered at the time):* Auto-merge PRs for safe events; separate flagged PRs for conflicts. *Assessment: lateral but more complex.* Follow events are low-volume (follow-at-follow granularity, not hundreds per day), so batching all events into one PR and holding the whole batch when any event is suspect is both simpler and sufficient. The human sees the full context of the batch in one place.

## Consequences

- The merge gate lives in `follow-fold.yml` (Actions), not in the n8n drain workflow. The drain is stateless and dumb; the CI workflow enforces the policy. This split keeps harvesting infrastructure separate from merge policy.
- Adding `integrity` as a required status check on `main` must be coordinated with this workflow. The transition requires either replacing `GITHUB_TOKEN` with a PAT (so the fold's push triggers CI) or accepting that folded PRs wait for a human merge. This constraint is documented in the workflow header comment and issue [#9](https://github.com/lentago/music-curator/issues/9).
- The mechanical / taste-judgment distinction is a transferable pattern: any future automation that writes to the inventory should classify its changes against this same boundary.
