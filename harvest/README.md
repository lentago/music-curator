# Periodic Spotify harvester (n8n + Redis queue)

The **live-snapshot** half of the roadmap's data-source lifecycle, complementing
the one-time GDPR **Extended Streaming History** export (the lifetime *batch*
spine). This harvester takes a dated snapshot of the current-rotation signals
the Web API still exposes and publishes it to a durable **message queue**; a
monthly consumer rolls the queue up and commits it to the repo.

What is and isn't reachable via the Web API in 2026 is documented in
[`../roadmap/spotify-data-availability.md`](../roadmap/spotify-data-availability.md).

## Architecture

```
Daily    Schedule → Code (fetch snapshot) → Redis Push ─┐
                                                        ▼
                                        Redis list  "spotify:harvests"   (durable buffer, ~30/mo)
                                                        │
Monthly  Schedule → Redis Get (list) → Code (aggregate → git commit → PR → auto-merge) → Redis Delete (drain)
                                                        ▼
                                        music-curator/data/harvests/YYYY-MM.json

15 min   Schedule → Redis Get (baseline) → Code (diff follows + capture now-playing)
                  → Code (fan out) → Redis Push → Redis Set (new baseline)
                                                        ▼
                                        Redis list  "spotify:follow-events"
                                                        │
Daily    Schedule → Redis Get (list) → Code (append log → open PR, no arm) → Redis Delete (drain)
                                                        ▼
                              PR appends data/harvests/follow-events.jsonl
                                                        │
CI       GitHub Action (follow-fold): harvest_merge.py → validate.py → commit onto PR
                  → merge IFF the batch is only reservoir seeds + provenance
                                                        ▼
                              data/music-inventory.json (reservoir) + data/follows.json
```

**Why a queue, not a file share.** The earlier design wrote dated JSON files to
a NAS bind-mount; mounting NAS into the n8n LXC is impossible via the Terraform
pipeline (Proxmox blocks bind-mounts to API tokens) and destroyed the container
once trying. The message-queue design touches **no bind mount, no shared
filesystem, no cluster state** — Redis is just another container in the n8n
compose. The queue also earns its keep as the **month-long buffer**: the
harvester fires daily and forgets; the consumer drains once a month and commits
a single roll-up, instead of a commit per day.

- **Hosting:** both workflows run on the existing n8n box (**LXC 113**,
  192.168.139.13); **Redis** runs beside n8n in the same compose.
- **Auth to Spotify:** loopback PKCE (public client, no secret) — n8n's own
  Spotify OAuth can't be used (its callback is non-loopback HTTP, which Spotify
  rejects). One-time consent on your workstation via `spotify_auth_bootstrap.py`;
  n8n only refreshes the token thereafter.
- **Sink:** the git repo. Raw daily snapshots never hit disk on a share — they
  live in the queue until the monthly roll-up commits the aggregate.

## Files

| File | Role |
|---|---|
| `spotify_auth_bootstrap.py` | Run **once** on your workstation → prints the refresh token. Stdlib only. |
| `gen_workflow.py` | Source of truth for the **daily producer** workflow (readable Code-node JS + emitter). Edit here, regenerate — don't hand-edit the JSON. |
| `spotify-harvest.workflow.json` | Importable n8n **producer** workflow (generated): Schedule → Code → Redis Push. |
| `gen_rollup.py` | Source of truth for the **monthly consumer** workflow (readable Code-node JS + emitter). Edit here, regenerate — don't hand-edit the JSON. |
| `rollup.workflow.json` | Importable n8n **monthly consumer** workflow (generated): Schedule → Redis Get (list) → Code (aggregate + git commit + auto-merged PR) → Redis Delete. |
| `gen_followwatch.py` | Source of truth for the **follow watcher** workflow (readable Code-node JS + emitter). Edit here, regenerate — don't hand-edit the JSON. |
| `follow-watch.workflow.json` | Importable n8n **follow watcher** workflow (generated): Schedule (15 min) → Redis Get → Code (diff + capture) → Code (fan out) → Redis Push → Redis Set. |
| `gen_followdrain.py` | Source of truth for the **follow drain** workflow (readable Code-node JS + emitter). Edit here, regenerate — don't hand-edit the JSON. |
| `follow-drain.workflow.json` | Importable n8n **follow drain** workflow (generated): Schedule (daily) → Redis Get (list) → Code (append log + open PR, never arms) → Redis Delete. |
| `../.github/workflows/follow-fold.yml` | The **fold Action** (not n8n): on a drain PR, runs `harvest_merge.py` + `validate.py`, commits the fold, and merges the PR only when every event is a reservoir seed or provenance stamp. |

## Deploy runbook

Steps 1–2 and 5–6 are yours (interactive / credentials); 3–4 are in-guest app
changes on the n8n box (not Terraform-managed).

> **Deployed (2026-07-23):** all steps below are done on LXC 113 — both
> workflows are active (`spotifyHarvest01`, `spotifyRollup01`), the Redis +
> GitHub credentials are wired, and both have been verified end-to-end (see
> **Status**). The runbook is kept as the from-scratch reference / recovery
> procedure.

### 1. Register a Spotify Developer app
[developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) →
**Create app**. Post-2026-02 Dev-Mode rules: Premium account; add your own
account under **User Management** (≤5 users); **Redirect URI** exactly
`http://127.0.0.1:8888/callback`; enable the Web API; copy the **Client ID**.

### 2. Mint the refresh token (once, on your workstation)
```bash
python harvest/spotify_auth_bootstrap.py --client-id <CLIENT_ID>
```

### 3. Add Redis + secrets to the n8n compose (on 192.168.139.13)
Put the secrets in `/opt/n8n/.env` (`chmod 600`, never committed):
```
SPOTIFY_CLIENT_ID=<CLIENT_ID>
SPOTIFY_REFRESH_TOKEN=<from step 2>
GITHUB_TOKEN=<fine-grained PAT: Contents + Pull requests write on lentago/music-curator>
```
Add to `/opt/n8n/docker-compose.yml` — the env wiring and a Redis service with
persistence:
```yaml
services:
  n8n:
    env_file: [.env]
    environment:
      - N8N_BLOCK_ENV_ACCESS_IN_NODE=false   # let the Code node read $env
  redis:
    image: redis:7-alpine
    command: ["redis-server", "--appendonly", "yes"]   # durable
    restart: unless-stopped
    volumes: [redis_data:/data]
volumes:
  redis_data:
```
Then `cd /opt/n8n && docker compose up -d`. (n8n reaches Redis at host `redis`,
port 6379, on the compose network.)

### 4. Add the Redis credential
- **Redis** — host `redis`, port `6379` (no password, internal). Used by the
  Redis nodes in both workflows.

GitHub needs **no n8n credential**: the consumer authenticates from
`$env.GITHUB_TOKEN` (step 3), because its commit runs in a Code node and n8n
Code nodes can't read the credential store. The token needs **Contents: write**
(to push the roll-up branch via the git data API) and **Pull requests: write**
(to open + auto-merge the PR). Direct-to-`main` is impossible — a ruleset
requires PRs with zero bypass — so the consumer commits to a
`harvest/rollup-YYYY-MM` branch, opens a PR, and arms squash auto-merge.

### 5. Import the workflows
All three are already imported (see the pre-staged note above). If you ever need
to re-import: Editor → **Import from File**, or via CLI
`docker exec n8n n8n import:workflow --input=/tmp/<file>` (the JSON carries a
stable `id`, so a re-import updates in place rather than duplicating). The
generated JSON now names the `redisLocal01` credential inline, so no UI step is
needed to make the Redis nodes runnable.

> **Redeploy gotchas — both cost real time to rediscover:**
>
> 1. **`import:workflow` deactivates the workflow it imports** (it says so in
>    the log). Follow every import with
>    `n8n update:workflow --id=<id> --active=true` *and* a
>    `docker compose restart n8n` — the CLI warns that activation "will not take
>    effect if n8n is running", and it means it.
> 2. **The sqlite DB is in WAL mode.** `docker cp`-ing `database.sqlite` alone
>    gives a stale snapshot that can be hours behind — a just-imported workflow
>    simply will not appear. Copy `database.sqlite-wal` and `-shm` alongside it
>    before querying `workflow_entity.active`.
> 3. **`n8n execute --id=…` cannot run while the server is up** ("Task Broker's
>    port 5679 is already in use"). To smoke-test, activate and let the schedule
>    fire, then inspect `execution_entity`.

### 6. Test, then activate
Execute the producer once; confirm one item lands on the `spotify:harvests`
Redis list (`docker exec -it redis redis-cli LLEN spotify:harvests`). Then
activate both workflows.

## What it pulls

Only user-data endpoints still available in Development Mode:

| Endpoint | Into the snapshot as | Notes |
|---|---|---|
| `GET /me` | `profile` | country, `product`, follower count |
| `GET /me/top/{artists,tracks}` × 3 ranges | `top.*` | `short`/`medium`/`long_term` |
| `GET /me/tracks` | `saved_tracks` | full liked library, with `added_at` |
| `GET /me/following?type=artist` | `followed_artists` | includes artist `genres` |
| `GET /me/playlists` | `playlists` | **metadata only** (name, owner, counts) |
| `GET /me/player/recently-played` | `recently_played` | last 50 only |

> ⚠️ **Playlist caveat:** only playlist *metadata* (`/me/playlists`) is fetched.
> Playlist *contents* (`GET /playlists/{id}/tracks`) return **403** for a
> Development-Mode operator app — the availability spec's row on this is being
> corrected. Do not add a contents fetch to the harvest.

Not available at all: audio features, audio analysis, recommendations,
related-artists, per-track `popularity`, bulk multi-get. Genre enrichment at
scale comes from MusicBrainz.

## Snapshot schema (v1)
Unchanged from the file-based design — the same object is now the queue message
body (a JSON string), not a file:
```jsonc
{ "harvested_at", "source", "harvester", "schema": 1,
  "profile": {…}, "top": { "artists": {…}, "tracks": {…} },
  "saved_tracks": […], "followed_artists": […], "playlists": […],
  "recently_played": […], "counts": {…} }
```

## Roll-up schema (v2)
Each `data/harvests/YYYY-MM.json` the consumer commits is a per-artist aggregate
over that month's daily snapshots — the compact, diffable signal the
human-in-the-loop inventory fold reads:
```jsonc
{ "month": "YYYY-MM", "generated_at", "source", "harvester", "schema": 2,
  "snapshot_days",          // how many daily snapshots rolled up
  "snapshot_first_day",     // v2: the window follow deltas are measured against
  "snapshot_last_day",
  "profile", "playlists_count", "artist_count",
  "followed_count", "new_follow_count",          // v2
  "artists": {              // keyed by artist name; keys sorted for stable diffs
    "<name>": {
      "days_seen",          // distinct snapshot days seen in any signal
      "first_seen", "last_seen",
      "top_ranges",         // subset of short/medium/long_term where in top ARTISTS
      "in_top_artists_days", "in_top_tracks_days",
      "followed",           // followed at any point in the month
      "followed_days",      // v2: distinct days observed in the follow list
      "first_followed",     // v2: first day observed followed (null if never)
      "last_followed",      // v2
      "new_follow",         // v2: first_followed is after snapshot_first_day
      "unfollowed",         // v2: last_followed is before snapshot_last_day
      "saved_tracks_max",   // max distinct saved tracks by the artist in a snapshot
      "plays",              // distinct recently-played `played_at`, de-duped across days
      "genres": […]
    }, … }
}
```
`plays` de-dupes by `played_at`, so the same play appearing in consecutive daily
`recently_played` windows counts once — a real, non-inflated listen count.

### Reading the follow fields (v2)

**Spotify exposes no `followed_at`.** `GET /me/following` returns the current
set with no timestamps, so a follow is only ever *first observed on day D*. An
artist already followed when harvesting began is indistinguishable from one
followed that same morning — which is why the deltas are anchored to the
month's own snapshot window rather than presented as absolute follow dates:

- **`new_follow`** — first observed followed *after* `snapshot_first_day`. This
  is the only case the data can actually support, and it is the signal to act
  on. Resolution is one day; the follow happened somewhere in the 24 h before
  the snapshot that first saw it.
- **`unfollowed`** — observed followed, then gone by `snapshot_last_day`.
- An artist followed continuously across the whole window has
  `new_follow: false` — correctly, since nothing new happened *within* the
  window. Cross-month new follows come from diffing consecutive roll-ups'
  `followed` sets, which the day fields do not replace.

A month whose `snapshot_days` is small (a gap in the producer, or the month it
was first deployed) makes `new_follow` unreliable in both directions — check
`snapshot_first_day`/`snapshot_last_day` before trusting a delta.

## The follow watcher

The only latency-sensitive workflow in the family. The producer and consumer
work on aggregates that can be rebuilt from a later export; this one captures
something **ephemeral** — what was playing at the moment a follow happened —
which is gone forever if not caught close to the event. That is why it runs
every 15 minutes rather than daily: a follow is a deliberate act, and the song
that caused it is the context that makes it legible later.

**How a follow is detected.** Spotify exposes no `followed_at` anywhere, so the
only way to notice a follow is to diff the current list against a remembered
one. Redis holds that baseline at `spotify:follows:last` (a JSON array of artist
names); each run compares, emits one event per change, then advances the
baseline.

**Event shape** (pushed as JSON strings onto `spotify:follow-events`):
```jsonc
{ "type": "follow" | "unfollow", "artist", "artist_id", "genres": […],
  "detected_at",                 // ISO — when the DIFF ran, not when you clicked
  "now_playing": {…} | null,     // currently-playing at detection
  "recent_tail": […],            // last 5 played, with played_at
  "trigger_confidence": "high" | "low",
  "trigger_source": "now_playing" | "recently_played" | null,
  "trigger_track": {…} | null }
```
`trigger_*` is set when the newly-followed artist appears in now-playing or the
recent tail — i.e. you followed them *while listening to them*, the common case,
and the strongest available evidence for which song caused the follow. When the
artist is nowhere in the window, confidence is `low` and `trigger_track` is
null; the surrounding context is still recorded rather than guessed at.

**Ordering.** Events are pushed **before** the baseline moves. A crash between
the two re-detects the change next cycle — a duplicate event, dedupable on
`artist` + `detected_at`. The reverse order would lose the capture permanently,
and an unrecoverable capture is exactly what this workflow exists to prevent.

**Two refusals.** A missing baseline throws rather than treating an empty
previous set as "everything is new" (that would emit a false follow event for
every artist already followed). An empty follow list from the API throws rather
than being read as a mass unfollow.

**Deploy.** Seed the baseline once before activating, or the first run throws:
```bash
# from a JSON array of the artist names you currently follow
docker cp baseline.json redis:/tmp/baseline.json
docker exec redis sh -lc 'redis-cli -x SET spotify:follows:last < /tmp/baseline.json'
```
Skipping a cycle is harmless: when the follow set is unchanged the fan-out emits
zero items, which short-circuits both the push and the baseline write — safe
precisely because an unchanged set means the stored baseline is already correct.

## Follow ingestion (drain + fold)

A follow is a **deliberate act**, so unlike the roll-up's passive signals it is
allowed to seed the inventory automatically. Ingestion is split across the two
runtimes for one reason each: only n8n can reach the LAN Redis, and only the
repo has the tested Python fold. Neither reimplements the other's job.

**Stage A — the drain (n8n, daily 05:00).** Reads `spotify:follow-events`,
appends the new events to `data/harvests/follow-events.jsonl` (deduped by the
fold's own `artist + detected_at` id), commits the append to a
`harvest/follows-<timestamp>` branch, and opens a PR. It **deliberately does not
arm auto-merge** — `main` has no required status checks, so an armed PR would
merge instantly, landing the log before the fold ever runs. The PR must stay
open for Stage B. The Redis list is drained only after the commit succeeds.

**Stage B — the fold (GitHub Action `follow-fold`).** Triggered by the drain's
PR, it runs `harvest_merge.py` (which classifies every event — seed / owned /
discarded / unfollow), runs `validate.py`, commits the resulting inventory +
`data/follows.json` onto the PR branch, and then **merges the PR only when the
batch is exclusively new reservoir seeds and provenance**. A follow of a
discarded artist (a resurrect decision) or any unfollow flips the batch to
"needs review": the Action posts a comment explaining why and leaves the PR open
for a human. This is the agreed rule — additive reservoir seeding auto-merges,
everything else waits.

Because the merge gate is this Action (not a required check), its safety is that
`harvest_merge.py` and `validate.py` both run in it; if either fails the job
fails and nothing merges. The fold is idempotent, so the commit it pushes
re-triggering the Action is a harmless no-op.

## The merge principle
The roll-up (`data/harvests/YYYY-MM.json`) and every harvest are **inputs**,
never a live rewrite of the curated inventory. Folding a harvest into
[`../data/music-inventory.json`](../data/music-inventory.json) is a separate,
deliberate, human-in-the-loop step: new signals update `tagged` / `anchor` /
the future `rotation` field and append genuinely new artists, but **never
silently resurrect discarded entries**; name drift is reconciled with the
Phase-2 dedup logic.

## Status
**Live.** Both workflows are active on LXC 113 and verified end-to-end.

- **Producer** (daily → Redis) — **active** (`spotifyHarvest01`), daily 06:00.
  Verified: real snapshots land on `spotify:harvests`.
- **Consumer** (monthly → PR) — **active** (`spotifyRollup01`), 1st of month
  02:00. Reads the whole list with a non-destructive Redis Get (keyType `list`),
  aggregates the per-artist roll-up (see *Roll-up schema*), commits
  `data/harvests/YYYY-MM.json` to a `harvest/rollup-YYYY-MM` branch via the git
  data API, opens a PR, arms squash auto-merge, then drains the queue — the drain
  only runs if the Code node succeeds, so a failure preserves the buffer.
  Verified: the first roll-up (`2026-07.json`) landed via an auto-merged PR.
  Emits **roll-up schema v2** (follow deltas) since 2026-07-23; `2026-07.json`
  predates it and carries v1, so it has no follow-day fields.
- **Follow watcher** (15 min → Redis) — **active** (`spotifyFollowWatch01`),
  every 15 minutes. Diffs `/me/following` against the `spotify:follows:last`
  baseline and pushes change events to `spotify:follow-events`. Baseline seeded
  2026-07-23 with the then-current 64 follows. The event queue is **not yet
  drained by anything** — the ingest path that folds follows into the inventory
  is the next piece of work; until then events accumulate durably in Redis.
- **Follow drain** (daily → PR) — `spotifyFollowDrain01`, daily 05:00. Drains
  `spotify:follow-events` into `data/harvests/follow-events.jsonl` via an
  unarmed PR; the `follow-fold` Action folds and conditionally merges it. See
  *Follow ingestion* above.
- **Infra** — Redis (`redis:7-alpine`, `appendonly yes`) + env wiring live in
  `/opt/n8n/docker-compose.yml`; secrets in `/opt/n8n/.env` (mode 600):
  `SPOTIFY_CLIENT_ID`, `SPOTIFY_REFRESH_TOKEN`, `GITHUB_TOKEN`.

> **Token expiry:** the `GITHUB_TOKEN` PAT expires and must be rotated before
> then, or the monthly consumer's next run 403s. Refresh it in `/opt/n8n/.env`
> and `docker compose up -d`.

## Secrets hygiene
Nothing secret in the repo. The Spotify refresh token and the `GITHUB_TOKEN` PAT
live only in `/opt/n8n/.env` (`0600`) — keep copies in Bitwarden. Rotate the
Spotify token by removing the app authorization and re-running
`spotify_auth_bootstrap.py`; rotate the GitHub PAT before its expiry (fine-grained
PATs are capped at ~1 year) by minting a new one and updating `.env`.
