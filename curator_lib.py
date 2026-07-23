#!/usr/bin/env python3
"""Shared primitives for the music-curator tools.

The artist-name normalization below is the Phase 2 dedup key, and it is the
single most load-bearing function in the repo: every layer that joins to the
inventory -- streaming history, discography harvests, Spotify follows -- reaches
the right artist record through it, or silently creates a duplicate. It lived as
three copies before this module; the third would have been the one that drifted.

Stdlib only, like every other tool here.
"""

import re
import unicodedata
import urllib.parse

__all__ = ["alnum", "index_by_alnum", "collisions_by_alnum"]


def alnum(name):
    """Punctuation- and accent-insensitive key for an artist or title.

    Percent-decodes (rip directories are sometimes URL-escaped), folds
    underscores to spaces, strips accents, then keeps only [a-z0-9].

    The accent fold is why this is not simply `re.sub(r"[^a-z0-9]", "", s)`:
    that expression *deletes* non-ASCII letters rather than folding them, so
    "Bela Fleck" keys to "belafleck" while "Béla Fleck" keys to "blafleck" and
    the two never meet. Spotify returns properly accented names and the
    inventory carries a dozen accented keys, so without the NFKD pass an
    accented artist can be ingested a second time alongside the copy already
    there -- which is exactly the failure an automatic ingest must not have.

        >>> alnum("Béla Fleck") == alnum("Bela Fleck")
        True
        >>> alnum("Sigur Rós") == alnum("Sigur Ros")
        True
    """
    s = urllib.parse.unquote(name).replace("_", " ").lower()
    s = "".join(c for c in unicodedata.normalize("NFKD", s)
                if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", s)


def index_by_alnum(names, aliases=None):
    """Map alnum key -> canonical name, for joining a foreign layer to the roster.

    `aliases` is an optional {alnum key: name} overlay for drift the key cannot
    bridge on its own (rebrands, "&" vs "and" splits, romanizations).

    When two names share a key the FIRST wins, so the mapping is independent of
    dict ordering; use collisions_by_alnum() to surface such pairs rather than
    letting one quietly shadow the other.
    """
    index = {}
    for name in names:
        index.setdefault(alnum(name), name)
    if aliases:
        index.update(aliases)
    return index


def collisions_by_alnum(names):
    """Group names that share a normalization key: {key: [name, ...]}.

    A collision means the roster holds the same artist twice under different
    spellings. Callers surface these rather than merging them -- deciding which
    spelling is canonical, and which record keeps the albums, is a curation
    call, not something a normalizer should make.
    """
    buckets = {}
    for name in names:
        buckets.setdefault(alnum(name), []).append(name)
    return {key: group for key, group in buckets.items() if len(group) > 1}
