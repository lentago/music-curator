#!/usr/bin/env python3
"""Repair rip damage in album titles across the inventory and credits.

The library was ripped by tooling that truncated titles at exactly 40
characters, substituted the characters Windows forbids in filenames, and
sometimes wrote a folder name in place of a title.

Album titles are the join key for credits.json, so every rename and drop is
mirrored there — otherwise the personnel research detaches from the albums it
describes.

    python repair_titles.py --dry-run
    python repair_titles.py
"""
import argparse
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dedup_lib import album_key  # noqa: E402

INVENTORY = os.path.join(HERE, 'data', 'music-inventory.json')
CREDITS = os.path.join(HERE, 'data', 'credits.json')

# S1 — entries that are not records.
JUNK = re.compile(r'\.txt$|^Unknown Album|^Amazon MP3$', re.I)

# S3 — deliberate stylizations that title-casing must not flatten.
STYLIZED = {
    'emotive': 'eMOTIVe',
    'clouddead': 'cLOUDDEAD',
    'cn_tower_mp3': 'CN Tower',
    'the_dark_side_of_the_moon_(sacd)': 'The Dark Side of the Moon (SACD)',
    "we_ain't_fessin'_(double_quotes)": "We Ain't Fessin' (Double Quotes)",
    'ritual_de_lo_habitual': 'Ritual de lo Habitual',
}
# Words that stay lowercase inside a title.
SMALL = {'a', 'an', 'and', 'as', 'at', 'but', 'by', 'de', 'for', 'from', 'in',
         'lo', 'nor', 'of', 'on', 'or', 'the', 'to', 'with'}

# Explicit reconstructions decided on the worksheet.
RECONSTRUCT = {
    ('Explosions In The Sky', 'Those Who Tell the Truth Shall Die, Thos'):
        'Those Who Tell the Truth Shall Die, Those Who Tell the Truth Shall '
        'Live Forever',
    ('Mew', "No More Stories Are Told Today I'm Sorry"):
        "No More Stories Are Told Today, I'm Sorry They Washed Away // No More "
        "Stories, The World Is Grey, I'm Tired, Let's Wash Away",
    ('Ray Charles', 'Modern Sounds in Country and Western Mus'): None,
    ('Ray Charles', 'Modern SoundsIn Country And Western Music, Vols 1 & 2'):
        'Modern Sounds in Country and Western Music, Vols 1 & 2',
    ('The Neville Brothers', "Uptown Rulin'_ The Best of the Neville B"):
        "Uptown Rulin': The Best of the Neville Brothers",
    ('The Pogues', 'If I Should Fall From Grace With God [Ex'):
        'If I Should Fall From Grace With God [Expanded]',
    ('The Smithereens', 'From Jersey It Came! The Smithereens Ant'):
        'From Jersey It Came! The Smithereens Anthology',
    ('James Brown', 'The CD Of JB (Sex Machine & Other Soul C'):
        'The CD Of JB (Sex Machine & Other Soul Classics)',
    ('John Zorn', 'Astaroth_ Book Of Angels Volume One - Ja'):
        'Astaroth: Book Of Angels Volume One - Jamie Saft Trio',
    ('Cracow Klezmer Band', 'Masada Book II - The Book Of Angels - Vo'):
        'Masada Book II - The Book Of Angels - Vol. 5: Balan',
    ('Imogen Heap', 'Various Artists - New Dawn (Class of 94}'):
        'Various Artists - New Dawn (Class of 94)',
    ('Metric', 'Old World Underground, Where Are You Now'):
        'Old World Underground, Where Are You Now?',
    # The underscore here stands in for a question mark, not a colon, so the
    # automatic S4 rule would produce "Picture: - The Essential".
    ('Billy Bragg', 'Must I Paint You a Picture_ - The Essential Billy Bragg'):
        'Must I Paint You a Picture? The Essential Billy Bragg',
    ('Beth Orton', 'Pass in Time - The Definitive Collection'):
        'Pass in Time: The Definitive Collection',
    ("Warren Zevon - I'll Sleep When I'm Dead (An Anthology)", 'Disc 1'):
        "I'll Sleep When I'm Dead (An Anthology) Disc 1",
    ("Warren Zevon - I'll Sleep When I'm Dead (An Anthology)", 'Disc 2'):
        "I'll Sleep When I'm Dead (An Anthology) Disc 2",
}
# Explicitly left alone (false positives and one unrecoverable title).
LEAVE = {
    ('Paul Simon', 'The Rhythm Of The Saints (2011 Remaster)'),
    ('Ray Charles', 'Ray - Original Motion Picture Soundtrack'),
    ('David Grisman Quintet', '1'),
}

FILENAME_STYLE = re.compile(r"^[a-z0-9][a-z0-9_'\-\.\(\)]*$")

# A longer title that merely adds a disc or edition marker is a DIFFERENT
# release, not the same one spelled out. Without this, "Song Review: A Greatest
# Hits Collection" gets swallowed by "... Disc 2" and disc 1 disappears.
DISC_MARKER = re.compile(r'^(disc|cd|extras?|bonus|vol)\b', re.I)


def title_case(raw):
    """S3 — turn a filename-style title back into a title."""
    text = raw.replace('_', ' ')
    text = re.sub(r'\s+', ' ', text).strip()
    words = text.split(' ')
    out = []
    for i, w in enumerate(words):
        core = w.strip('()[]')
        low = core.lower()
        if i not in (0, len(words) - 1) and low in SMALL:
            out.append(w.lower())
        elif any(c.isupper() for c in w):
            out.append(w)          # already stylized, leave it
        else:
            # capitalise the first LETTER, not the first character — otherwise
            # a leading bracket absorbs it and "(remaster)" stays lowercase
            m = re.search(r'[a-z]', w)
            out.append(w[:m.start()] + w[m.start()].upper() + w[m.start() + 1:]
                       if m else w)
    return ' '.join(out)


def restore_punctuation(t):
    """S4 — only the unambiguous case: '_ ' stood in for a stripped colon.

    Requires exactly one underscore in the whole title, immediately followed by
    a space and not preceded by one. Titles with several underscores are using
    the substitution for something else — "L_A_ Forum (Live_ 1975)" wants
    periods, and " _ " between clauses is standing in for a slash or dash — and
    a title where "_ " is followed by " - " is usually a stripped question mark
    rather than a colon.
    """
    if t.count('_') != 1:
        return t
    i = t.index('_')
    if i == 0 or t[i - 1] == ' ':
        return t
    if not t[i + 1:].startswith(' ') or t[i + 1:].startswith(' - '):
        return t
    return t[:i] + ':' + t[i + 1:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    with open(INVENTORY) as f:
        inv_doc = json.load(f, object_pairs_hook=collections.OrderedDict)
    with open(CREDITS) as f:
        cred_doc = json.load(f, object_pairs_hook=collections.OrderedDict)
    artists = inv_doc['artists']
    credits = cred_doc['artists']

    # artist -> {old_title: new_title or None(drop)}
    plan = collections.defaultdict(dict)
    stats = collections.Counter()
    untouched_underscore = []

    for name, rec in artists.items():
        if rec.get('discard'):
            continue
        albums = list(rec.get('albums') or [])
        keys = {t: album_key(t) for t in albums}

        for t in albums:
            if (name, t) in LEAVE:
                continue
            if (name, t) in RECONSTRUCT:
                plan[name][t] = RECONSTRUCT[(name, t)]
                stats['reconstruct' if RECONSTRUCT[(name, t)] else 'recon-drop'] += 1
                continue
            if JUNK.search(t):                                    # S1
                plan[name][t] = None
                stats['junk'] += 1
                continue
            if len(t) == 40:                                      # S2
                sib = [u for u in albums if u != t
                       and keys[u].startswith(keys[t])]
                if sib:
                    plan[name][t] = None
                    stats['trunc-dupe'] += 1
                    continue
            if FILENAME_STYLE.match(t) and ('_' in t or t.islower()):  # S3
                new = STYLIZED.get(t) or title_case(t)
                if new != t:
                    plan[name][t] = new
                    stats['title-case'] += 1
                continue
            if '_ ' in t:                                         # S4
                new = restore_punctuation(t)
                if new != t:
                    plan[name][t] = new
                    stats['punctuation'] += 1
                continue
            if '_' in t:
                untouched_underscore.append((name, t))

    # --- apply to the inventory, then re-dedup within each artist ----------
    # Titles the emergent pass collapses are keyed on their POST-rename form,
    # so credits needs them separately from `plan` or it keeps entries whose
    # album no longer exists.
    emergent = []
    emergent_drop = collections.defaultdict(set)
    for name, mapping in plan.items():
        rec = artists[name]
        out = []
        for t in (rec.get('albums') or []):
            new = mapping.get(t, t)
            if new is not None:
                out.append(new)
        # renames can make one title a duplicate (or prefix) of another
        seen = {}
        for t in out:
            seen.setdefault(album_key(t), []).append(t)
        final = []
        for k in sorted(seen, key=len):
            group = seen[k]
            longer = [m for m in seen if m != k and m.startswith(k)
                      and len(k) >= 15 and not DISC_MARKER.match(m[len(k):].strip())]
            if longer:
                emergent.append((name, group[0], seen[longer[0]][0]))
                emergent_drop[name].update(group)
                continue
            final.append(max(group, key=len))
            if len(group) > 1:
                emergent.append((name, group[1], group[0]))
                keep = max(group, key=len)
                emergent_drop[name].update(g for g in group if g != keep)
        rec['albums'] = sorted(set(final))
        rec['album_count'] = len(rec['albums'])

    # --- S5: mirror renames and drops into credits.json --------------------
    n_cred = 0
    for name, mapping in plan.items():
        if name not in credits:
            continue
        albums = credits[name]
        rebuilt = collections.OrderedDict()
        for t, body in albums.items():
            new = mapping.get(t, t)
            if new is None or new in emergent_drop.get(name, ()):
                n_cred += 1
                continue
            if new != t:
                n_cred += 1
            if new not in rebuilt or body.get('status') == 'verified':
                rebuilt[new] = body
        credits[name] = rebuilt

    meta = inv_doc['meta']
    meta['total_albums'] = sum(len(r.get('albums') or [])
                               for r in artists.values())
    # Follows and person nodes legitimately own nothing; an artist that had
    # albums and now has none is the case worth surfacing.
    empties = [n for n, r in artists.items()
               if not r.get('discard') and not (r.get('albums') or [])
               and 'Person node' not in (r.get('note') or '')
               and r.get('source') != 'spotify-follow']

    for k in ('junk', 'trunc-dupe', 'title-case', 'punctuation',
              'reconstruct', 'recon-drop'):
        print(f'  {k:14} {stats[k]}')
    print(f'\ntotal title changes: {sum(stats.values())}')
    print(f'credits.json keys renamed or dropped: {n_cred}')
    print(f'total_albums: {meta["total_albums"]}')
    if emergent:
        print(f'\nemergent duplicates collapsed after repair ({len(emergent)}):')
        for n, dropped, kept in emergent:
            print(f'  {n[:26]:26} dropped {dropped!r}  (kept {kept!r})')
    if untouched_underscore:
        print(f'\nunderscores left alone as ambiguous ({len(untouched_underscore)}):')
        for n, t in untouched_underscore[:10]:
            print(f'  {n[:26]:26} | {t}')
        if len(untouched_underscore) > 10:
            print(f'  … +{len(untouched_underscore) - 10} more')
    if empties:
        print(f'\n!! artists left with zero albums: {empties}')

    if args.dry_run:
        print('\n--dry-run: nothing written')
        return
    with open(INVENTORY, 'w') as f:
        json.dump(inv_doc, f, indent=2, ensure_ascii=False)
        f.write('\n')
    with open(CREDITS, 'w') as f:
        json.dump(cred_doc, f, indent=2, ensure_ascii=False)
        f.write('\n')
    print('\nwrote inventory and credits.')


if __name__ == '__main__':
    main()
