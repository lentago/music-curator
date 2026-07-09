# Music Curator

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/lentago/music-curator)

A prompt-engineered methodology for turning a low-effort dump of someone's music collection — a directory tree, a Spotify export, a plain list of artists — into a clean, queryable **taste profile** that a language model can mine for personalized discovery across conversations.

**Authorship:** The methodology, documentation, and worked example in this repo are co-written with [Claude](https://claude.ai) (Anthropic). I direct the work and review the output; Claude writes the prompts and prose. I'm an infrastructure operator, not a software engineer — please don't read this repo as a portfolio of coding ability.

## The Problem

Streaming services already build algorithmic taste profiles, but they only see your *current* rotation and infer the rest. The richer signal — the one built up over decades — is usually trapped in an owned or curated collection that's too messy to use directly:

- **Duplicates from formatting drift** — `16_horsepower` and `16 Horsepower`, `Wovenhand` and `Woven Hand`, the same album under two artist spellings.
- **Torrent and download cruft** — tracker-only folders, date-stamped `Unknown Album` noise, lowercase-underscore naming, loose `.mp3` files filed at artist depth.
- **Compilation fragmentation** — one comp ripped with each track filed under its own artist folder, masquerading as a dozen artists nobody actually collects.
- **Other people's files mixed in** — a partner's pop, a friend's bachelor-party lounge comps, hype-cycle singletons grabbed once and never revisited.

Feed that raw mess to a recommender and you get noise-driven guesses. This methodology cleans it into a structured data source first, then uses it to ground discovery in *the listener's actual taste* rather than algorithmic inference.

## How It Works

A five-phase workflow, run conversationally with the listener in the loop:

| Phase | What happens |
|---|---|
| **1. Intake & parse** | Convert whatever the user can produce (tree dump, Spotify export, prose) into a structured artist → album hierarchy. |
| **2. Mechanical sweep** | Before any taste judgment: merge duplicate folders, drop tracker cruft, detect compilation fragmentation, delete empty/ringtone/podcast noise. |
| **3. Confident tagging** | Tag only the artists whose scene / era / genre you genuinely know. Leave the rest in an untagged reservoir — a 15%-tagged-but-correct inventory beats a 100%-tagged-with-errors one. |
| **4. Iterative discard triage** | Run rounds of 8–12 discard candidates *with the user*, grouped into thematic clumps, each ending in an honest confidence ladder (*money on the table / strong / pushable*). The user adjudicates; their **keeps** teach more than their kills. |
| **5. Pivot to exploration** | Once the discard rate plateaus (~15–20%), switch from triage to discovery: adjacent-artist suggestions, anchor-artist catch-up, reservoir mining, cross-referencing new finds against what they already own. |

The heuristics that drive Phase 4 — high-confidence discard tells, a **canon-tolerance** exception (sole greatest-hits comps from foundational figures stay), the **lesser-album rule**, genre-orthogonality and compilation-fragmentation tests — are the substance of the method. They live in [`music-curation-methodology.md`](music-curation-methodology.md).

## What's Here

- **[`music-curation-methodology.md`](music-curation-methodology.md)** — the reusable skill: phases, discard heuristics, pacing, anti-patterns, and exit criteria, written to be inherited by a future session with no memory of the original run.
- **[`data/`](data/)** — the living data source the wiki is rendered from:
  - [`music-inventory.json`](data/music-inventory.json) — the cleaned, tagged inventory (schema-validated in CI).
  - [`credits.json`](data/credits.json) — the per-album personnel layer that drives the session-tie edges.
- **[`vault/`](vault/)** — the wiki itself: a generated Obsidian vault whose **graph view** turns the taste profile into a visual artist map. See below.
- **[`obsidian_driver.py`](obsidian_driver.py)** — the driver that renders `data/` into `vault/`.
- **[`examples/`](examples/)** — the original worked run, from a single ~25,000-file / 700-artist collection across **13 triage rounds** (16.8% discard rate):
  - [`chris-music-profile.md`](examples/chris-music-profile.md) — the distilled taste profile: foundational anchors, confirmed signal lanes, threads queued for exploration.
  - [`music-tree`](examples/music-tree) — the raw library tree that was fed in, kept as an input fixture so the before/after is visible.
- **[`roadmap/roadmap.md`](roadmap/roadmap.md)** — planned capabilities (periodic Spotify harvest, streaming + collection merge, packaging as a Claude skill), grounded in threads that surfaced during the original run.

## Obsidian graph vault

The cleaned inventory is already a graph: each tagged artist carries a
**two-tier category** — one of 13 top-level genres aligned with the canonical
music taxonomies (AllMusic, Discogs, Wikipedia's genre families), plus an
optional second-order `subcategory` where a genre deserves finer structure
(`Hip-Hop › Underground`, `Country & Americana › Gothic Americana`). The
grayish scene buckets live only at the second order; record-label and
city-scene pseudo-genres were eliminated outright. `obsidian_driver.py`
renders those relationships into a self-contained
[Obsidian](https://obsidian.md) vault where each artist note wikilinks to its
subcategory hub (which links up to its category) or straight to its category —
those links are the graph edges. Open the folder in Obsidian and the graph
resolves into 13 color-coded genre trees out of the box, no plugins. It opens **filtered to the
taste structure** — the meta/navigation notes are hidden — so you see the music,
not the scaffolding. No artist is pre-weighted as an "anchor"; the important
nodes surface from the connectivity itself, since Obsidian sizes nodes by degree.

```bash
python obsidian_driver.py            # → vault/
```

What comes out (from the collection's 554 active artists):

- **Artist notes** each link into exactly one branch of the category tree —
  subcategory hub where one exists, top-level hub otherwise — and every node in
  a branch shares its top-level color, so the 13 genre clusters (with their
  subcategory sub-clusters) read at a glance.
- **Collaboration edges** link combo acts straight to the members they share —
  `El-P & Cannibal Ox` → El-P + Cannibal Ox, `Mos Def & Talib Kweli` → both —
  parsed from the artist keys, drawn only to members that are themselves in the
  collection. So the graph also shows the social graph, not just category
  membership.
- **Session ties** wire artists together through **shared personnel** — a
  musician who played on both artists' albums (Marc Ribot across Tom Waits *and*
  John Zorn; Jerry Douglas' dobro across the whole bluegrass/newgrass web). These
  ~400 edges come from [`data/credits.json`](data/credits.json), a
  per-album personnel layer researched and cross-referenced against the roster;
  only roster artists become ties. They cross the category clusters — the
  collection's hidden wiring.
- **Untagged reservoir** artists (no category yet) hang off a single `Reservoir`
  hub, hidden from the default view so the taste map stays legible.

The vault ships pre-built at [`vault/`](vault/) so the graph is browsable
without running anything. It is fully generated —
regenerate rather than hand-editing. Discarded artists are dropped by default;
`--include-discarded` keeps them (tagged `#discarded`).

## Origin

Distilled from a single long Claude conversation that started as "can Claude connect to Spotify?", discovered that recent-play history was too thin a sample to be meaningful, and pivoted into a full triage of an owned MP3 collection. The methodology is the generalizable part; the `examples/` are one person's actual run, published as a demonstration rather than scrubbed away.

---

*Part of the [Lentago Labs](https://github.com/lentago) portfolio of prompt-engineered systems — a sibling to [reference-checker](https://github.com/lentago/reference-checker).*
