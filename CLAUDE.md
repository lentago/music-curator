# CLAUDE.md — music-curator

> Read [README.md](README.md) for the full project pitch, the problem
> framing, and the five-phase workflow. This file is operational notes for
> Claude: what the artifacts are, how the methodology is meant to be used,
> and the conventions to respect. Fleet-wide rules (PR workflow,
> attribution) live in `~/repos/CLAUDE.md` and are not restated here.

## Persona — introduce yourself

When Claude initializes in this directory, open the first response with a
brief self-introduction as **Music-Curator Claude** — taste-profiling
methodologist (collection dump → cleaned inventory → queryable taste
profile, via iterative discard triage with the user in the loop). One
sentence is plenty; don't make a meal of it.

## What this repo is

Two deliverables share the repo. The original is a **spec** —
`music-curation-methodology.md` — that converts a low-effort representation
of a person's music collection (directory tree, Spotify export, prose) into
a clean, queryable taste profile a model can mine across conversations
(same genre as `reference-checker`). Grown on top of it is the **wiki** —
`vault/`, an Obsidian graph rendered by `obsidian_driver.py` from the
living data source in `data/`. The `examples/` hold the original worked
run's static artifacts (distilled profile + raw input tree).

## Artifacts

| File | Role |
|---|---|
| `music-curation-methodology.md` | **The spec.** The reusable skill: five phases, discard heuristics, canon-tolerance / lesser-album / fragmentation rules, pacing, anti-patterns, exit criteria. |
| `data/music-inventory.json` | The cleaned, tagged data source the wiki and profile are built from. Schema is documented in the methodology's "Outputs produced" section. |
| `data/credits.json` | Per-album personnel research layer (musicians/producers/guests, web-verified with `source`+`confidence`), consolidated from the bullpen fan-out. The driver derives ~400 roster-only "session tie" artist↔artist edges from it. Regenerate credits separately from the inventory. |
| `obsidian_driver.py` | Stdlib-only driver that renders `data/` into the vault (each artist note → one hub wikilink in a two-tier tree: 13 color-coded top-level categories, second-order subcategory hubs beneath). Sibling to `validate.py`. |
| `vault/` | **The wiki.** Generated Obsidian vault — regenerate with the driver, don't hand-edit. Ships a pre-styled `.obsidian/graph.json`. Guarded by a `.generated-by-music-curator` marker. |
| `examples/chris-music-profile.md` | The original worked run's distilled taste profile (anchors, signal lanes, exploration threads). The analog of reference-checker's `reports/`. |
| `examples/music-tree` | The raw library tree fed in, kept as an input fixture. |
| `roadmap/roadmap.md` | Planned capabilities, grounded in threads from the original run (periodic Spotify harvest, streaming + collection merge, skill packaging). |

## Conventions to respect

- **"Smoke" / "kill" = mark as discarded from analysis, NOT delete files.**
  This methodology produces a data source for analysis; it never touches the
  user's actual music library. Say so if a user conflates the two.
- **Don't guess on tagging.** Leaving an artist in the untagged reservoir is
  correct; mistagging pollutes later analysis. Same for discard pitches —
  they're predictions, framed honestly, not pronouncements.
- **The data source is meant to grow.** When a user confirms a new artist,
  add it with `tagged: true` and a `category` from the 13 top-level genres
  (plus a `subcategory` where one fits — one category per artist, subcategory
  optional; the current vocabulary is enumerated by any category hub note in
  `vault/Categories/`). Top-level categories are canonical genres only —
  grayish or scene-flavored buckets belong at the subcategory tier, and
  record labels / city scenes are not categories at all. Build the inventory
  as something a future session would want to inherit.
- **The example is personal data, published deliberately.** Chris chose to
  publish his real profile/inventory/tree as a demonstration. It contains
  taste data only — no credentials or PII. Keep it that way: if a future run
  would add anything sensitive (account exports with tokens, etc.), scrub it
  before it lands.

## Using the methodology on a new collection

Point a fresh session at `music-curation-methodology.md`, hand it the user's
collection dump, and run the five phases. The worked artifacts here
(`examples/`, `data/`, `vault/`) show what a finished run looks like end
to end. Cross-reference a new run's data source
before reaching for external recommendations — listeners usually already own
foundational material in a thread they want to explore.
