# Roadmap

Planned capabilities for the music-curation methodology. Each entry includes
what it adds, an implementation sketch, a priority, and dependencies. Items
are grounded in threads that surfaced during the original triage run — not
speculative feature-padding.

**Status:** The methodology (`music-curation-methodology.md`) and worked
`examples/` are the core deliverable. The items below are planned extensions.

**Implemented:** Engineering spine (issue #4) — `schema/music-inventory.schema.json`
(JSON Schema Draft 7 for structural validation) and `validate.py` (cross-field
integrity checker + near-duplicate artist-key detection). CI runs the validator on
every change to the inventory, schema, or validator itself (`.github/workflows/validate.yml`).

---

## Data-source lifecycle

### Periodic Spotify Harvest (Exportify)

**Priority:** High (the natural next step — this is where the original
conversation ended)

**What it adds:** Turns a one-time collection snapshot into a *living* data
source. The original run pulled "recently played" via the Spotify API and
found the sample too thin to be meaningful. [Exportify](https://exportify.net)
exports full playlist and liked-songs data; run on a schedule, it becomes a
periodic harvest that keeps the current-rotation picture fresh alongside the
historical-collection picture.

**Implementation sketch:**
- Document the Exportify export → normalize-to-inventory step as a Phase 1
  intake variant (the methodology already accepts Spotify exports as input).
- Define a merge rule: new harvest rows update `tagged`/`anchor`/rotation
  signals on existing artists and append genuinely new ones; they never
  silently resurrect discarded entries.
- Stamp each harvest with a date so rotation drift is visible over time.

**Dependencies:** A repeatable export path (Exportify in-browser, or the
Spotify Web API with a stored token — keep any token out of the repo).

---

### Streaming + Collection Merge

**Priority:** High

**What it adds:** The example profile explicitly notes the gap — the MP3
collection is a *historical* taste artifact (deepest investment ~2000–2010),
while Spotify shows the *current* rotation, and they don't fully overlap. A
first-class merge keeps both lenses in one data source instead of treating
them as separate documents.

**Implementation sketch:**
- Add a `rotation` dimension to the inventory schema (current / dormant /
  historical) distinct from `era`.
- Reconcile naming drift across sources (a streaming artist string vs. a
  folder-name spelling) using the same dedup logic as Phase 2.
- Surface "current rotation has no collection roots" and "deep collection
  anchor absent from current rotation" as explicit findings — both are
  exploration fuel.

**Dependencies:** Periodic Spotify harvest above.

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
