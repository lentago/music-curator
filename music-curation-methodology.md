# Music Curation Methodology

> **Purpose:** A workflow for converting a low-effort representation of a person's music collection into a clean, queryable taste-profile that drives personalized exploration and recommendation. The output is a data source Claude can mine across conversations, not a one-shot recommendation list.

---

## When to use this skill

Trigger any time a user wants to:
- Break out of a listening rut and find new artists in styles they already love
- Catch up on recent releases from anchor artists they've been investing in
- Discover what's hiding in their own collection that they've forgotten
- Cross-reference new finds against what they already own
- Generally have a music-recommendation conversation grounded in *their actual taste data*, not algorithmic guesses

## Inputs accepted

Whatever low-effort representation the user can produce. Examples:
- Directory tree of an MP3 collection (`tree` or `find` output, file or paste)
- Spotify Wrapped data export (annual JSON)
- Plain text list of artists/albums
- Description of taste in prose, with named artists
- Hybrid: collection inventory + Spotify data + verbal anchors

The user does **not** need to clean or organize the input first. Cleanup is part of the workflow.

## Outputs produced

1. **Cleaned JSON inventory** — `music-inventory.json` with structure:
   ```json
   {
     "meta": { ... summary stats ... },
     "artists": {
       "Artist Name": {
         "albums": [...],
         "album_count": N,
         "scenes": ["scene-tag", ...],
         "era": "1990s-now",
         "genre": "...",
         "anchor": true|false,
         "tagged": true|false,
         "discard": true|false,
         "discard_reason": "..."
       }
     },
     "compilations": { "various_artists_albums": [...], "discarded": [...] }
   }
   ```
2. **Personal profile document** — anchors, confirmed signal lanes, threads queued for exploration, discard heuristics specific to this user
3. **Threads queued for exploration** — concrete next-action lanes the conversation can pull on

## Workflow phases

### Phase 1 — Intake and parse
Convert the input to a structured artist→album hierarchy. For tree/listing inputs, use depth-aware parsing (be aware that `tree` uses non-breaking spaces in continuation indents). Build a working in-memory model.

### Phase 2 — Mechanical dedup and cruft sweep
Before any taste judgment, do the structural cleanup:
- Merge duplicate artist folders from formatting drift (e.g., `16_horsepower` + `16 Horsepower`, `Wovenhand` + `Woven Hand`, `janes_addiction` + `Jane's Addiction`)
- Drop loose `.mp3` files filed at artist depth (filing errors)
- Drop torrent-tracker-only folders (`.txt` file with no audio — Demonoid residue is a common pattern)
- Drop empty folders, ringtones folders, podcast folders, playlist `.m3u` files
- Drop date-stamped `Unknown Album (8-13-2007 ...)` entries — pure metadata noise
- Detect compilation fragmentation: when N artists' only album is the same comp, that's one comp ripped weirdly, not N artists

### Phase 3 — Initial confident tagging
Tag every artist where you confidently know the scene/era/genre. Leave the rest as an "untagged reservoir." Do not guess on tagging — wrong tags pollute later analysis. Better to have a 15% tagged + 85% untagged inventory than a 100% tagged inventory with errors.

Tag dimensions:
- `scenes` (array, plural — most artists span multiple)
- `era` (rough years)
- `genre` (free text)
- `anchor` (boolean — for foundational figures the user has explicitly named)

### Phase 4 — Iterative discard triage
Run rounds of 8-12 discard candidates with the user. Each round:
- Group candidates into thematic clumps (don't pitch random selection)
- Provide a confidence ladder at the end (money on the table / strong / pushable)
- Be honest about pushability — don't pretend confident on speculative pitches

User adjudicates. Apply discards to the data, re-tag confirmed lanes, propose next round.

Stop when discard rate plateaus around 15-20%, or when most pitches are reaching into "pushable" territory.

### Phase 5 — Pivot to exploration mode
Once the inventory is clean enough, switch from triage to exploration:
- Adjacent-artist suggestions grounded in the reservoir
- Anchor-artist catch-up (what's new from artists they love)
- Reservoir mining (what they have that they've forgotten)
- Cross-reference with new finds during the exploration

---

## Discard heuristics

### High-confidence discard tells

| Pattern | Example |
|---|---|
| Sole-entry artist orthogonal to all other taste signals | Single Boney James album in a serious-jazz collection |
| `Adele - [2011] 21 (Limited Edition)` style folder naming | Download-site artifact, filed as artist |
| Lowercase-with-underscores folder names | `the_best_of_the_commodores`, torrent-naming convention |
| Single CD posing as album | The Cure *High [US #2]* — only ~3 tracks, "[US #2]" is the catalog ID |
| Multiple artist-folder spellings of the same album | `Sondre Lerche` + `Sondre Lerche and the Faces Down` both contain *Phantom Punch* |
| Budget orchestral covers | "Royal Philharmonic Orchestra Plays the Hits of Phil Collins" |
| Phase-branded comp series | "The Chillout Session 2002," "Essential Lounge Vol. 2" |
| TV-theme novelties / comedian-on-music-shelf | Sam Kinison *Live From Hell*, The A-Team theme |
| Compilation fragmentation | 7+ artists whose only album is the same single comp |
| Hype-cycle indie debut as sole entry, never returned to | Foster The People *Torches*, Phoenix *Wolfgang Amadeus*, Animal Collective *MPP*, CYHSY |
| Universal "everyone had this album" sole entries | Adele *21*, Dido *No Angel*, Bob Marley *Legend* |

### Canon-tolerance exception

**Rule:** Sole-entry "Greatest Hits" comps from foundational figures in scenes the user demonstrably loves are *acceptable*, not discardable.

**Examples that passed canon-tolerance in this triage:**
- Aretha Franklin *Jazz To Soul* (sole comp, kept — soul-canon foundational)
- James Brown *The CD Of JB* (sole comp, kept — funk-canon foundational)
- Nat King Cole *The Unforgettable* (sole comp, kept — crooner-canon foundational)
- Vince Guaraldi *A Charlie Brown Christmas* (sole album, kept — jazz-piano-canon foundational)
- Neil Young *Greatest Hits* (sole comp, kept — folk-rock-canon foundational)

**The discriminator:** Is the artist *foundational to a scene the user already deeply loves elsewhere in their collection?* If yes, keep. If no, discard candidate.

### Lesser-album rule (unreliable but worth pitching)

If an artist X is canonical and the user has X's *late-period or non-peak* album as their sole entry → discard candidate, on the reasoning that real fans would have the canonical album.

**Worked:** Bonnie Raitt *Souls Alike* (2005), The Posies *Every Kind of Light* (2005), Belly *King* (1995, lesser).

**Failed:** The Beta Band *Heroes to Zeros* (lesser, kept), The Sword *High Country* (post-peak, kept). Some users genuinely "just grabbed whatever album."

Treat as suggestion-to-pitch, not auto-kill.

### Genre-orthogonality test

"Sole entry from a genre with zero other anchors" is suspicious. Examples cleared:
- Operatic crossover pop (Bocelli, Il Divo) when no other classical-pop-vocal lane
- Smooth jazz (Boney James, Chris Botti, FOUR PLAY, The Rippingtons, The Braxton Brothers, Keiko Matsui) when serious jazz catalog elsewhere
- Slick Latin pop (Pausini, Sin Bandera, Montaner, Juanes, Chichi Peralta) when folkloric/Vallenato Latin elsewhere

### Compilation fragmentation pattern

Detect: when 5+ artists in the inventory have the *same single album* as their sole entry. That's not 5 artists — it's one comp ripped with each track filed under its own artist folder.

Example caught: *Inspiración-Espiración Remix Disc 1* by Gotan Project. Eight artists (Aníbal Troilo, Astor Piazzolla, Cerioti, Chet Baker/Gotan Project, Domingo Cura, J-Zone, Peace Orchestra, plus Gotan Project) all listed the same single album. Cleanup: keep the canonical owner (Gotan Project), discard the seven fragment-artists.

**Important corollary:** If user's only entry for an artist they care about is a comp fragment, *they don't actually have that artist*. Note this — it may surface as a future "we should add real X" thread.

### Misfile patterns to watch

- **Album title promoted to artist slot** — e.g., a folder called "The A-Team" turning out to be Aceyalone & Abstract Rude's duo project. Easy to mistake for "an artist called The A-Team." If something seems thin or oddly named, ask the user.
- **Single-track files filed at artist depth** — `Bob Mould - The Descent.mp3` sitting at the same level as artist folders.

---

## Pacing and format

- **Batches of 8-12 candidates per round.** Smaller feels low-momentum, larger overwhelms.
- **Three thematic clumps per round** — group by pattern (e.g., "smooth jazz outliers," "hype-cycle 2008-2012," "comp pile sweep"). Random selection is harder to triage.
- **Confidence ladder at the end** — *Money on the table / Strong / Pushable*. Be honest where you're guessing.
- **Acknowledge keeps as signal** — when user keeps a "doesn't fit anything else" pitch, treat it as a *new confirmed lane*. Tag it. Don't pitch the same shape again next round.
- **Surface structural findings as they appear** — duplicates, fragmentation, cruft buckets. These are usually multi-item wins.
- **Stop when the well goes brackish** — typically 15-20% discard rate. After that, per-item judgment cost exceeds value.

## Anti-patterns

- **Don't guess on unknown artist names.** They could be friends' bands, local discoveries, partner's adds, or random downloads. Ask the user. Group them and ask once.
- **Don't kill in confirmed scenes.** Once user has affirmed a lane (e.g., "industrial is real for me"), stop pitching that lane's entries.
- **Don't repeat the same pitch shape after correction.** If user pushes back on a kind of discard, internalize the lesson before next round.
- **Don't pretend confidence.** "Pushable" is honest; "money on the table" should be reserved for entries you'd actually bet on.
- **Don't tag artists you don't recognize.** Better to leave them in the untagged reservoir than to mistag.

---

## Exit criteria — knowing when to stop triaging

- Discard rate plateaus around 15-20%
- User pushes back on most pitches in a round
- Most pitches reach into "pushable" rather than "money on the table"
- Confirmed signal lanes outnumber unconfirmed signal lanes by a clear margin
- The remaining untagged reservoir is mostly non-discardable (authentic taste, just unrecognized by Claude)

When you hit exit criteria: pivot to exploration mode and offer the user a list of threads queued for exploration based on their confirmed lanes.

---

## Exploration-mode methods

Once the data source is clean and tagged:

### Adjacent-artist suggestions
Given the user loves X, suggest Y on the basis of:
- Same scene/label (DefJux roster → Anticon roster bridge)
- Same producer or collaborator (Aesop Rock → Blockhead)
- Same era and aesthetic
- Direct social-graph connection (Aesop Rock produces for billy woods now → billy woods → Armand Hammer)

### Anchor-artist catch-up
For each anchor, surface what they've done since the user last collected. Search the web for recent releases. Cross-reference with what's already in the data source.

### Reservoir mining
"Here's what you already have in genre Z that you may have forgotten about." Especially useful when user names a thread they want to explore — chances are good they have foundational material already.

### Cross-reference during discovery
When user discovers artist A, check if A's collaborators / labelmates / influences are already in their reservoir. The "have I always already had something like this?" surface.

### Thread sequencing
When multiple threads are queued, suggest order by:
- **Highest hidden depth** — where the user has invested but not exhausted (Tzadik catalog if they have 30+ Zorn records)
- **Highest current momentum** — extension of an already-active thread
- **Cleanest payoff** — tight scenes where exploration is bounded (gothic Americana around David Eugene Edwards)
- **User's stated preference** — always wins

---

## Things this methodology does NOT solve

- **The actual file-management cleanup.** This skill produces a *data source for analysis*, not a tidy MP3 library. If the user wants to clean their physical collection, that's a separate workflow.
- **Algorithmic recommendations at scale.** This is for conversations, not for batch recommendation generation. The value is in the back-and-forth.
- **Streaming-service taste profiles.** Spotify/Apple Music have algorithmic profiles already; this skill is most useful when streaming data is *insufficient* (current rotation only, sparse history, etc.) and a fuller picture is hidden in the user's owned/curated collection.
- **Discovery without anchors.** The methodology depends on having *some* taste signal to work with. A user with no established preferences won't benefit much.

---

## Collaboration notes for Claude

- Treat the user's identity as the anchor, not the algorithm's.
- Discard pitches are predictions, not pronouncements. Frame accordingly.
- The user's keeps teach you more than their discards. Pay close attention.
- Don't pad rounds to hit 12 if the well genuinely runs dry — say so, and pivot.
- The data source is for *recurring use across conversations*. Build it as something you'd want to inherit.
