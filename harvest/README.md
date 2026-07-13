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
Monthly  Schedule → Redis Llen → pop N → Code (aggregate) → GitHub commit
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
| `rollup.workflow.json` | Importable n8n **monthly consumer** workflow (drains Redis → aggregates → GitHub commit). *(staged — see Status)* |

## Deploy runbook

Steps 1–2 and 5–6 are yours (interactive / credentials); 3–4 are in-guest app
changes on the n8n box (not Terraform-managed).

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
Editor → **Import from File** → `spotify-harvest.workflow.json` (and, once
built, `rollup.workflow.json`). Assign the credentials to the Redis/GitHub nodes.

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

## The merge principle
The roll-up (`data/harvests/YYYY-MM.json`) and every harvest are **inputs**,
never a live rewrite of the curated inventory. Folding a harvest into
[`../data/music-inventory.json`](../data/music-inventory.json) is a separate,
deliberate, human-in-the-loop step: new signals update `tagged` / `anchor` /
the future `rotation` field and append genuinely new artists, but **never
silently resurrect discarded entries**; name drift is reconciled with the
Phase-2 dedup logic.

## Status
- **Producer** (daily → Redis) — built (`spotify-harvest.workflow.json`).
- **Redis + credentials + monthly consumer** — staged. The consumer
  (`rollup.workflow.json`) drains the list, aggregates a per-artist roll-up
  (play/appearance counts, first/last seen, which top-ranges each artist
  showed up in), and commits via the GitHub node.

## Secrets hygiene
Nothing secret in the repo. The refresh token lives only in `/opt/n8n/.env`
(`0600`) — keep a copy in Bitwarden. The GitHub PAT lives only in the n8n
credential store. Rotate the Spotify token by removing the app authorization
and re-running `spotify_auth_bootstrap.py`.
