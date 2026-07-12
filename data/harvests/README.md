# data/harvests/

The **committed roll-up** side of the periodic Spotify harvest. See
[`../../harvest/`](../../harvest/) for the harvester itself and
[`../../roadmap/spotify-data-availability.md`](../../roadmap/spotify-data-availability.md)
for what Spotify actually exposes.

## What lands here vs. on the NAS

- **Raw daily snapshots do NOT live here.** They land on the NAS
  (`lentago:/spotify-harvest/spotify-YYYY-MM-DD.json`) — one per day, kept off
  git so the repo doesn't accrete a snapshot every 24h.
- **This folder holds periodic roll-ups** — a compact per-artist aggregate
  (e.g. `2026-07.json`: play/appearance counts, first/last seen, which top
  ranges an artist showed up in) committed monthly, so the repo carries a
  versioned, diffable trail of rotation drift over time without the raw bulk.

## Status

**Staged.** The daily → NAS harvester is the first milestone; the roll-up
generator (NAS snapshots → this folder, committed via a monthly n8n workflow
or a LAN-side job) is a fast-follow, wired once the daily path is proven. Until
then this folder is a placeholder.

## These are inputs, not the inventory

Nothing here rewrites [`../music-inventory.json`](../music-inventory.json).
Folding a harvest into the curated inventory is a separate, deliberate,
human-in-the-loop step (per the roadmap's Streaming + Collection Merge design):
new signals update `tagged` / `anchor` / the future `rotation` field and append
genuinely new artists, but **never silently resurrect discarded entries**, and
artist-name drift is reconciled with the same Phase-2 dedup logic. The merge
tool stays under review; the harvest just supplies clean, dated evidence.
