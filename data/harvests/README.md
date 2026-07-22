# data/harvests/

The **committed roll-up** landing for the periodic Spotify harvest. See
[`../../harvest/`](../../harvest/) for the harvester and
[`../../roadmap/spotify-data-availability.md`](../../roadmap/spotify-data-availability.md)
for what Spotify exposes.

## What lands here vs. in the queue

- **Raw daily snapshots do NOT live here, and are not files on any share.** The
  daily producer publishes each snapshot to a **durable Redis queue** (list
  `spotify:harvests`) on the n8n box, where it buffers until the monthly
  roll-up.
- **This folder holds the monthly roll-up** — a compact per-artist aggregate
  (`YYYY-MM.json`: play/appearance counts, first/last seen, which top-ranges an
  artist showed up in) committed by the roll-up workflow's **GitHub node** after
  it drains the queue. So the repo carries a versioned, diffable trail of
  rotation drift over time, without the raw per-day bulk.

## Status

**Staged, pending activation.** Both the daily → Redis producer and the monthly
consumer (which drains Redis, aggregates, and commits here) are built and
imported into n8n (inactive); Redis and the `.env` scaffold are live on the n8n
box. What remains is the Spotify OAuth + n8n credentials + activation — see the
[harvest README's Status](../../harvest/README.md#status).

## These are inputs, not the inventory

Nothing here rewrites [`../music-inventory.json`](../music-inventory.json).
Folding a harvest into the curated inventory is a separate, deliberate,
human-in-the-loop step: new signals update `tagged` / `anchor` / the future
`rotation` field and append genuinely new artists, but **never silently
resurrect discarded entries**; name drift is reconciled with the Phase-2 dedup
logic.
