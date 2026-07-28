#!/usr/bin/env python3
"""Shared primitives for the name-variant merge pass (issue #42).

Kept separate from curator_lib because this is album-title normalisation, not
the artist-key `alnum()` that every joining tool uses.
"""
import re
import unicodedata

# Letters that are not decomposable diacritics — NFKD leaves them intact and
# an ASCII fold would drop them entirely, silently splitting "Með Suð" from
# "Med sud".
LETTER_FOLD = {'ð': 'd', 'Ð': 'd', 'þ': 'th', 'Þ': 'th', 'æ': 'ae',
               'Æ': 'ae', 'ø': 'o', 'Ø': 'o', 'ß': 'ss', 'ł': 'l', 'Ł': 'l'}

# Titles below this length are never treated as truncations of a longer title —
# "Disc 1" must not absorb "Disc 1 (2009 Stereo Remaster)".
MIN_TRUNCATION_LEN = 15


def album_key(title):
    """Normalise an album title for equality comparison.

    Deliberately conservative: case, accents, underscores and punctuation are
    folded, but disc numbers, bracketed editions and parenthetical suffixes are
    preserved. Stripping those merges genuinely distinct releases — three discs
    of one Dick's Picks volume, or Low Estate against Low Estate (Nouvelle).
    """
    t = ''.join(LETTER_FOLD.get(c, c) for c in title)
    t = unicodedata.normalize('NFKD', t)
    t = ''.join(c for c in t if not unicodedata.combining(c))
    t = t.lower().replace('_', ' ')
    t = re.sub(r'[^a-z0-9]+', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def merge_albums(titles):
    """Group titles that are the same release.

    Returns (groups, ambiguous) where groups maps a display title to the raw
    titles folded into it, and ambiguous lists truncated titles that prefix
    more than one longer title and so cannot be resolved automatically.
    """
    exact = {}
    for t in titles:
        exact.setdefault(album_key(t), []).append(t)

    keys = list(exact)
    # Resolve the prefix relation over every key up front. A truncated title
    # that extends into exactly one longer title is that title; one that could
    # be any of several is unresolvable and must not be folded into whichever
    # happens to sort first.
    absorb, ambiguous = {}, []
    for k in keys:
        if len(k) < MIN_TRUNCATION_LEN:
            continue
        longer = [m for m in keys if m != k and m.startswith(k)]
        if len(longer) == 1:
            absorb[k] = longer[0]
        elif len(longer) > 1:
            ambiguous.append((k, sorted(longer)))

    # follow absorb chains to a terminal title
    def resolve(k, seen=None):
        seen = seen or set()
        while k in absorb and k not in seen:
            seen.add(k)
            k = absorb[k]
        return k

    groups = {}
    for k, raw in exact.items():
        groups.setdefault(resolve(k), []).extend(raw)

    display = {}
    for k, raw in groups.items():
        display[best_title(raw)] = raw
    return display, ambiguous


def best_title(titles):
    """Pick the display title for a group of rips of the same release.

    Longest wins, because a truncated folder name is always the worse record.
    On a tie — which is the common case for pure case variants — prefer the
    one that reads like a title rather than a filename: no underscores, and
    more capitalisation. Without this, 'folklore' beats 'Folklore' purely on
    dict order.
    """
    return max(titles, key=lambda t: (len(t), '_' not in t,
                                      sum(c.isupper() for c in t)))
