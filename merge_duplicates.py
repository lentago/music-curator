#!/usr/bin/env python3
"""Merge name-variant duplicate artists across the inventory and sidecars (#42).

An artist carried under two spellings fragments its albums, graph edges and
rotation stamp across two nodes. Merging retires one key, so every layer that
joins on the artist key has to follow: credits.json holds album maps under the
key AND collection_match back-references pointing at it; follows.json and the
streaming sidecar key on it too.

Rotation is deliberately NOT reconciled here — run streaming_merge.py
afterwards to re-derive it from the raw export against the merged roster.

    python merge_duplicates.py --dry-run
    python merge_duplicates.py
"""
import argparse
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dedup_lib import best_title, merge_albums  # noqa: E402

INVENTORY = os.path.join(HERE, 'data', 'music-inventory.json')
CREDITS = os.path.join(HERE, 'data', 'credits.json')
FOLLOWS = os.path.join(HERE, 'data', 'follows.json')

# (key_a, key_b, canonical) — canonical may be a third spelling when both
# recorded keys are wrong, as with the missing space in the Sonny Terry key.
MERGES = [
    ('16 Horsepower', 'Sixteen Horsepower', '16 Horsepower'),
    ('Beat Junkies', 'The Beat Junkies', 'The Beat Junkies'),
    ('Dave Matthews Band', 'The Dave Matthews Band', 'Dave Matthews Band'),
    ('Dresden Dolls', 'The Dresden Dolls', 'The Dresden Dolls'),
    ('Grateful Dead', 'The Grateful Dead', 'Grateful Dead'),
    ('Magnetic Fields', 'The Magnetic Fields', 'The Magnetic Fields'),
    ('Microphones', 'The Microphones', 'The Microphones'),
    ('Red Hot Chili Peppers', 'The Red Hot Chili Peppers',
     'Red Hot Chili Peppers'),
    ('Sigur Ros', 'Sigur Rós', 'Sigur Rós'),
    ('The xx', 'Xx', 'The xx'),
    ('Neko Case & Her Boyfriends', 'Neko Case And Her Boyfriends',
     'Neko Case & Her Boyfriends'),
    ('Juan Luis Guerra 440', 'Juan Luis Guerra y 440', 'Juan Luis Guerra 440'),
    ('Sonny Terry with Johnny Winter& Willie Dixon',
     'Sonny Terry with Johnny Winter& Willie D',
     'Sonny Terry with Johnny Winter & Willie Dixon'),
    ('Joshua Bell-Edgar Meyer-Sam Bush-Mike Marshall',
     'Joshua Bell_Edgar Meyer_Sam Bush_Mike Ma',
     'Joshua Bell-Edgar Meyer-Sam Bush-Mike Marshall'),
    ('Vishwa Mohan Bhatt With Bela Fleck and Jie Bing Chen',
     'Vishwa Mohan Bhatt With Bela Fleck and J',
     'Vishwa Mohan Bhatt With Bela Fleck and Jie Bing Chen'),
    ('The Beatles', 'TheBeatles-WhiteAbum-2009StereoRemaster', 'The Beatles'),
    ('Old & In the Way', 'Old & in the Way-Jerry Garcia-David Grisman',
     'Old & In the Way'),
]

# Album-level calls the conservative fold refused to make (A1-A6).
# canonical artist -> titles to drop from the merged list
ALBUM_DROPS = {
    # A1 — Wovenhand records already present under the Wovenhand entry.
    '16 Horsepower': ['blush_music', 'consider_the_birds'],
    # A3 — truncation matching two releases that are both present in full.
    'The Beat Junkies': ['The World Famous Beat Junkies, Vol. 2 Di'],
    # A4 — box-set title duplicating the three volumes.
    'The Magnetic Fields': ['69 Love Songs'],
    # A5 — combined entry duplicating the two disc entries.
    'Sigur Rós': ['Hvarf - Heim'],
}
# A6 — repair both White Album rips into one clean pair.
ALBUM_RENAMES = {
    'The Beatles': {
        'Disc 1': 'The Beatles [White Album] Disc 1',
        'Disc 2': 'The Beatles [White Album] Disc 2',
        'The Beatles Disc 1 (2009 Stere': 'The Beatles [White Album] Disc 1',
        'The Beatles Disc 2 (2009 Stere': 'The Beatles [White Album] Disc 2',
    },
}


def load(path):
    with open(path) as f:
        return json.load(f, object_pairs_hook=collections.OrderedDict)


def dump(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write('\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    inv_doc = load(INVENTORY)
    artists = inv_doc['artists']
    credits_doc = load(CREDITS)
    credits = credits_doc['artists']
    follows_doc = load(FOLLOWS)
    follows = follows_doc['artists']

    missing = [k for a, b, _ in MERGES for k in (a, b) if k not in artists]
    if missing:
        sys.exit(f'ABORT — not in inventory: {missing}')

    report = []
    for a, b, canon in MERGES:
        ra, rb = artists[a], artists[b]

        # --- albums: conservative fold, then the A-decisions --------------
        raw = (ra.get('albums') or []) + (rb.get('albums') or [])
        renames = ALBUM_RENAMES.get(canon, {})
        raw = [renames.get(t, t) for t in raw]
        groups, ambiguous = merge_albums(raw)
        titles = [best_title(v) for v in groups.values()]
        drops = set(ALBUM_DROPS.get(canon, []))
        kept = sorted({t for t in titles if t not in drops})
        dropped = sorted(t for t in titles if t in drops)

        # --- scalar fields: canonical wins, other fills gaps ---------------
        merged = collections.OrderedDict(ra)
        for k, v in rb.items():
            if k in ('albums', 'album_count', 'rotation'):
                continue
            if merged.get(k) in (None, '', [], {}):
                merged[k] = v
        merged['albums'] = kept
        merged['album_count'] = len(kept)

        # --- rewrite the artists map, preserving position -------------------
        rebuilt = collections.OrderedDict()
        for key, rec in artists.items():
            if key == b:
                continue                      # retired
            if key == a:
                rebuilt[canon] = merged       # canonical takes a's slot
            else:
                rebuilt[key] = rec
        artists = rebuilt

        # --- credits: union the album maps under the canonical key ---------
        cred_a = credits.pop(a, None)
        cred_b = credits.pop(b, None)
        if cred_a or cred_b:
            union = collections.OrderedDict()
            for src in (cred_a, cred_b):
                for al, rec in (src or {}).items():
                    al = renames.get(al, al)
                    if al in drops:
                        continue
                    if al not in union or rec.get('status') == 'verified':
                        union[al] = rec
            credits[canon] = union

        # --- follows: move provenance onto the canonical key ---------------
        for k in (a, b):
            if k in follows and k != canon:
                follows.setdefault(canon, follows[k])
                if k != canon:
                    follows.pop(k, None)

        report.append((a, b, canon, len(raw), len(kept), dropped, ambiguous))

    # --- credits back-references ------------------------------------------
    remap = {}
    for a, b, canon in MERGES:
        for k in (a, b):
            if k != canon:
                remap[k] = canon
    n_cm = 0
    for _art, albums in credits.items():
        for _al, rec in albums.items():
            for p in rec.get('personnel', []):
                cm = p.get('collection_match')
                if cm in remap:
                    p['collection_match'] = remap[cm]
                    n_cm += 1

    inv_doc['artists'] = artists
    meta = inv_doc['meta']
    live = [r for r in artists.values() if not r.get('discard')]
    meta['total_unique_artists'] = len(artists)
    meta['total_albums'] = sum(len(r.get('albums') or []) for r in artists.values())
    tagged = sum(1 for r in artists.values() if r.get('tagged'))
    meta['tagged_artists'] = tagged
    meta['untagged_artists'] = len(artists) - tagged

    w = max(len(c) for *_, c, _, _, _, _ in [(0, 0, m[2], 0, 0, 0, 0) for m in report])
    for a, b, canon, nraw, nkept, dropped, amb in report:
        retired = b if canon == a else (a if canon == b else f'{a} + {b}')
        print(f'{canon}')
        print(f'    retires: {retired!r}')
        print(f'    albums:  {nraw} raw → {nkept} kept'
              + (f'   dropped {dropped}' if dropped else ''))
        for k, l in amb:
            print(f'    note: unresolvable truncation matched {len(l)} releases')
    print()
    print(f'artists: {len(artists)}  (was {len(artists) + len(MERGES)})')
    print(f'total_albums: {meta["total_albums"]}')
    print(f'collection_match references remapped: {n_cm}')
    print(f'tagged {tagged} / untagged {len(artists) - tagged} / live {len(live)}')

    if args.dry_run:
        print('\n--dry-run: nothing written')
        return
    dump(INVENTORY, inv_doc)
    dump(CREDITS, credits_doc)
    dump(FOLLOWS, follows_doc)
    print('\nwrote inventory, credits, follows.'
          '  Run streaming_merge.py next to re-derive rotation.')


if __name__ == '__main__':
    main()
