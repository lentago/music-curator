# Music Curator

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

- **[`music-curation-methodology.md`](music-curation-methodology.md)** — the reusable skill. The product of this repo: phases, discard heuristics, pacing, anti-patterns, and exit criteria, written to be inherited by a future session with no memory of the original run.
- **[`examples/`](examples/)** — a real worked instance from a single ~25,000-file / 700-artist collection, run across **13 triage rounds** (16.8% discard rate):
  - [`chris-music-profile.md`](examples/chris-music-profile.md) — the distilled taste profile: foundational anchors, confirmed signal lanes, threads queued for exploration.
  - [`music-inventory.json`](examples/music-inventory.json) — the cleaned, tagged data source the profile is built from.
  - [`music-tree`](examples/music-tree) — the raw library tree that was fed in, kept as an input fixture so the before/after is visible.
- **[`roadmap/roadmap.md`](roadmap/roadmap.md)** — planned capabilities (periodic Spotify harvest, streaming + collection merge, packaging as a Claude skill), grounded in threads that surfaced during the original run.

## Origin

Distilled from a single long Claude conversation that started as "can Claude connect to Spotify?", discovered that recent-play history was too thin a sample to be meaningful, and pivoted into a full triage of an owned MP3 collection. The methodology is the generalizable part; the `examples/` are one person's actual run, published as a demonstration rather than scrubbed away.

---

*Part of the [Lentago Labs](https://github.com/lentago) portfolio of prompt-engineered systems — a sibling to [reference-checker](https://github.com/lentago/reference-checker).*
