# Periodic Spotify harvester (n8n)

The **live-snapshot** half of the roadmap's data-source lifecycle. It
complements the one-time GDPR **Extended Streaming History** export (the
lifetime *batch* spine): this harvester takes a dated snapshot of the
current-rotation signals the Web API still exposes, on a schedule, so the
"what am I listening to *now*" picture stays fresh between exports.

What is and isn't reachable via the Web API in 2026 — and why the export is
the richer source — is documented in
[`../roadmap/spotify-data-availability.md`](../roadmap/spotify-data-availability.md).
Read that first; this directory is the implementation of its "Path A".

## Architecture

```
n8n (LXC 113, pve4)                                      NAS (lentago share)
┌───────────────────────────────────────────┐           ┌──────────────────────┐
│ Schedule (daily 06:00)                     │           │ spotify-harvest/      │
│   → Code: refresh token + fetch endpoints  │  writes   │   spotify-2026-07-12  │
│   → Write Files  ──────────────────────────┼──────────▶│   spotify-2026-07-13  │
└───────────────────────────────────────────┘  /data/    │   …                   │
                                                harvests  └──────────┬───────────┘
                                                                     │ monthly roll-up
                                                                     ▼  (staged — see below)
                                                          music-curator/data/harvests/
                                                            2026-07.json  (committed)
```

- **Hosting:** a native n8n workflow on the existing **LXC 113** (`n8n`,
  192.168.139.13). Chosen over a dedicated LXC to reuse the box already stood
  up for exactly this kind of automation.
- **Auth:** loopback PKCE (public client, **no client secret**). n8n's own
  Spotify OAuth credential can't be used — its callback is
  `http://<lan-ip>:5678/...`, and since 2025-04-09 Spotify rejects non-loopback
  HTTP redirect URIs. So the one-time consent happens on your workstation
  (`spotify_auth_bootstrap.py`), and n8n only ever *refreshes* the token.
- **Output — both, per the roadmap merge design:**
  - **NAS raw daily** — one `spotify-YYYY-MM-DD.json` per run (working now).
  - **Repo monthly roll-up** — a compact per-artist aggregate committed to
    [`../data/harvests/`](../data/harvests/) (**staged**: wire up after the
    daily→NAS path is proven — see [that folder's README](../data/harvests/README.md)).

## Files

| File | Role |
|---|---|
| `spotify_auth_bootstrap.py` | Run **once** on your workstation → prints the refresh token. Stdlib only. |
| `gen_workflow.py` | Source of truth for the workflow. Holds the Code-node JS as readable text and emits the JSON. Edit here, regenerate — don't hand-edit the JSON. (Same driver→generated-output pattern as `obsidian_driver.py` → `vault/`.) |
| `spotify-harvest.workflow.json` | The importable n8n workflow (generated). |

## Setup runbook

Ordered. Steps 1–3 and 5–6 are yours (interactive / secrets); step 4 is a
kalmia PR (the LXC's shape is Terraform-enforced).

### 1. Register a Spotify Developer app

[developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) →
**Create app**. Post-2026-02 Development Mode rules apply:

- Requires a **Premium** account (you have it).
- Under **User Management**, add your own Spotify account (Dev Mode allows ≤5
  users; you're the only one).
- **Redirect URI** — set exactly: `http://127.0.0.1:8888/callback`
  (loopback literal — the only HTTP redirect Spotify still accepts).
- Enable the **Web API**. Copy the **Client ID**.

### 2. Mint the refresh token (once, on your workstation)

```bash
python harvest/spotify_auth_bootstrap.py --client-id <CLIENT_ID>
```

A browser opens; approve the scopes; the refresh token prints to your
terminal. Nothing is written to disk or git.

### 3. Put the secrets on the n8n host

On `192.168.139.13` (`ssh root@192.168.139.13`), create `/opt/n8n/.env`
(**not** in any repo), `chmod 600`:

```
SPOTIFY_CLIENT_ID=<CLIENT_ID>
SPOTIFY_REFRESH_TOKEN=<the token from step 2>
```

Wire it into `/opt/n8n/docker-compose.yml` — add the env file, allow env
access in Code nodes, and mount the NAS harvest folder (created in step 4):

```yaml
services:
  n8n:
    env_file: [.env]
    environment:
      # …existing vars…
      - N8N_BLOCK_ENV_ACCESS_IN_NODE=false   # let the Code node read $env secrets
    volumes:
      - n8n_data:/home/node/.n8n
      - /data/harvests:/data/harvests        # NAS bind (from the kalmia mount)
```

Then `cd /opt/n8n && docker compose up -d`. (Editing the compose *inside* the
LXC is a legitimate in-guest app change — kalmia governs the LXC, not the app
running in it.)

### 4. Add the NAS bind-mount to the LXC (kalmia PR)

The container has no NAS mount today, so it has nowhere to land the raw
snapshots. Add a `mount_point` to the `n8n` container resource in
`kalmia/terraform/containers.tf` (mirrors how `pub` mounts the web folder):

```hcl
mount_point {
  volume = "/mnt/neptune-lentago/spotify-harvest"  # pve4 host path (NAS)
  path   = "/data/harvests"                          # inside the LXC
}
```

Create the NAS folder first (`/volume1/lentago/spotify-harvest/` on neptune),
open the PR, let the gha-runner apply on merge. **Do not `pct set` the mount
live** — the next kalmia apply would revert it.

### 5. Import the workflow into n8n

Editor → **⋯ → Import from File** → `harvest/spotify-harvest.workflow.json`.
It imports **inactive**.

### 6. Test, then activate

Open the workflow → **Execute Workflow** once. Confirm a
`spotify-YYYY-MM-DD.json` appears in the NAS `spotify-harvest/` folder and its
`counts` look sane. Then toggle the workflow **Active** for the daily run.

## What it pulls

Only the user-data endpoints still available in Development Mode (see the
availability spec for the full picture, including the dead ones):

| Endpoint | Into the snapshot as | Notes |
|---|---|---|
| `GET /me` | `profile` | country, `product` (premium/free), follower count |
| `GET /me/top/{artists,tracks}` × 3 ranges | `top.artists`, `top.tracks` | `short_term` ≈ 4wk, `medium_term` ≈ 6mo, `long_term` ≈ 12mo |
| `GET /me/tracks` | `saved_tracks` | full liked library, paginated, with `added_at` |
| `GET /me/following?type=artist` | `followed_artists` | includes each artist's `genres` |
| `GET /me/playlists` | `playlists` | metadata only (name, owner, counts) — no track dumps |
| `GET /me/player/recently-played` | `recently_played` | **last 50 only** — the export is what covers real history |

**Not available** (don't expect them): audio features, audio analysis,
recommendations, related-artists, and — since Feb 2026 — the per-track
`popularity` field and bulk multi-get. Genre enrichment at scale must come
from MusicBrainz, not here.

## Snapshot schema (v1)

```jsonc
{
  "harvested_at": "2026-07-12T06:00:03Z",
  "source": "spotify-web-api",
  "harvester": "music-curator/n8n",
  "schema": 1,
  "profile":   { "id", "display_name", "country", "product", "followers" },
  "top": {
    "artists": { "short_term": [{ "id", "name", "genres" }], "medium_term": [...], "long_term": [...] },
    "tracks":  { "short_term": [{ "id", "name", "uri", "artists": [], "album", "duration_ms" }], ... }
  },
  "saved_tracks":     [{ "added_at", "id", "name", "uri", "artists": [], "album", "duration_ms" }],
  "followed_artists": [{ "id", "name", "genres": [] }],
  "playlists":        [{ "id", "name", "owner", "tracks_total", "public", "collaborative" }],
  "recently_played":  [{ "played_at", "id", "name", "uri", "artists": [], "album", "duration_ms" }],
  "counts":           { "saved_tracks", "followed_artists", "playlists", "recently_played" }
}
```

## The merge principle (important)

Snapshots are **inputs**, never a live rewrite of the curated inventory. Per
the roadmap's Streaming + Collection Merge design, folding a harvest into
[`../data/music-inventory.json`](../data/music-inventory.json) is a **separate,
deliberate, human-in-the-loop step**:

- New rows update `tagged` / `anchor` / (future) `rotation` on existing
  artists and append genuinely new ones.
- They **never silently resurrect discarded entries.**
- Artist-name drift (a streaming string vs. a folder spelling) is reconciled
  with the same Phase-2 dedup logic the methodology already uses.

The harvester's only job is to land clean, dated snapshots. The merge tool is
a roadmap follow-on and stays under human review.

## Secrets hygiene

Nothing secret lives in this repo. The refresh token exists only in
`/opt/n8n/.env` on the LXC (`0600`) — keep a canonical copy in Bitwarden. The
PKCE flow uses no client secret. If the token is ever leaked, rotate it by
removing the app authorization in your Spotify account and re-running step 2.
