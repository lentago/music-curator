# Roadmap

Planned capabilities for the music-curation methodology. Each entry includes
what it adds, an implementation sketch, a priority, and dependencies. Items
are grounded in threads that surfaced during the original triage run — not
speculative feature-padding.

**Status:** The methodology (`music-curation-methodology.md`) and the wiki
it produced (`vault/`, rendered from `data/`) are the core deliverables;
`examples/` keeps the original run's static artifacts. The items below are
planned extensions.

**Implemented:**
- Engineering spine (issue #4) — `schema/music-inventory.schema.json`
  (JSON Schema Draft 7 for structural validation) and `validate.py` (cross-field
  integrity checker + near-duplicate artist-key detection). CI runs the validator on
  every change to the inventory, schema, or validator itself (`.github/workflows/validate.yml`).
- Obsidian graph vault — `obsidian_driver.py` renders the inventory into an
  Obsidian vault (`vault/`) whose graph view clusters artists into a two-tier
  category tree — 13 color-coded top-level genres with second-order
  subcategory hubs beneath (one category per artist, subcategory optional) —
  letting the important nodes surface from the connectivity rather than a
  prior (see below).
- Personnel / session-tie edges — `data/credits.json` is a per-album
  personnel layer (musicians, producers, guests) researched across the whole
  collection and cross-referenced against the roster; the driver draws ~400
  roster-only artist↔artist "session tie" edges from it (a player who appears on
  both artists' albums), surfacing connectors like Jerry Douglas and Marc Ribot
  that cross the category clusters.

---

## Data-source lifecycle

### Periodic Spotify Harvest (n8n Web API → Redis queue)

**Priority:** High — **in progress** (producer built; deploy + consumer remain).

**What it adds:** Turns the one-time snapshot into a *living* data source. The
original run found `recently-played` too thin; this is the live-snapshot layer
that complements the GDPR Extended Streaming History export (the lifetime batch
spine — see [`spotify-data-availability.md`](spotify-data-availability.md)).

**Architecture (message-queue — no shared filesystem):**

```
Daily    n8n: Schedule → Code (fetch snapshot) → Redis Push → list "spotify:harvests"
Monthly  n8n: Schedule → drain list → aggregate per-artist → GitHub commit data/harvests/YYYY-MM.json
```

Runs on the n8n box (LXC 113); Redis is a container in the same compose. The
earlier NAS-file design was abandoned: Proxmox forbids bind-mounts via the
Terraform pipeline's API token, and the attempt destroyed the CT (see memory
`n8n-ct-recovery-model`). The queue doubles as the month-long buffer, so the
repo gets one roll-up commit per month, not one per day.

**Built (PR #32):** the data-availability spec, the loopback-PKCE bootstrap
(`harvest/spotify_auth_bootstrap.py`), and the daily **producer** workflow
(`harvest/gen_workflow.py` → `spotify-harvest.workflow.json`).

**Remaining (concrete next steps):**
1. Deploy Redis to `/opt/n8n/docker-compose.yml` + wire the Spotify
   `/opt/n8n/.env` — in-guest, low-risk (snippet in `harvest/README.md`).
2. Add two n8n credentials: a Redis connection and a fine-grained GitHub PAT
   (`contents:write` on `music-curator`).
3. Import + test the producer; confirm a snapshot lands on the Redis list.
4. Build the monthly **consumer** (`harvest/rollup.workflow.json`): Redis Llen →
   pop N → aggregate (play/appearance counts, first/last seen, top-range hits)
   → GitHub commit.
5. Correct the spec's playlist row — playlist *contents* (`/playlists/{id}/tracks`)
   return 403 for a Dev-Mode operator app; only `/me/playlists` metadata works.

**Merge rule (unchanged):** harvest signals update `tagged`/`anchor`/`rotation`
and append new artists; they never silently resurrect discarded entries; each
harvest is date-stamped so rotation drift stays visible.

**Dependencies:** the n8n box (LXC 113); a stored refresh token kept out of the
repo. See memory `spotify-harvest-status`.

---

### Streaming + Collection Merge

**Priority:** High — **shipped (batch spine), 2026-07-12**

**What it adds:** The example profile explicitly notes the gap — the MP3
collection is a *historical* taste artifact (deepest investment ~2000–2010),
while Spotify shows the *current* rotation, and they don't fully overlap. A
first-class merge keeps both lenses in one data source instead of treating
them as separate documents.

**Shipped as:** [`streaming_merge.py`](../streaming_merge.py), run against the
GDPR Extended Streaming History export (2011→2026, kept untracked — it carries
IP addresses). It writes a `rotation` field (current / dormant / historical)
onto every non-discarded inventory artist (schema updated accordingly), emits
the compact committed sidecar `data/streaming-summary.json` (per-artist plays,
minutes, first/last played, per-year histogram — inventory-matched artists plus
streaming-only artists above a 10-play floor), and prints the three finding
classes: current rotation without collection roots, collection anchors absent
from rotation, and discarded-but-streamed artists (surfaced, never silently
resurrected). Name drift is bridged with the Phase 2 alnum normalization plus
an extensible alias map. Thresholds: a play = ≥30 s; current = ≥10 plays in the
trailing 18 months (measured from the newest play in the export, so reruns are
stable); dormant floor = 10 lifetime plays.

**Remaining:** refresh `rotation` from the periodic harvest (above) instead of
one-off GDPR exports; surface rotation in the vault (artist-note field and/or a
graph preset); fold the findings into the distilled profile.

**Dependencies:** Periodic Spotify harvest above (for the refresh path).

---

## Exploration capabilities

### Anchor-Artist Catch-Up Automation

**Priority:** Medium

**What it adds:** The example profile maintains an "anchor-artist catch-up
queue" by hand (what's new from Aesop Rock, Zorn, Waits, Cash, Byrne…).
Automate it: for each anchor, web-search recent releases, then cross-
reference against the inventory so only genuinely-new material surfaces.

**Implementation sketch:**
- For each `anchor: true` artist, query for releases newer than their latest
  album already in the inventory.
- Filter against the data source so owned/known releases are dropped.
- Return a ranked "new from artists you love" list with the gap noted.

**Dependencies:** Live web search at run time (same assumption
reference-checker makes).

---

### Reservoir-First Cross-Referencing

**Priority:** Medium

**What it adds:** Formalizes a methodology principle into a repeatable check:
before reaching for external recommendations in a thread, mine what the
listener already owns. The example repeatedly found foundational material
already in the reservoir (Tzadik depth, bluegrass anchors, the
Anticon→doseone→Backwoodz social-graph bridge).

**Implementation sketch:**
- Given a thread (scene tag or named artist), first return matching
  untagged-reservoir and tagged entries already in the inventory.
- Only then suggest external adjacents (same scene/label, shared
  producer/collaborator, same era).
- Record confirmed discoveries back into the inventory with `tagged: true`.

**Dependencies:** None beyond the existing data source.

---

## Visualization

### Obsidian Graph Vault ✅ (implemented)

**What it adds:** Turns the inventory into a browsable, visual **artist graph**.
`obsidian_driver.py` renders one note per active artist that wikilinks into a
two-tier **category tree**; opened in Obsidian, the graph resolves into 13
color-coded top-level genres with subcategory sub-clusters. No artist is
pre-designated as important; node size follows degree, so the hubs emerge
from the graph rather than from a prior imposed on it.

**Implemented as:** a stdlib-only driver (sibling to `validate.py`), the
committed vault at `vault/`, and a pre-styled
`.obsidian/graph.json` (a distinct color per category, spaced by the golden
ratio; the meta hubs filtered out). Deterministic and idempotent; the output dir
is guarded by a marker file so it never clobbers a foreign directory. Edges come
from two sources:

1. **Category-tree hubs.** Each artist links into exactly one branch of a
   two-tier taxonomy: 13 top-level genres aligned with the canonical music
   taxonomies (AllMusic, Discogs, Wikipedia's popular-music families), with
   second-order subcategories where a genre deserves finer structure
   (`Hip-Hop › Underground`, `Country & Americana › Gothic Americana`).
   Grayish buckets survive only at the second order; the old record-label and
   city-scene pseudo-genres (`Def Jux`, `Stones Throw`, `Anticon`, `Patton
   Orbit`, `New Orleans`) were dissolved into real genres, splitting their
   members case by case.
2. **Collaboration edges.** Combo artist keys are parsed into their members
   (`El-P & Cannibal Ox` → El-P + Cannibal Ox; `Willie Nelson-Waylon Jennings`
   → both), and a direct artist→artist edge is drawn to each member that is
   itself in the collection. Members are only linked on an exact node match, so
   canonical groups (Hall & Oates) and `The`-prefix near-duplicates yield no
   false edges.

**Possible extensions:**
- **Named side-project edges.** Key-parsing catches `A & B`-style keys but not
  named projects whose key doesn't name its members (Hail Mary Mallon → Aesop
  Rock + Rob Sonic; Madvillain → MF DOOM + Madlib; the doseone → Backwoodz
  bridge). Those live in the profile prose; a curated `members`/`collaborators`
  schema field would let the driver draw them too.
- **Thread MOCs from the profile.** Generate a note per queued exploration
  thread (Tzadik deep dive, bluegrass extension, …) linking its key artists and
  expansion candidates, so the profile's editorial threads become navigable.
- **Era/decade lens.** An optional era-bucket edge set for a temporal view.

**Dependencies:** None for the core; the named-side-project extension depends on
adding collaboration data to the schema.

---

## Productization

### Package as a Claude Skill

**Priority:** Medium (high value for reuse)

**What it adds:** The methodology is already written to be inherited by a
fresh session. Packaging it as a proper skill (`SKILL.md` + a reference-file
table pointing at the heuristics) makes it auto-triggerable instead of
copy-pasted, and lets it run consistently against any new collection.

**Implementation sketch:**
- Author a `SKILL.md` whose trigger covers "profile / declutter / explore my
  music collection," with the discard-heuristics tables as referenced files.
- Keep `music-curation-methodology.md` as the canonical long-form source the
  skill summarizes.

**Dependencies:** None — this is a packaging/structure change.

---

### Generalize Beyond Music

**Priority:** Low (stretch)

**What it adds:** The *shape* — low-effort dump → mechanical dedup → confident
tagging → iterative discard triage with the user → queryable profile —
generalizes to other collections (books, films, board games, recipes). The
heuristics are music-specific; the workflow is not.

**Implementation sketch:**
- Factor the domain-agnostic phases from the music-specific heuristics.
- Spike one adjacent domain end-to-end before claiming generality.

**Dependencies:** A stable, exercised music methodology first — generalize
from a proven base, not a speculative one.

---

## Prioritized order

0. **Engineering spine** ✅ — JSON Schema + validator; keeps the data source
   self-consistent as it grows.
0b. **Obsidian graph vault** ✅ — visual artist map driven off the inventory;
   makes the taste structure explorable.
1. **Periodic Spotify harvest** — where the original conversation pointed;
   converts a snapshot into a living data source.
2. **Streaming + collection merge** — closes the historical-vs-current gap the
   example profile already calls out.
3. **Package as a Claude skill** — makes the whole thing reusable, not a
   one-off.
4. **Anchor-artist catch-up automation** — automates a queue maintained by
   hand today.
5. **Reservoir-first cross-referencing** — formalizes an existing principle.
6. **Generalize beyond music** — only after the music base is proven.
