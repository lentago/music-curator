#!/usr/bin/env python3
"""Fold Spotify follow events into the inventory.

A follow is the one Spotify signal that is a *deliberate act*: you chose to
follow that artist, the way you chose which rips to keep. That is categorically
different from the passive telemetry the monthly roll-up carries (top-artist
ranks, play presence), and it is why a follow is allowed to *seed* the inventory
automatically while the roll-up only ever proposes. This tool is the fold for
that deliberate signal; the roll-up fold, when it exists, will be report-only.

Input is the durable follow-event log the watcher produces
(`data/harvests/follow-events.jsonl`, one JSON event per line — appended by the
daily n8n drain). Each event is dispositioned into exactly one class:

  seed            new artist -> appended to the untagged reservoir. The honest
                  destination: Spotify's `genres` comes back empty, so there is
                  nothing to categorize from, and guessing a tag is what the
                  methodology forbids. Gets `source: spotify-follow` + a
                  `followed_at` stamp so the record explains its own origin.
  provenance      the follow matches an artist already in the collection ->
                  the inventory record is left untouched; the follow is recorded
                  in the sidecar only.
  follow-discarded  the follow matches a *discarded* artist -> NOT resurrected.
                  Recorded and flagged; resurrection stays an explicit human
                  call (the methodology's "surfaced, never silently resurrected"
                  rule).
  unfollow        recorded in the sidecar; never deletes, never auto-discards.
                  An unfollow is a far weaker signal than a follow and easy to
                  do by accident.

`seed` and `provenance` are auto-mergeable; `follow-discarded` and `unfollow`
require review, so a batch containing either is reported as NOT auto-mergeable
and the automation opens the PR unarmed.

Outputs:
  1. data/follows.json  -- the provenance sidecar (like credits.json): per-artist
     follow time, the song captured at the follow, its confidence, and the
     "seed ties" (co-artists on the trigger track that are in the collection --
     the earned edges that let a seeded artist wire into the graph).
  2. Inventory mutation: new reservoir artists for seeds; the three live meta
     counters recomputed. Nothing else on the spine is touched.

The fold is idempotent: every applied event id is recorded in the sidecar's
ledger, so re-running over the same (or a longer) log folds nothing twice, and
a run that changes nothing rewrites nothing.

Stdlib only.
"""

import argparse
import json
import os
import sys

from curator_lib import alnum, index_by_alnum

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_INVENTORY = os.path.join(HERE, "data", "music-inventory.json")
DEFAULT_EVENTS = os.path.join(HERE, "data", "harvests", "follow-events.jsonl")
DEFAULT_SIDECAR = os.path.join(HERE, "data", "follows.json")

SOURCE = "spotify-follow"

# Dispositions that do not need a human before merging.
AUTO_OK = {"seed", "provenance"}


def load_events(path):
    """Parse a JSONL follow-event log. Missing file -> no events (not an error:
    the log simply hasn't been written yet). Blank lines are skipped."""
    if not os.path.exists(path):
        return []
    events = []
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as exc:
                sys.exit(f"ERROR: {path}:{lineno}: invalid JSON event: {exc}")
    return events


def event_key(event):
    """Idempotency id: an event is uniquely the (artist, detected_at) pair the
    watcher stamps. NUL-joined so no artist name can collide with the separator."""
    return f"{event.get('artist', '')}\x00{event.get('detected_at', '')}"


def compact_track(track):
    """The stored form of a captured track: identity only, no volatile playback
    state (progress_ms / is_playing drift between snapshots and are not
    provenance)."""
    if not track:
        return None
    out = {
        "track": track.get("track"),
        "artists": list(track.get("artists") or []),
        "album": track.get("album"),
        "uri": track.get("uri"),
    }
    if track.get("played_at"):
        out["played_at"] = track["played_at"]
    return out


def seed_ties(trigger_track, followed_name, roster_index):
    """Inventory keys of the trigger track's *other* artists that are in the
    collection.

    You followed Kenny Segal while a billy woods track he produced was playing:
    woods is in the collection, so that is a real, earned edge from the new node
    into the graph -- the whole reason the watcher captures the song. Discarded
    artists are excluded (roster_index is built from active artists only), and
    the followed artist never ties to itself.
    """
    if not trigger_track:
        return []
    self_key = alnum(followed_name)
    ties = []
    for co in trigger_track.get("artists") or []:
        if alnum(co) == self_key:
            continue
        hit = roster_index.get(alnum(co))
        if hit:
            ties.append(hit)
    return sorted(set(ties), key=str.lower)


def fold(inventory, sidecar, events):
    """Apply the events to (inventory, sidecar) in place. Returns a list of
    action records describing each event's disposition, for the summary and the
    arming decision. Pure function of its inputs -> deterministic reruns."""
    artists = inventory["artists"]
    # Match against ACTIVE artists only: a discarded key must not absorb a
    # follow as "provenance", it has to surface as a resurrect decision.
    active_index = index_by_alnum(
        [n for n, r in artists.items() if not r.get("discard")]
    )
    # A separate index over discarded keys, to name the resurrect target.
    discarded_index = index_by_alnum(
        [n for n, r in artists.items() if r.get("discard")]
    )

    side_artists = sidecar.setdefault("artists", {})
    ledger = set(sidecar.setdefault("processed_events", []))

    actions = []
    dirty_inventory = False

    # Deterministic order: chronological, then artist, then type. Reruns and
    # re-orderings of the log produce the same result.
    for event in sorted(events, key=lambda e: (e.get("detected_at", ""),
                                               e.get("artist", ""),
                                               e.get("type", ""))):
        key = event_key(event)
        name = event.get("artist", "")
        if key in ledger:
            actions.append({"disposition": "skip-dup", "artist": name,
                            "detected_at": event.get("detected_at")})
            continue
        ledger.add(key)
        sidecar["processed_events"] = sorted(ledger)

        etype = event.get("type")
        if etype == "unfollow":
            rec = side_artists.setdefault(name, {})
            rec["unfollowed_at"] = event.get("detected_at")
            actions.append({"disposition": "unfollow", "artist": name,
                            "detected_at": event.get("detected_at")})
            continue

        if etype != "follow":
            actions.append({"disposition": "unknown", "artist": name,
                            "detail": f"unrecognized event type {etype!r}"})
            continue

        detected = event.get("detected_at")
        trigger = compact_track(event.get("trigger_track"))
        ties = seed_ties(trigger, name, active_index)

        # Sidecar provenance is recorded for every follow, whatever the
        # inventory disposition -- the follow happened and the moment was
        # captured regardless of whether the artist is new, owned, or discarded.
        rec = side_artists.get(name, {})
        rec["followed_at"] = min(rec.get("followed_at") or detected, detected) if detected else rec.get("followed_at")
        rec["last_event_at"] = max(rec.get("last_event_at") or detected, detected) if detected else rec.get("last_event_at")
        if event.get("artist_id"):
            rec["artist_id"] = event["artist_id"]
        rec["trigger_confidence"] = event.get("trigger_confidence")
        rec["trigger_source"] = event.get("trigger_source")
        rec["trigger_track"] = trigger
        if ties:
            rec["seed_ties"] = ties
        if event.get("genres"):
            rec["genres"] = sorted(set(event["genres"]))
        side_artists[name] = rec

        active_hit = active_index.get(alnum(name))
        discarded_hit = discarded_index.get(alnum(name))

        if discarded_hit:
            rec["matched_discarded"] = discarded_hit
            actions.append({"disposition": "follow-discarded", "artist": name,
                            "detail": f"follow matches discarded artist {discarded_hit!r}",
                            "detected_at": detected})
        elif active_hit:
            rec["matched_inventory"] = active_hit
            actions.append({"disposition": "provenance", "artist": name,
                            "matched": active_hit, "detected_at": detected})
        else:
            # New seed -> the untagged reservoir.
            artists[name] = {
                "albums": [],
                "album_count": 0,
                "tagged": False,
                "source": SOURCE,
                "followed_at": detected,
            }
            rec["seeded"] = True
            dirty_inventory = True
            actions.append({"disposition": "seed", "artist": name,
                            "seed_ties": ties, "detected_at": detected})

    if dirty_inventory:
        _recount_meta(inventory)

    return actions, dirty_inventory


def _recount_meta(inventory):
    """Recompute the three live counters validate.py checks. triage_summary is a
    frozen record of the original 13-round run and is deliberately left alone."""
    artists = inventory["artists"]
    meta = inventory["meta"]
    meta["total_unique_artists"] = len(artists)
    meta["tagged_artists"] = sum(1 for r in artists.values() if r.get("tagged") is True)
    meta["untagged_artists"] = sum(1 for r in artists.values() if r.get("tagged") is False)


def write_json(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def summarize(actions):
    """(auto_mergeable, summary dict) from the action list."""
    by = {}
    for a in actions:
        by.setdefault(a["disposition"], []).append(a)
    review = [a for a in actions if a["disposition"] not in AUTO_OK
              and a["disposition"] != "skip-dup"]
    applied = [a for a in actions if a["disposition"] != "skip-dup"]
    auto = bool(applied) and not review
    return auto, {
        "auto_mergeable": auto,
        "applied": len(applied),
        "seeded": [a["artist"] for a in by.get("seed", [])],
        "provenance": [a["artist"] for a in by.get("provenance", [])],
        "review": [{"artist": a["artist"], "why": a["disposition"],
                    "detail": a.get("detail")} for a in review],
        "skipped_duplicates": len(by.get("skip-dup", [])),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--events", default=DEFAULT_EVENTS,
                        help="JSONL follow-event log (default: data/harvests/follow-events.jsonl)")
    parser.add_argument("--inventory", default=DEFAULT_INVENTORY)
    parser.add_argument("--sidecar", default=DEFAULT_SIDECAR,
                        help="follow-provenance sidecar (default: data/follows.json)")
    parser.add_argument("--summary", help="write the machine-readable arming summary to this path")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the disposition only; write nothing")
    args = parser.parse_args()

    events = load_events(args.events)
    with open(args.inventory, encoding="utf-8") as fh:
        inventory = json.load(fh)
    sidecar = ({"artists": {}, "processed_events": []}
               if not os.path.exists(args.sidecar)
               else json.load(open(args.sidecar, encoding="utf-8")))

    actions, dirty_inventory = fold(inventory, sidecar, events)
    auto, summary = summarize(actions)

    print(f"events read: {len(events)}  applied: {summary['applied']}  "
          f"skipped(dup): {summary['skipped_duplicates']}")
    if summary["seeded"]:
        print(f"\nseeded to reservoir ({len(summary['seeded'])}):")
        for a in [x for x in actions if x["disposition"] == "seed"]:
            ties = f"  ties: {', '.join(a['seed_ties'])}" if a.get("seed_ties") else ""
            print(f"  + {a['artist']}{ties}")
    if summary["provenance"]:
        print(f"\nfollow of an owned artist ({len(summary['provenance'])}): "
              + ", ".join(summary["provenance"]))
    if summary["review"]:
        print(f"\nNEEDS REVIEW ({len(summary['review'])}) — PR opens unarmed:")
        for r in summary["review"]:
            print(f"  ! {r['artist']}: {r['detail'] or r['why']}")
    print(f"\nauto-mergeable: {auto}")

    if args.summary:
        write_json(args.summary, summary)

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return

    write_json(args.sidecar, sidecar)
    if dirty_inventory:
        write_json(args.inventory, inventory)
        print(f"wrote {args.inventory} (+{len(summary['seeded'])} seeded) and {args.sidecar}")
    else:
        print(f"wrote {args.sidecar} (inventory unchanged)")


if __name__ == "__main__":
    main()
