#!/usr/bin/env python3
"""Merge a Spotify Extended Streaming History export into the inventory.

Implements the roadmap's "Streaming + Collection Merge": the MP3 collection is a
historical taste artifact while streaming shows the current rotation, and this
script keeps both lenses in one data source. It reads the GDPR export (which
stays untracked — it carries IP addresses), aggregates qualifying plays per
artist, and produces:

  1. data/streaming-summary.json — a compact committed sidecar (like
     credits.json) with per-artist streaming aggregates for every
     inventory-matched artist and every streaming-only artist above the floor.
  2. A `rotation` field (current / dormant / historical) written onto each
     non-discarded artist in data/music-inventory.json.
  3. Findings on stdout: current rotation without collection roots, deep
     collection anchors absent from rotation, and discarded-but-streamed
     artists (surfaced, never silently resurrected).

A play qualifies at >= 30s listened (Spotify's own stream threshold). The
"recent" window is measured back from the newest timestamp in the export, not
from the wall clock, so reruns on the same export are stable.
"""

import argparse
import glob
import json
import os
import re
import sys
import urllib.parse
from collections import Counter, defaultdict
from datetime import datetime, timedelta

DEFAULT_INVENTORY = os.path.join(os.path.dirname(__file__), "data", "music-inventory.json")
DEFAULT_EXPORT = os.path.join(os.path.dirname(__file__), "data", "my_spotify_data", "Spotify Extended Streaming History")
DEFAULT_OUT = os.path.join(os.path.dirname(__file__), "data", "streaming-summary.json")

QUALIFYING_MS = 30_000      # Spotify counts a stream at 30s
RECENT_MONTHS = 18          # "current rotation" lookback window
CURRENT_MIN_RECENT = 10     # recent plays needed to call an artist current
FLOOR_PLAYS = 10            # lifetime plays: dormant floor + sidecar inclusion

# streaming artist string (alnum) -> inventory key, for drift alnum can't bridge
ALIASES = {}


def alnum(s):
    """Punctuation/underscore-insensitive key, same normalization family as
    the Phase 2 dedup logic."""
    s = urllib.parse.unquote(s).replace("_", " ").lower()
    return re.sub(r"[^a-z0-9]", "", s)


def load_plays(export_dir):
    """Aggregate qualifying audio plays per streaming-artist key."""
    files = sorted(glob.glob(os.path.join(export_dir, "Streaming_History_Audio_*.json")))
    if not files:
        sys.exit(f"ERROR: no Streaming_History_Audio_*.json under {export_dir}")
    stats = defaultdict(lambda: {
        "name": None, "plays": 0, "minutes": 0.0,
        "first_played": None, "last_played": None,
        "recent_plays": 0, "recent_minutes": 0.0,
        "plays_by_year": Counter(),
    })
    newest = None
    rows = []
    for path in files:
        with open(path, encoding="utf-8") as fh:
            for r in json.load(fh):
                artist = r.get("master_metadata_album_artist_name")
                if not artist or (r.get("ms_played") or 0) < QUALIFYING_MS:
                    continue
                rows.append((r["ts"], artist, r["ms_played"]))
                newest = max(newest or r["ts"], r["ts"])
    cutoff = (datetime.fromisoformat(newest.replace("Z", "+00:00"))
              - timedelta(days=RECENT_MONTHS * 30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for ts, artist, ms in rows:
        s = stats[alnum(artist)]
        s["name"] = s["name"] or artist
        s["plays"] += 1
        s["minutes"] += ms / 60000.0
        s["first_played"] = min(s["first_played"] or ts, ts)
        s["last_played"] = max(s["last_played"] or ts, ts)
        s["plays_by_year"][ts[:4]] += 1
        if ts >= cutoff:
            s["recent_plays"] += 1
            s["recent_minutes"] += ms / 60000.0
    return stats, newest, cutoff


def classify(s):
    """Rotation class for an artist's streaming aggregate (None = no plays)."""
    if s is None:
        return "historical"
    if s["recent_plays"] >= CURRENT_MIN_RECENT:
        return "current"
    if s["plays"] >= FLOOR_PLAYS:
        return "dormant"
    return "historical"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--export-dir", default=DEFAULT_EXPORT,
                        help="Spotify Extended Streaming History directory")
    parser.add_argument("--inventory", default=DEFAULT_INVENTORY)
    parser.add_argument("--out", default=DEFAULT_OUT, help="sidecar output path")
    parser.add_argument("--dry-run", action="store_true",
                        help="print findings only; write nothing")
    args = parser.parse_args()

    stats, newest, cutoff = load_plays(args.export_dir)
    with open(args.inventory, encoding="utf-8") as fh:
        inv = json.load(fh)

    inv_by_alnum = {alnum(name): name for name in inv["artists"]}
    for stream_key, inv_key in ALIASES.items():
        inv_by_alnum[stream_key] = inv_key

    # --- rotation onto inventory artists -----------------------------------
    rotation_counts = Counter()
    for name, rec in inv["artists"].items():
        if rec.get("discard"):
            rec.pop("rotation", None)
            continue
        rec["rotation"] = classify(stats.get(alnum(name)))
        rotation_counts[rec["rotation"]] += 1

    # --- sidecar -------------------------------------------------------------
    entries = []
    for key, s in stats.items():
        inv_key = inv_by_alnum.get(key)
        if inv_key is None and s["plays"] < FLOOR_PLAYS:
            continue
        entries.append({
            "artist": s["name"],
            "inventory_key": inv_key,
            "plays": s["plays"],
            "minutes": round(s["minutes"], 1),
            "recent_plays": s["recent_plays"],
            "recent_minutes": round(s["recent_minutes"], 1),
            "first_played": s["first_played"],
            "last_played": s["last_played"],
            "plays_by_year": dict(sorted(s["plays_by_year"].items())),
        })
    entries.sort(key=lambda e: -e["minutes"])
    sidecar = {
        "meta": {
            "source": "Spotify Extended Streaming History (GDPR export, untracked)",
            "newest_play": newest,
            "recent_cutoff": cutoff,
            "qualifying_ms": QUALIFYING_MS,
            "recent_months": RECENT_MONTHS,
            "current_min_recent_plays": CURRENT_MIN_RECENT,
            "floor_plays": FLOOR_PLAYS,
            "streamed_artists_total": len(stats),
            "entries": len(entries),
        },
        "artists": entries,
    }

    # --- findings -------------------------------------------------------------
    stream_only = [e for e in entries
                   if e["inventory_key"] is None and e["recent_plays"] >= CURRENT_MIN_RECENT]
    stream_only.sort(key=lambda e: -e["recent_plays"])
    anchors_dormant = []
    for name, rec in inv["artists"].items():
        if rec.get("discard") or rec.get("rotation") == "current":
            continue
        if rec.get("anchor") or rec.get("album_count", 0) >= 4:
            s = stats.get(alnum(name))
            anchors_dormant.append((name, rec.get("album_count", 0),
                                    rec.get("rotation"), s["last_played"][:10] if s else "never"))
    anchors_dormant.sort(key=lambda t: -t[1])
    discarded_streamed = []
    for name, rec in inv["artists"].items():
        if not rec.get("discard"):
            continue
        s = stats.get(alnum(name))
        if s and s["plays"] >= FLOOR_PLAYS:
            discarded_streamed.append((name, s["plays"], s["last_played"][:10]))
    discarded_streamed.sort(key=lambda t: -t[1])

    print(f"rotation: {dict(rotation_counts)}")
    print(f"\nCurrent rotation with no collection roots ({len(stream_only)} artists, top 25):")
    for e in stream_only[:25]:
        print(f"  {e['recent_plays']:>5} recent plays  {e['artist']}")
    print(f"\nCollection anchors absent from current rotation ({len(anchors_dormant)}, top 25 by shelf weight):")
    for name, n_albums, rot, last in anchors_dormant[:25]:
        print(f"  {n_albums:>2} albums  {rot:<10} last streamed {last:<11} {name}")
    print(f"\nDiscarded but still streamed >= {FLOOR_PLAYS} plays ({len(discarded_streamed)}) — review, never auto-resurrect:")
    for name, plays, last in discarded_streamed:
        print(f"  {plays:>5} plays, last {last}  {name}")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(sidecar, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    with open(args.inventory, "w", encoding="utf-8") as fh:
        json.dump(inv, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"\nwrote {args.out} ({len(entries)} artists) and rotation onto {sum(rotation_counts.values())} inventory artists")


if __name__ == "__main__":
    main()
