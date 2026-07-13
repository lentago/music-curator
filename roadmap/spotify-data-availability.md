# Spotify user-data availability — harvest spec

> Reference for the roadmap's **Periodic Spotify Harvest** and **Streaming +
> Collection Merge** items. Answers one question: *what of a user's own
> Spotify data can we actually get in 2026, and how?* Written against the
> platform reality after Spotify's two big lockdowns (Nov 2024, Feb 2026) —
> not the pre-2024 API everyone still writes tutorials about.
>
> **Last verified:** 2026-07-12. The Web API surface is a moving target;
> re-check the changelogs linked at the bottom before building against it.

## TL;DR — the decision

Two harvest paths are viable for a personal, single-user project like this
one. They are complementary, not competing.

| Path | Best for | Cost of entry | The catch |
|---|---|---|---|
| **GDPR "Download your data" export** | *Lifetime* per-play history → real play counts, timestamps, skip signal | None — no app, no OAuth, no quota. Just your account. | Batch only (email delivery, up to 30 days); no genre/audio metadata. |
| **Web API (Development Mode)** | *Snapshot* of library, top artists/tracks, follows, playlists | Register an app; OAuth; **Premium account required as of Feb 2026** | Hard caps (5 users), no audio features / recommendations / genres-at-scale, `recently-played` is only the last 50 plays. |

**For this project, the GDPR Extended Streaming History export is the primary
harvest** — it is the only source that yields lifetime play counts and
per-play timestamps, which is exactly what the roadmap's proposed `rotation`
dimension (current / dormant / historical) needs and what the "recently
played was too thin" dead-end from the original run was missing. The Web API
is the secondary, *live-snapshot* lens (liked songs, current top items,
follows) for keeping the picture fresh between exports.

**What is simply gone** (for any app created after Nov 2024, which is every
new personal app): audio features (danceability/energy/valence/tempo),
audio analysis, recommendations, related-artists, and — as of Feb 2026 —
even the `popularity` field and bulk metadata fetches. Acoustic-similarity
and "artists like X" work must now be sourced from third parties (see
Path C).

---

## 0. The access-tier reality (read this first)

Everything below is gated by which **quota tier** your app occupies. There
are effectively two, and a personal project can only ever be in the first.

### Development Mode — where a personal harvest lives, permanently

The default tier for any newly registered app. As of the **February 11,
2026** changes, a new Development Mode client ID carries these limits:

- **Spotify Premium account required** to use Development Mode at all.
- **One** Development Mode client ID per developer.
- **Five** authorized users maximum (down from the old 25). Fine for
  one person; fatal for anything shared.
- **A restricted endpoint allowlist** (enumerated in Path A below). New
  client IDs got this on Feb 11, 2026; a **March 9, 2026** update
  *postponed* the endpoint restrictions for pre-existing integrations
  pending community feedback, but the Premium / 5-user / single-ID caps
  apply to everyone.
- Tighter rate limits than extended apps.

### Extended Quota Mode — unattainable for this project

The only tier that lifts the user cap and (for apps that had it *before*
Nov 2024) retains the deprecated endpoints. Since **May 15, 2025** the
approval bar is explicitly commercial:

- A legally registered business.
- **250,000+ monthly active users.**
- A launched, publicly available service, present in key markets.
- Proof of commercial viability.

A personal taste-profiling tool clears none of these. **Assume the harvest
is stuck in Development Mode forever** — design around the 5-user cap and
the reduced endpoint set, and do not plan on ever regaining audio features
via the API.

---

## Path A — Web API (live snapshot)

### Auth model

- **OAuth 2.0 Authorization Code with PKCE** for a local/native tool (no
  client secret needed in the client). Client Credentials flow exists but
  cannot read *user* data, so it is useless here.
- You request a set of **scopes**; the user consents once; you store the
  refresh token (**keep it out of the repo** — the roadmap already flags
  this).
- Token is a bearer token, ~1 hour lifetime, refreshed with the refresh
  token.

### Scopes that matter for a taste harvest

| Scope | Grants |
|---|---|
| `user-read-private` | Subscription/account type, country (the `product` field: premium/free) |
| `user-read-email` | Email address |
| `user-top-read` | Top artists and tracks |
| `user-read-recently-played` | Recently played tracks |
| `user-library-read` | Saved/"liked" tracks, albums, shows, episodes |
| `user-follow-read` | Followed artists |
| `playlist-read-private` | Private playlists |
| `playlist-read-collaborative` | Collaborative playlists |
| `user-read-playback-state` / `user-read-currently-playing` | Live player state / now-playing |

### Endpoints still available in Development Mode (Feb 2026 allowlist)

These are the read endpoints a harvest actually uses, all confirmed present
on the Feb 2026 supported list:

| Endpoint | Returns | Scope | Key limits |
|---|---|---|---|
| `GET /me` | Profile: display name, id, country, `product`, follower count, (email w/ scope) | `user-read-private`, `user-read-email` | — |
| `GET /me/top/{type}` (`artists`\|`tracks`) | Top items over a window | `user-top-read` | `time_range`: `short_term` (~4 wks), `medium_term` (~6 mo), `long_term` (~12 mo). 50/page; only the first ~99 reachable. |
| `GET /me/tracks` | Liked songs, each with `added_at` | `user-library-read` | 50/page, full library, cursor/offset |
| `GET /me/albums`, `/me/shows`, `/me/episodes`, `/me/audiobooks` | Saved library of each type | `user-library-read` | 50/page |
| `GET /me/following?type=artist` | Followed artists (incl. artist `genres`) | `user-follow-read` | cursor-paginated |
| `GET /me/playlists` → `GET /playlists/{id}/tracks` | Playlists, then tracks w/ `added_at` + `added_by` | `playlist-read-private`, `playlist-read-collaborative` | 50/page |
| `GET /me/player/recently-played` | **Only the last 50 plays**, w/ `played_at` | `user-read-recently-played` | ⚠️ Hard 50-item ceiling, short window. **This is the "too thin" source the original run hit.** Tracks only. |
| `GET /me/player`, `/me/player/currently-playing`, `/me/player/queue`, `/me/player/devices` | Live playback state / now-playing | `user-read-playback-state`, `user-read-currently-playing` | Point-in-time; poll to sample |
| `GET /search` | Catalog search (for name reconciliation) | — | Reduced result limits in Dev Mode |
| `GET /artists/{id}`, `/albums/{id}`, `/tracks/{id}` | **Single-item** metadata; artist object carries `genres` | — | Bulk multi-get removed (see below) — genre enrichment is now **one call per artist** |
| `GET /artists/{id}/albums`, `GET /albums/{id}/tracks` | Discography / tracklist | — | — |

### What was removed — do not design around these

**November 27, 2024 deprecation** (unavailable to any app without
pre-existing extended access — i.e. every new app):

- **Audio Features** (`/audio-features`) — danceability, energy, valence,
  tempo, key, loudness, acousticness, instrumentalness, etc. *The single
  biggest loss for acoustic/mood analysis.*
- **Audio Analysis** (`/audio-analysis`) — bars/beats/segments/pitch.
- **Recommendations** (`/recommendations`) — seed-based "make me a playlist".
- **Related Artists** (`/artists/{id}/related-artists`) — "artists like X".
- **Featured Playlists** and **Category's Playlists** (`/browse/*`).
- **30-second preview URLs** in multi-get responses.
- **Algorithmic & Spotify-owned editorial playlists** (Discover Weekly,
  Release Radar, etc. — cannot be read via API).

**February 2026 additional removals** (new Development Mode client IDs):

- **Bulk / multi-get endpoints** (`GET /tracks?ids=`, `/artists?ids=`,
  `/albums?ids=`) — you must fetch one id at a time now. Makes whole-library
  genre enrichment slow (N calls, rate-limited).
- **Get Artist's Top Tracks** (`/artists/{id}/top-tracks`).
- **Browse / New Releases / Markets** (`/browse/new-releases`, `/markets`).
- **Public user profiles** (`GET /users/{id}`).
- **Response fields removed** from track objects: `popularity`,
  `external_ids`, `linked_from`. (`preview_url` was already gone from
  multi-get in 2024.) So **there is no longer a per-track popularity
  signal** via the API.

### Rate limits

Rolling ~30-second window; Development Mode is throttled more tightly than
extended apps. Over-limit returns **HTTP 429 with a `Retry-After` header** —
honor it. Whole-library genre enrichment via single-artist calls is the
operation most likely to hit this; batch and back off.

---

## Path B — GDPR "Download your data" export (primary harvest)

No app, no OAuth, no quota, no Premium requirement. Request it from
**Account → Privacy settings → "Download your data"** on the web. Delivered
as a link by email. Machine-readable **JSON**. Three independently
selectable tiers:

### Tier 1 — Account Data (the fast one; ~a few days)

A broad snapshot. Relevant-to-taste contents:

- **Playlists** — names, descriptions, tracks (artist/album/title), dates,
  follower counts.
- **Streaming history — trailing 1 year only** (timestamp UTC, artist,
  title, `ms_played`). The lifetime version is Tier 2.
- **Your Library** — saved songs, albums, artists, shows, episodes, each
  with its Spotify URI.
- **Search queries** — term, date, device, which result was tapped.
- **Follows** — following / follower / blocked counts.
- **Inferences** — the ad-targeting **interest segments** Spotify has
  attached to you (a candid, if coarse, external read on taste).
- **Taste Profiles** — Spotify's own personalized streaming summary.
- **Wrapped** — annual top-content stats.
- Plus non-taste PII: payments (card last-4 etc.), profile (email, DOB,
  gender, address, phone), messages, customer-service history, family plan,
  voice-command transcripts, recent precise location. **Scrub these before
  anything lands in a published repo** — the project's data is taste-only by
  policy.

### Tier 2 — Extended Streaming History (the prize; up to 30 days)

**One row per play, for the entire lifetime of the account.** This is the
richest taste signal Spotify will hand a normal user, and it is the reason
this path is the primary harvest. Per-row fields:

| Field | Meaning |
|---|---|
| `ts` | Timestamp the stream **ended** (UTC) |
| `ms_played` | Milliseconds actually played (→ derive completion / skip) |
| `master_metadata_track_name` | Track title |
| `master_metadata_album_artist_name` | Primary artist |
| `master_metadata_album_album_name` | Album |
| `spotify_track_uri` | Track URI (join key back to the API / catalog) |
| `reason_start` | How the play began (`trackdone`, `clickrow`, `playbtn`, `appload`, …) |
| `reason_end` | How it ended (`trackdone`, `fwdbtn`, `backbtn`, `endplay`, …) |
| `shuffle` | Shuffle on? |
| `skipped` | User skipped? (⚠️ unreliable — see caveats) |
| `offline` / `offline_timestamp` | Played offline? / when |
| `incognito_mode` | Private session? |
| `platform` | Device/OS (detailed pre-Oct 2023, simplified after) |
| `conn_country` | Country of connection |
| `ip_addr` | IP address (PII — scrub) |
| `episode_name` / `episode_show_name` / `spotify_episode_uri` | Podcast fields (null for music) |

**Caveats that matter for analysis:**

- **`skipped` is unreliable pre-2022** (recorded `false` for the whole
  2015–2022 span). For real skip detection, derive it:
  `skipped OR reason_end IN ('fwdbtn','backbtn','endplay','unknown')`
  combined with a low `ms_played`.
- **Coverage starts at account creation** but can have gaps (one documented
  export was missing March 2015 – Nov 2017). Don't assume continuity.
- **~2.6% of rows overlap** in time (concurrent/duplicate stream artifacts).
- **Track de-duplication is on you** — the same recording appears under
  multiple album releases with different URIs, inflating per-track counts.
  Aggregate at (artist, title) or resolve via MusicBrainz for accurate
  play-count ranking.
- **No genre, no audio features, no popularity** in the export — it is
  play events only. Genre/mood must be joined from elsewhere (Path C).

### Tier 3 — Technical Log Information (skip)

Commands, error strings, device logs. No taste value; ignore.

---

## Path C — Exportify & third-party fill-ins

### Exportify (low-effort, in-browser)

[exportify.net](https://exportify.net) — a browser app that logs in with
*your* Spotify account (its own registered client) and dumps **playlists and
liked songs to CSV**, no code. Still the fastest way to get a clean library
snapshot. Post-Nov-2024 it **lost its audio-features columns** (energy,
valence, tempo, etc.) because the underlying endpoint is gone; what remains
is track / album / artist / duration / `added_at` / ISRC-level columns. Good
enough to normalize into the inventory; not a substitute for the export's
play history.

### Replacing the dead audio-feature / recommendation endpoints

If the project ever wants mood/acoustic vectors or "artists like X" again,
they now come from outside Spotify:

- **Genres / relationships / de-dup** → **MusicBrainz** (+ its
  artist-relationship graph) — free, open, and already the right join target
  for the collection's canonical artist identities.
- **Audio features (danceability/energy/valence/tempo)** → **ReccoBeats**,
  **AcousticBrainz** (frozen but free), or commercial (**Songstats**,
  **Musicae**, **Cyanite**).
- **Scrobble-style live history** → **Last.fm** (if the user scrobbles) is
  an alternative continuous play-history source with a still-open API and no
  5-user cap.

---

## Mapping to this project's data source

How the harvest feeds `data/music-inventory.json` and the roadmap items:

- **`rotation` dimension (current / dormant / historical)** — proposed in
  the roadmap, is *directly* computable from **Extended Streaming History**:
  bucket each artist by recency + density of `ts` (recent & frequent →
  current; old & silent → historical). This is the merge that closes the
  "MP3 collection is historical, Spotify is current" gap the example profile
  calls out.
- **`anchor` / signal strength** — lifetime play counts (aggregate rows per
  artist, after track de-dup) are a far better anchor signal than the API's
  top-50 or the now-removed `popularity` field.
- **Name reconciliation (Phase 2 dedup)** — `spotify_track_uri` +
  `GET /tracks/{id}` (or the export's URIs) give canonical artist/album
  strings to reconcile against folder-name spellings, using the same dedup
  logic Phase 2 already applies.
- **Genre / `category` tagging** — **not** free from Spotify at scale
  anymore (bulk artist fetch removed, and its genres are coarse regardless).
  Enrich from MusicBrainz, or keep tagging confident-only per the
  methodology and leave the rest in the reservoir.
- **Merge rule** — per the roadmap: harvest rows update
  `tagged`/`anchor`/rotation on existing artists and append genuinely new
  ones; they **never silently resurrect discarded entries**. Stamp each
  harvest with a date so rotation drift is visible over time.

**Recommended intake shape:** one-time **Extended Streaming History** export
for the historical spine, then a periodic **Web API** snapshot (liked songs +
top items + follows) for the living current-rotation layer. `recently-played`
alone is a dead end — the export is what makes the harvest meaningful.

---

## Sources

- [Introducing some changes to our Web API — Spotify (2024-11-27)](https://developer.spotify.com/blog/2024-11-27-changes-to-the-web-api)
- [Update on Developer Access and Platform Security — Spotify (2026-02-06)](https://developer.spotify.com/blog/2026-02-06-update-on-developer-access-and-platform-security)
- [Web API Changelog — February 2026](https://developer.spotify.com/documentation/web-api/references/changes/february-2026)
- [Web API Changelog — March 2026](https://developer.spotify.com/documentation/web-api/references/changes/march-2026)
- [February 2026 Web API Dev Mode Migration Guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide)
- [Scopes — Spotify for Developers](https://developer.spotify.com/documentation/web-api/concepts/scopes)
- [Understanding your data — Spotify Support](https://support.spotify.com/us/article/understanding-your-data/)
- [Data rights and privacy settings — Spotify Support](https://support.spotify.com/us/article/data-rights-and-privacy-settings/)
- [My Spotify extended streaming history data — Ortham's Software Notes](https://blog.ortham.net/posts/2024-12-21-spotify-streaming-history-part-1/)
- [State of Spotify Web API Report 2025 — Lee Martin](https://spotify.leemartin.com/)
- [Spotify changes developer mode API… — TechCrunch (2026-02-06)](https://techcrunch.com/2026/02/06/spotify-changes-developer-mode-api-to-require-premium-accounts-limits-test-users/)
- [Spotify cuts developer access to recommendation features — TechCrunch (2024-11-27)](https://techcrunch.com/2024/11/27/spotify-cuts-developer-access-to-several-of-its-recommendation-features/)
</content>
</invoke>
