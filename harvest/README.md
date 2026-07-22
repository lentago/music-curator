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
Monthly  Schedule → Redis Get (list) → Code (aggregate) → GitHub commit → Redis Delete (drain)
                                                        ▼
                                        music-curator/data/harvests/YYYY-MM.json
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
| `rollup.workflow.json` | Importable n8n **monthly consumer** workflow (generated): Schedule → Redis Get (list) → Code (aggregate) → GitHub commit → Redis Delete. |

## Deploy runbook

Steps 1–2 and 5–6 are yours (interactive / credentials); 3–4 are in-guest app
changes on the n8n box (not Terraform-managed).

> **Pre-staged (2026-07-22):** the in-guest infra of step 3 (Redis service +
> env wiring + a `/opt/n8n/.env` scaffold with **empty** placeholders) is
> already applied on LXC 113, and both workflows are already imported into n8n
> (step 5, inactive: `spotifyHarvest01`, `spotifyRollup01`). What's left for
> you: steps 1–2 (Spotify OAuth), step 4 (add the two credentials in the UI and
> assign them), then step 6 (test + activate). See **Status**.

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
Put the Spotify secrets in `/opt/n8n/.env` (`chmod 600`, never committed):
```
SPOTIFY_CLIENT_ID=<CLIENT_ID>
SPOTIFY_REFRESH_TOKEN=<from step 2>
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

### 4. Add the two n8n credentials
- **Redis** — host `redis`, port `6379` (no password, internal). Used by the
  Redis nodes in both workflows.
- **GitHub API** — a fine-grained PAT with **`contents: write`** on
  `lentago/music-curator`. Used by the roll-up's GitHub node to commit.

### 5. Import the workflows
Both are already imported (see the pre-staged note above). If you ever need to
re-import: Editor → **Import from File** → `spotify-harvest.workflow.json` and
`rollup.workflow.json`, or via CLI
`docker exec n8n n8n import:workflow --input=/tmp/<file>` (the JSON carries a
stable `id`, so a re-import updates in place rather than duplicating). Assign the
credentials to the Redis/GitHub nodes.

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

## Roll-up schema (v1)
Each `data/harvests/YYYY-MM.json` the consumer commits is a per-artist aggregate
over that month's daily snapshots — the compact, diffable signal the
human-in-the-loop inventory fold reads:
```jsonc
{ "month": "YYYY-MM", "generated_at", "source", "harvester", "schema": 1,
  "snapshot_days",          // how many daily snapshots rolled up
  "profile", "playlists_count", "artist_count",
  "artists": {              // keyed by artist name; keys sorted for stable diffs
    "<name>": {
      "days_seen",          // distinct snapshot days seen in any signal
      "first_seen", "last_seen",
      "top_ranges",         // subset of short/medium/long_term where in top ARTISTS
      "in_top_artists_days", "in_top_tracks_days",
      "followed",           // followed at any point in the month
      "saved_tracks_max",   // max distinct saved tracks by the artist in a snapshot
      "plays",              // distinct recently-played `played_at`, de-duped across days
      "genres": […]
    }, … }
}
```
`plays` de-dupes by `played_at`, so the same play appearing in consecutive daily
`recently_played` windows counts once — a real, non-inflated listen count.

## The merge principle
The roll-up (`data/harvests/YYYY-MM.json`) and every harvest are **inputs**,
never a live rewrite of the curated inventory. Folding a harvest into
[`../data/music-inventory.json`](../data/music-inventory.json) is a separate,
deliberate, human-in-the-loop step: new signals update `tagged` / `anchor` /
the future `rotation` field and append genuinely new artists, but **never
silently resurrect discarded entries**; name drift is reconciled with the
Phase-2 dedup logic.

## Status
Both workflows are code-complete and **staged on the n8n box** (LXC 113). The
harvester is not yet live only because the Spotify OAuth (steps 1–2) hasn't been
run — there are no other blockers.

- **Producer** (daily → Redis) — built (`spotify-harvest.workflow.json`),
  imported as `spotifyHarvest01` (inactive).
- **Consumer** (monthly → GitHub) — built (`rollup.workflow.json`,
  `gen_rollup.py`), imported as `spotifyRollup01` (inactive). Reads the whole
  list with a non-destructive Redis Get (keyType `list`), aggregates the
  per-artist roll-up (see *Roll-up schema*), commits `data/harvests/YYYY-MM.json`
  via the GitHub node, then deletes the drained key — the Delete only runs if the
  commit succeeds, so a failed commit preserves the buffer.
- **Infra staged** — Redis (`redis:7-alpine`, `appendonly yes`) and the env
  wiring (`env_file`, `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`) are live in
  `/opt/n8n/docker-compose.yml`; `/opt/n8n/.env` exists (mode 600) with **empty**
  `SPOTIFY_CLIENT_ID` / `SPOTIFY_REFRESH_TOKEN` placeholders.
- **Remaining (activation)** — steps 1–2 (register the app + mint the refresh
  token; needs your Premium account), fill `/opt/n8n/.env` and
  `docker compose up -d`, add the **Redis** + **GitHub API** credentials in the
  n8n UI and assign them, test-run the producer (one item on `spotify:harvests`),
  then activate both workflows.

> **Committing to `main`:** the consumer's GitHub node commits the monthly
> roll-up directly to the default branch. Confirm the fine-grained PAT (and any
> branch protection on `music-curator`) permits a bot push to `data/harvests/` on
> `main`; if not, point the node at a branch and open a PR instead. Verify this
> at activation — it can't be exercised until there's queue data to roll up.

## Secrets hygiene
Nothing secret in the repo. The refresh token lives only in `/opt/n8n/.env`
(`0600`) — keep a copy in Bitwarden. The GitHub PAT lives only in the n8n
credential store. Rotate the Spotify token by removing the app authorization
and re-running `spotify_auth_bootstrap.py`.
