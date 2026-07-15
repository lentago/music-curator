#!/usr/bin/env python3
"""Merge harvested discography files into the discographies sidecar.

Implements the "seed the collection with full discographies" flow: a harvest
step (per-artist JSON extracted from a canonical discography source, e.g. the
artist's Wikipedia discography page) is merged into
data/discographies.json — a committed sidecar (like credits.json and
streaming-summary.json) that carries every known recording per seeded artist,
whether owned or not. The curated inventory's `albums` lists keep their
meaning (albums actually in the collection); this layer is the full-catalog
lens around them.

For every harvested recording the merge computes:

  owned / owned_match — does the recording match an album already in the
      collection?  Matched with the Phase-2 alnum normalization against the
      seeded artist's own `albums` AND the credited project's `albums` when
      that project is itself a roster artist (a Zorn recording credited to
      Masada matches the collection's Masada rips).
  roster_link — the credited artist/project resolved to an inventory key when
      it is a roster artist other than the seeded one (Naked City, Electric
      Masada, ...), so the wiki driver can draw the edge.

Findings printed: per-artist totals and owned coverage, owned albums the
harvest did NOT account for (rip-name drift worth an alias), and roster links
found. --worklist writes the personnel-research worklist (album-shaped
recordings not already covered by credits.json).

Usage:
    python discography_merge.py harvest-*.json [--out data/discographies.json]
        [--inventory data/music-inventory.json] [--credits data/credits.json]
        [--worklist /tmp/worklist.json] [--harvested YYYY-MM-DD] [--dry-run]
"""

import argparse
import json
import os
import re
import sys
import urllib.parse
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_INVENTORY = os.path.join(HERE, "data", "music-inventory.json")
DEFAULT_CREDITS = os.path.join(HERE, "data", "credits.json")
DEFAULT_OUT = os.path.join(HERE, "data", "discographies.json")

# Recording types that carry an album's worth of personnel and belong in the
# credits research layer. Singles, videos, and one-track guest spots stay in
# this sidecar only.
ALBUM_TYPES = {"studio", "live", "compilation", "EP", "soundtrack"}

# Minimum alnum-key lengths for the fuzzy match tiers — below these, short
# titles ("Alice", "Elegy") only match exactly. Prefix gets a lower floor than
# containment: a shared prefix ("orphans" / "orphansbrawlersbawlersbastards")
# is much stronger evidence than a substring anywhere.
PREFIX_MIN = 6
CONTAIN_MIN = 8

_DISC_SUFFIX = re.compile(r"(?:\b(?:disc|disk|cd)\s*\d+|\[[^\]]*$|\([^)]*$)", re.I)

# Word-level drift between rip names and canonical titles that the alnum key
# can't bridge: articles, Vol./Volume, and spelled-out volume numbers
# ("Book of Angels Volume One" / "Volume 1", "The Book of Angels" / "Book of
# Angels"). Applied to both sides of the match, within one artist's scope.
_NUM_WORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
              "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
              "eleven": "11", "twelve": "12"}


def alnum(s):
    """Punctuation/underscore-insensitive key, same normalization family as
    the Phase 2 dedup logic (and streaming_merge.py)."""
    s = urllib.parse.unquote(s).replace("_", " ").lower()
    return re.sub(r"[^a-z0-9]", "", s)


def title_key(name):
    """alnum key for a recording/album title with word-level drift folded."""
    s = urllib.parse.unquote(name).replace("_", " ").lower()
    s = re.sub(r"\bthe\b", " ", s)
    s = re.sub(r"\bvol(?:ume)?\b\.?", " vol ", s)
    s = re.sub(r"\b(" + "|".join(_NUM_WORDS) + r")\b",
               lambda m: _NUM_WORDS[m.group(1)], s)
    return re.sub(r"[^a-z0-9]", "", s)


def album_key(name):
    """title_key for an owned-album rip name: disc suffixes and dangling
    bracket fragments (40-char folder truncation) stripped first."""
    return title_key(_DISC_SUFFIX.sub(" ", name))


def match_quality(rec_key, owned_key):
    """3 = exact, 2 = one is a prefix of the other (folder-name truncation,
    subtitle drift), 1 = shorter contained in longer."""
    if not rec_key or not owned_key:
        return 0
    if rec_key == owned_key:
        return 3
    short, long_ = sorted((rec_key, owned_key), key=len)
    if len(short) >= PREFIX_MIN and long_.startswith(short):
        return 2
    if len(short) >= CONTAIN_MIN and short in long_:
        return 1
    return 0


def resolve_roster(name, roster_by_alnum):
    """Inventory key for an artist/project name, tolerating a 'The ' prefix."""
    if not name:
        return None
    for cand in (name, re.sub(r"^the\s+", "", name, flags=re.I)):
        hit = roster_by_alnum.get(alnum(cand))
        if hit:
            return hit
    return None


def owned_matches(rec_key, candidates):
    """(best_quality, best 'Artist :: rip name', all qualifying strings).

    The best match is stored on the recording; *all* qualifying rip names
    count as accounted-for in the coverage finding (multi-disc rips are
    several inventory strings matching one canonical title)."""
    best = (0, None)
    all_hits = []
    for artist, album in candidates:
        q = match_quality(rec_key, album_key(album))
        if q > 0:
            all_hits.append(f"{artist} :: {album}")
        if q > best[0]:
            best = (q, f"{artist} :: {album}")
    return best[0], best[1], all_hits


def merge_artist(harvest, inventory, roster_by_alnum):
    """One harvest file -> the sidecar's per-artist record + findings."""
    artist = harvest["artist"]
    artists = inventory["artists"]
    if artist not in artists:
        sys.exit(f"ERROR: harvest artist {artist!r} is not an inventory artist")

    recordings = []
    matched_owned = set()  # 'Artist :: rip name' strings accounted for
    for sec in harvest.get("sections", []):
        for rec in sec.get("recordings", []):
            credited = rec.get("credited_to") or artist
            roster_link = resolve_roster(credited, roster_by_alnum)

            candidates = [(artist, a) for a in artists[artist].get("albums", [])]
            if roster_link and roster_link != artist:
                candidates += [(roster_link, a)
                               for a in artists[roster_link].get("albums", [])]
            quality, owned_match, all_hits = owned_matches(
                title_key(rec.get("title", "")), candidates)

            entry = {
                "title": rec.get("title"),
                "year": rec.get("year"),
                "credited_to": credited,
                "label": rec.get("label"),
                "type": rec.get("type", "other"),
                "section": sec.get("section"),
                "owned": quality > 0,
            }
            if rec.get("notes"):
                entry["notes"] = rec["notes"]
            if quality > 0:
                entry["owned_match"] = owned_match
                matched_owned.update(all_hits)
            if roster_link and roster_link != artist:
                entry["roster_link"] = roster_link
            recordings.append(entry)

    unmatched_owned = [a for a in artists[artist].get("albums", [])
                       if f"{artist} :: {a}" not in matched_owned]
    record = {
        "source_page": harvest.get("source_page"),
        "recordings": recordings,
    }
    return record, unmatched_owned


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("harvests", nargs="+", help="harvest JSON files")
    parser.add_argument("--inventory", default=DEFAULT_INVENTORY)
    parser.add_argument("--credits", default=DEFAULT_CREDITS)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--harvested", default=None,
                        help="harvest date stamp (YYYY-MM-DD) recorded per artist")
    parser.add_argument("--worklist", default=None,
                        help="write the personnel-research worklist (album-type "
                             "recordings not already covered by credits.json) here")
    parser.add_argument("--dry-run", action="store_true",
                        help="print findings only; write nothing")
    args = parser.parse_args()

    with open(args.inventory, encoding="utf-8") as fh:
        inventory = json.load(fh)
    credits = {}
    if os.path.exists(args.credits):
        with open(args.credits, encoding="utf-8") as fh:
            credits = json.load(fh)

    roster_by_alnum = {alnum(k): k for k in inventory["artists"]}

    # Existing sidecar is extended, not rebuilt: reruns replace only the
    # artists present in the given harvest files.
    sidecar = {"meta": {}, "artists": {}}
    if os.path.exists(args.out):
        with open(args.out, encoding="utf-8") as fh:
            sidecar = json.load(fh)

    worklist = []
    for path in args.harvests:
        with open(path, encoding="utf-8") as fh:
            harvest = json.load(fh)
        artist = harvest["artist"]
        record, unmatched = merge_artist(harvest, inventory, roster_by_alnum)
        if args.harvested:
            record["harvested"] = args.harvested
        sidecar["artists"][artist] = record

        recs = record["recordings"]
        owned = [r for r in recs if r["owned"]]
        links = Counter(r["roster_link"] for r in recs if r.get("roster_link"))
        types = Counter(r["type"] for r in recs)
        print(f"\n{artist}: {len(recs)} recordings "
              f"({', '.join(f'{n} {t}' for t, n in types.most_common())})")
        print(f"  owned matches: {len(owned)} recordings -> "
              f"{len({r['owned_match'] for r in owned})} collection albums")
        if links:
            print("  roster links: "
                  + ", ".join(f"{k} ({n})" for k, n in links.most_common()))
        if unmatched:
            print(f"  owned albums NOT accounted for by the harvest ({len(unmatched)}):")
            for a in unmatched:
                print(f"    - {a}")

        # Personnel worklist: album-shaped recordings whose personnel are not
        # already researched in credits.json (under this artist or the credited
        # roster project — owned rips were covered by the original credits run).
        covered = set()
        for who in {artist, *(r.get("roster_link") for r in recs if r.get("roster_link"))}:
            for alb in credits.get("artists", {}).get(who or "", {}):
                covered.add(album_key(alb))
        for r in recs:
            if r["type"] not in ALBUM_TYPES:
                continue
            if album_key(r["title"] or "") in covered:
                continue
            worklist.append({"artist": artist, "title": r["title"],
                             "year": r["year"], "credited_to": r["credited_to"],
                             "label": r["label"], "type": r["type"]})

    total = sum(len(r["recordings"]) for r in sidecar["artists"].values())
    owned_total = sum(1 for r in sidecar["artists"].values()
                      for rec in r["recordings"] if rec["owned"])
    sidecar["meta"] = {
        "source": "canonical discography pages (Wikipedia), harvested per artist",
        "artists": len(sidecar["artists"]),
        "recordings": total,
        "owned_recordings": owned_total,
    }

    print(f"\nsidecar: {len(sidecar['artists'])} artists, {total} recordings "
          f"({owned_total} owned) -> {args.out}")
    print(f"personnel worklist: {len(worklist)} album-type recordings not yet in credits")

    if args.dry_run:
        print("--dry-run: nothing written")
        return

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(sidecar, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    if args.worklist:
        with open(args.worklist, "w", encoding="utf-8") as fh:
            json.dump(worklist, fh, indent=2, ensure_ascii=False)
            fh.write("\n")


if __name__ == "__main__":
    main()
