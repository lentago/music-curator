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
| `data/streaming-summary.json` | Streaming-history sidecar (like `credits.json`): per-artist plays/minutes/first/last/per-year aggregates from the GDPR Extended Streaming History export, for inventory-matched artists plus streaming-only artists above a 10-play floor. The raw export (`data/my_spotify_data/`) is gitignored — it carries IP addresses. |
| `streaming_merge.py` | Stdlib-only merge tool (sibling to the driver): reads the GDPR export, writes the sidecar, stamps `rotation` (current / dormant / historical) onto non-discarded inventory artists, and prints the merge findings (stream-only rotation, dormant anchors, discarded-but-streamed). |
| `data/discographies.json` | Seeded full-discography sidecar (like `credits.json`): every known recording for selected anchor artists — owned or not — harvested per artist from a canonical discography page (Wikipedia), with owned-album matches and roster links computed. The driver renders it as a per-artist Discography section (◆ = in collection; roster side-projects wikilinked). Inventory `albums` keep meaning "owned"; this layer is the full-catalog lens around them. |
| `discography_merge.py` | Stdlib-only merge tool (sibling to the driver): merges per-artist harvest JSONs into the discographies sidecar, matches recordings against owned rips (Phase-2 alnum family, disc-suffix/truncation tolerant, including under roster side-projects like Naked City/Masada), and emits the personnel-research worklist for albums not yet in `credits.json`. Reruns replace only the artists being re-harvested. |
| `obsidian_driver.py` | Stdlib-only driver that renders `data/` into the vault (each artist note → one hub wikilink in a two-tier tree: 13 color-coded top-level categories, second-order subcategory hubs beneath). Sibling to `validate.py`. |
| `vault/` | **The wiki.** Generated Obsidian vault — regenerate with the driver, don't hand-edit. Ships a pre-styled `.obsidian/graph.json` plus a switchable preset library in `.obsidian/graph-presets/` (`default` = full taste map, `artist-web` = artist↔artist edges only; pick with the driver's `--graph` flag). Guarded by a `.generated-by-music-curator` marker. |
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
