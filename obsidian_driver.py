#!/usr/bin/env python3
"""
Render a music-inventory JSON file into an Obsidian vault whose graph view
clusters artists in a two-tier category tree.

Each active artist becomes a note that wikilinks to exactly one hub: its
subcategory hub where it has one (Hip-Hop › Underground), else its top-level
category hub. Subcategory hubs link up to their category, so the graph is a
strict tree over ~13 top-level genres, and every node in a tree is tagged with
its top-level category so the whole cluster shares one color. Untagged artists
hang off a single Reservoir hub, and the whole thing opens in Obsidian with a
pre-styled, category-colored graph and no plugins required. No artist is
pre-designated as more important than another — Obsidian sizes nodes by
degree, so the real hubs surface from the connectivity.

Usage:
    python obsidian_driver.py [path/to/music-inventory.json] [--out DIR]

    # defaults: reads data/music-inventory.json, writes vault/
    python obsidian_driver.py
    python obsidian_driver.py --out /tmp/my-vault --include-discarded
    python obsidian_driver.py --graph artist-web   # open on the artist↔artist web
    python obsidian_driver.py --graph rotation     # recolor by what's still played
    python obsidian_driver.py --graph source-follow  # highlight the Spotify follow set

The output directory is treated as fully generated: it is wiped and rebuilt on
every run (guarded by a marker file so it will not clobber a directory it did
not create). Discarded artists are dropped by default — pass
--include-discarded to keep them (tagged #discarded so you can filter them in
graph view).

Dependencies: none (Python 3.8+ standard library only).
"""

import argparse
import json
import os
import re
import shutil
import sys

from curator_lib import alnum

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_INVENTORY = os.path.join(HERE, "data", "music-inventory.json")
DEFAULT_CREDITS = os.path.join(HERE, "data", "credits.json")
DEFAULT_DISCOGRAPHIES = os.path.join(HERE, "data", "discographies.json")
DEFAULT_STREAMING = os.path.join(HERE, "data", "streaming-summary.json")
DEFAULT_FOLLOWS = os.path.join(HERE, "data", "follows.json")
DEFAULT_OUT = os.path.join(HERE, "vault")

# The tag the `source-follow` graph preset colors on. Carried by any artist
# currently followed on Spotify (owned or seeded), so the preset lights up the
# whole follow set over the taste map, independent of the category coloring.
SOURCE_FOLLOW_TAG = "source-follow"
SOURCE_FOLLOW_COLOR = (0.83, 0.62, 0.60)   # magenta-pink, distinct from the rotation ramp

# Written to the output dir so a later run knows the dir is ours to wipe.
MARKER = ".generated-by-music-curator"

# Characters that are illegal in filenames on common OSes or that break
# Obsidian wikilink resolution (#, ^, [, ], |, and path separators).
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f#^\[\]]')

RESERVOIR_HUB = "Reservoir"
HOME_MOC = "Music Collection"
ABOUT_NOTE = "About this vault"
ROTATION_MOC = "Rotation"

# The rotation classes streaming_merge.py writes onto the inventory, in the
# order they read as a decay curve: still playing → played, not lately → owned
# but not streamed. Each carries a graph color for the `rotation` preset.
ROTATION_CLASSES = ("current", "dormant", "historical")
ROTATION_COLORS = {
    "current": (0.33, 0.55, 0.55),      # green — in the last 18 months
    "dormant": (0.12, 0.70, 0.58),      # amber — played, but not lately
    "historical": (0.60, 0.25, 0.58),   # slate blue — shelf-only
}
ROTATION_BLURB = {
    "current": "still in play",
    "dormant": "played, but not lately",
    # Deliberately makes no claim about the shelf: person nodes carry a
    # rotation class too, and they own no albums.
    "historical": "effectively absent from the stream",
}


def load_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid JSON in {path}: {exc}", file=sys.stderr)
        sys.exit(1)


def slugify(name):
    """Filesystem- and wikilink-safe basename derived from a display name."""
    s = _ILLEGAL.sub(" ", name)
    s = re.sub(r"\s+", " ", s).strip().strip(".")
    return s or "untitled"


class BasenameAllocator:
    """Hands out globally-unique note basenames.

    Obsidian resolves ``[[Foo]]`` by basename across the whole vault, so two
    notes in different folders that share a basename are ambiguous. This keeps
    every basename unique, disambiguating rare collisions with a ``(2)`` suffix.
    """

    def __init__(self):
        self._used = set()

    def take(self, name):
        base = slugify(name)
        candidate, n = base, 2
        while candidate.lower() in self._used:
            candidate = f"{base} ({n})"
            n += 1
        self._used.add(candidate.lower())
        return candidate


def category_slug(name):
    """A #tag-safe slug for a category name, used to color its cluster.

    `Soul, Funk & R&B` -> `soul-funk-r-b`; `Trip-Hop & Downtempo` ->
    `trip-hop-downtempo`. Obsidian tags allow only letters, digits, and hyphens.
    """
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def prettify_album(name):
    """Gentle read-friendly cleanup of slug-style folder names."""
    return re.sub(r"\s+", " ", name.replace("_", " ")).strip()


# Delimiters inside an artist key that suggest a collaboration of separately
# collected artists. Constituents are only linked when they exactly match an
# existing artist node, so over-splitting a canonical group (Hall & Oates,
# Earth Wind & Fire) is harmless — it simply yields no edges.
_COLLAB_SPLIT = re.compile(
    r"\s*(?:&|\+|/|,|;|\bx\b|\band\b|\bwith\b|\bfeat\.?\b|\bfeaturing\b|\bvs\.?\b)\s*"
    r"|(?<=\S)-(?=\S)",
    re.I,
)


def parse_collaborators(name, lookup):
    """Constituent artist nodes named inside a collaboration key.

    `lookup` maps a lowercased artist name to its canonical form. Returns the
    canonical names of constituents that are themselves nodes (excluding `name`
    itself), preserving order and dropping duplicates.

    Only names that actually contain a separator are treated as collaborations,
    so a lone `The Grateful Dead` is never linked to a separate `Grateful Dead`
    node — that is a near-duplicate key (validate.py's job), not a collaboration.
    """
    raw_parts = [p for p in _COLLAB_SPLIT.split(name) if p and p.strip()]
    if len(raw_parts) < 2:
        return []
    found = []
    for raw in raw_parts:
        part = re.sub(r"\(.*?\)", "", raw).strip().strip(".")
        if not part:
            continue
        for cand in (part, re.sub(r"^the\s+", "", part, flags=re.I)):
            canonical = lookup.get(cand.lower())
            if canonical and canonical != name and canonical not in found:
                found.append(canonical)
    return found


def build_personnel_edges(credits, active_set):
    """Undirected roster-only personnel edges from the credits research layer.

    For each album, every credited person flagged `in_collection` whose
    `collection_match` resolves to a roster artist becomes an edge between the
    album's artist and that person (both roster artists). Self-links are dropped.
    A `collection_match` that names several roster keys (a person matching more
    than one collaboration entry) is split and each valid key is linked.

    Returns {artist: set(linked roster artists)}.
    """
    edges = {}
    if not credits:
        return edges

    # Direct roster match by normalized name. This is self-healing: a personnel
    # name that matches a roster artist wires an edge even if the stored
    # `in_collection` flag is stale (written before that artist joined the
    # roster) -- which is exactly the case for artists seeded from a Spotify
    # follow. It complements, not replaces, the stored `collection_match`, which
    # still catches name drift the alnum key can't bridge (Nick Cave -> Nick
    # Cave & the Bad Seeds).
    active_alnum = {alnum(n): n for n in active_set}

    def resolve(match):
        if not match:
            return []
        if match in active_set:
            return [match]
        out = []
        for piece in re.split(r"\s*;\s*", match):
            piece = piece.strip()
            if piece in active_set:
                out.append(piece)
            else:
                for sub in re.split(r",\s*", piece):
                    sub = sub.strip()
                    if sub in active_set:
                        out.append(sub)
        return out

    for artist, albums in credits.get("artists", {}).items():
        if artist not in active_set:
            continue
        for _album, rec in albums.items():
            for person in rec.get("personnel", []):
                targets = set()
                if person.get("in_collection"):
                    targets.update(resolve(person.get("collection_match")))
                direct = active_alnum.get(alnum(person.get("name", "")))
                if direct:
                    targets.add(direct)
                for match in targets:
                    if match == artist or match not in active_set:
                        continue
                    edges.setdefault(artist, set()).add(match)
                    edges.setdefault(match, set()).add(artist)
    return edges


def yaml_scalar(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def yaml_list(items):
    return "[" + ", ".join(yaml_scalar(i) for i in items) + "]"


def frontmatter(fields):
    """Render an ordered list of (key, value) pairs as a YAML frontmatter block.

    Lists are emitted inline; None values are skipped.
    """
    lines = ["---"]
    for key, value in fields:
        if value is None:
            continue
        if isinstance(value, list):
            if not value:
                continue
            lines.append(f"{key}: {yaml_list(value)}")
        else:
            lines.append(f"{key}: {yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines)


def link(target, display=None):
    """A wikilink to `target` (a basename), optionally piped with a display."""
    if display is None or display == target:
        return f"[[{target}]]"
    disp = display.replace("|", " / ").replace("[", "(").replace("]", ")")
    if disp == target:
        return f"[[{target}]]"
    return f"[[{target}|{disp}]]"


def write_note(out_dir, subfolder, basename, body):
    folder = os.path.join(out_dir, subfolder) if subfolder else out_dir
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{basename}.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body.rstrip() + "\n")


def is_reservoir(record):
    """An artist with no category assigned is untagged exploration inventory."""
    return not record.get("category")


def prepare_output_dir(out_dir):
    """Wipe and recreate the output dir, refusing to touch a foreign directory."""
    if os.path.exists(out_dir):
        if not os.path.exists(os.path.join(out_dir, MARKER)) and os.listdir(out_dir):
            print(
                f"ERROR: {out_dir} exists, is non-empty, and was not generated by "
                f"this tool (no {MARKER} marker). Refusing to overwrite it.",
                file=sys.stderr,
            )
            sys.exit(1)
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)
    with open(os.path.join(out_dir, MARKER), "w", encoding="utf-8") as fh:
        fh.write("This directory is generated by obsidian_driver.py. Edits are overwritten.\n")


def discography_section(disco_record, artist, active, artist_base):
    """Markdown lines for an artist's seeded full-discography section.

    Recordings stay list items (like the owned Albums section — no per-album
    notes), grouped under the source page's own section headings. Owned
    recordings carry a ◆ marker; a recording credited to another roster
    artist wikilinks to it, which is what draws the project edge (Zorn →
    Naked City / Masada) in the graph.
    """
    recs = disco_record.get("recordings", [])
    owned = sum(1 for r in recs if r.get("owned"))
    lines = [
        f"## Discography ({len(recs)} recordings · {owned} in collection ◆)", "",
        f"*Seeded from the [full discography]({disco_record.get('source_page')}) — "
        "every known recording, owned or not.*", "",
    ]
    by_section = {}
    order = []
    for r in recs:
        sec = r.get("section") or "Recordings"
        if sec not in by_section:
            by_section[sec] = []
            order.append(sec)
        by_section[sec].append(r)
    for sec in order:
        lines.append(f"### {sec}")
        for r in by_section[sec]:
            item = f"- {r.get('title')}"
            if r.get("year"):
                item += f" ({r['year']})"
            credited = r.get("credited_to")
            roster = r.get("roster_link")
            if roster and roster != artist and roster in active:
                item += f" — {link(artist_base[roster], credited or roster)}"
            elif credited and credited != artist:
                item += f" — {credited}"
            if r.get("owned"):
                item += " ◆"
            lines.append(item)
        lines.append("")
    return lines


_SPARK = "▁▂▃▄▅▆▇█"


def streaming_index(streaming):
    """Split the streaming sidecar into owned-artist and stream-only lookups.

    Returns (by_inventory_key, stream_only) where stream_only holds the entries
    with no inventory match — artists in rotation that the collection has no
    roots in, which is the sidecar's most actionable finding.
    """
    entries = (streaming or {}).get("artists", [])
    by_key = {}
    stream_only = []
    for entry in entries:
        key = entry.get("inventory_key")
        if key:
            by_key[key] = entry
        else:
            stream_only.append(entry)
    stream_only.sort(key=lambda e: -e.get("recent_plays", 0))
    return by_key, stream_only


def sparkline(counts):
    """Render year->plays as `<year> <bar><count>` segments scaled to the peak."""
    if not counts:
        return None
    peak = max(counts.values()) or 1
    segments = []
    for year in sorted(counts):
        n = counts[year]
        idx = min(len(_SPARK) - 1, int(round((n / peak) * (len(_SPARK) - 1))))
        segments.append(f"{year} {_SPARK[idx]}{n:,}")
    return " · ".join(segments)


def rotation_lines(rotation, entry, months=18, floor=10):
    """The artist note's rotation block: the class, its evidence, and by-year.

    The class comes from the inventory (streaming_merge.py writes it); the
    numbers come from the sidecar. An artist can be classed without ever
    appearing in the export — that is exactly what `historical` means — so the
    evidence clause is optional. Below the sidecar's own play floor the by-year
    histogram is noise (every bar is full height at a peak of one), so it is
    drawn only once there is enough listening to shape it.
    """
    if not rotation:
        return []
    blurb = ROTATION_BLURB.get(rotation, "")
    if not entry:
        return [f"**Rotation:** {rotation} — never streamed.", ""]
    plays = entry.get("plays", 0)
    recent = entry.get("recent_plays", 0)
    hours = round(entry.get("minutes", 0) / 60)
    last = (entry.get("last_played") or "")[:10]
    if recent:
        evidence = (f"{recent:,} play{'' if recent == 1 else 's'} in the trailing "
                    f"{months} months ({plays:,} lifetime")
        evidence += f", {hours:,} h)" if hours else ")"
    else:
        evidence = f"{plays:,} lifetime play{'' if plays == 1 else 's'}, none recent"
    lines = [f"**Rotation:** {rotation} — {blurb}. {evidence}, last on {last}.", ""]
    bars = sparkline(entry.get("plays_by_year") or {}) if plays >= floor else None
    if bars:
        lines.extend([f"**By year:** {bars}", ""])
    return lines


def follows_index(follows):
    """Name -> follow record from the follows sidecar, excluding unfollowed
    artists. An unfollow is recorded for the audit trail but is not a current
    follow, so it neither carries the tag nor renders as followed."""
    return {name: rec for name, rec in (follows or {}).get("artists", {}).items()
            if not rec.get("unfollowed_at")}


def follow_line(rec, seed_tie_links):
    """The artist note's follow-provenance block.

    Three honest shapes, because the certainty differs. A backfilled follow has
    no real date or trigger song (the watcher wasn't running when it happened),
    so it is stated as an observation, not a claim. A live follow with the
    triggering artist caught in the moment names the song; without it, just the
    date. Seed ties -- co-artists on the trigger track who are in the collection
    -- are the earned edges that let a seeded artist wire into the graph.
    """
    when = (rec.get("followed_at") or "")[:10]
    lines = []
    if rec.get("backfill"):
        lines.append(f"**Followed:** on Spotify — backfilled, observed as of "
                     f"{when} (original follow date and trigger song unknown).")
    else:
        trigger = rec.get("trigger_track") if rec.get("trigger_confidence") == "high" else None
        if trigger and trigger.get("track"):
            by = ", ".join(trigger.get("artists") or []) or "unknown"
            lines.append(f"**Followed:** {when} on Spotify, while playing "
                         f"*{trigger['track']}* — {by} (the likely trigger).")
        else:
            lines.append(f"**Followed:** {when} on Spotify.")
    lines.append("")
    if seed_tie_links:
        lines.append("**Seeded via:** " + " · ".join(seed_tie_links))
        lines.append("")
    return lines


def build_vault(inventory, out_dir, include_discarded=False, credits=None,
                discographies=None, streaming=None, follows=None, graph="default"):
    artists = inventory.get("artists", {})
    meta = inventory.get("meta", {})

    # Select the artists that become notes.
    active = {}
    for name, rec in sorted(artists.items(), key=lambda kv: kv[0].lower()):
        if rec.get("discard") and not include_discarded:
            continue
        active[name] = rec

    # Case-insensitive lookup used to resolve collaboration constituents.
    name_lookup = {name.lower(): name for name in active}

    # Roster-only personnel edges from the credits research layer.
    personnel_edges = build_personnel_edges(credits, set(active))

    # Streaming aggregates keyed by inventory name, plus the artists in
    # rotation the collection has no roots in.
    stream_by_key, stream_only = streaming_index(streaming)
    rotation_members = {cls: [] for cls in ROTATION_CLASSES}
    stream_meta = (streaming or {}).get("meta", {})
    recent_months = stream_meta.get("recent_months", 18)
    play_floor = stream_meta.get("floor_plays", 10)

    # Current Spotify follows (unfollowed artists excluded). Seed ties recorded
    # in the sidecar are resolved to nodes here, so a live follow's trigger song
    # becomes real artist->artist edges.
    follow_by_name = follows_index(follows)
    follow_members = []

    # Collect the two-tier hub structure and its members.
    category_members = {}   # category -> [artists filed directly under it, no subcategory]
    sub_members = {}        # (category, subcategory) -> [artist names]
    reservoir_members = []
    collab_map = {}         # artist name -> [constituent artist names that are nodes]

    for name, rec in active.items():
        cat = rec.get("category")
        sub = rec.get("subcategory")
        if cat and sub:
            sub_members.setdefault((cat, sub), []).append(name)
            category_members.setdefault(cat, [])
        elif cat:
            category_members.setdefault(cat, []).append(name)
        else:
            reservoir_members.append(name)
        constituents = parse_collaborators(name, name_lookup)
        if constituents:
            collab_map[name] = constituents

    # Allocate globally-unique basenames. Reserve the MOC names first so they
    # keep clean titles, then artists, then the category hubs.
    alloc = BasenameAllocator()
    fixed = {n: alloc.take(n)
             for n in (HOME_MOC, RESERVOIR_HUB, ABOUT_NOTE, ROTATION_MOC)}
    artist_base = {name: alloc.take(name) for name in active}
    cat_base = {cat: alloc.take(cat) for cat in sorted(category_members)}
    sub_base = {key: alloc.take(key[1]) for key in sorted(sub_members)}

    prepare_output_dir(out_dir)

    # --- Artist notes ---------------------------------------------------------
    for name, rec in active.items():
        cat = rec.get("category")
        tags = ["artist"]
        if rec.get("discard"):
            tags.append("discarded")
        if cat:
            tags.append(category_slug(cat))   # colors the artist with its cluster
        else:
            tags.append("reservoir")

        # A second, independent tag axis: the `rotation` graph preset colors on
        # these while the category tags stay untouched, so switching presets
        # re-reads the same graph through the listening lens.
        rotation = rec.get("rotation")
        stream_entry = stream_by_key.get(name)
        if rotation in rotation_members:
            tags.append(f"rotation-{rotation}")
            rotation_members[rotation].append(name)

        # Follow provenance is a third independent tag axis (category / rotation
        # / follow), so the `source-follow` preset lights up the follow set.
        follow_rec = follow_by_name.get(name)
        if follow_rec:
            tags.append(SOURCE_FOLLOW_TAG)
            follow_members.append(name)

        fm = frontmatter([
            ("aliases", [name] if artist_base[name] != name else None),
            ("type", "artist"),
            ("category", cat),
            ("subcategory", rec.get("subcategory")),
            ("era", rec.get("era")),
            ("rotation", rotation),
            ("plays", stream_entry.get("plays") if stream_entry else None),
            ("last_played", (stream_entry.get("last_played") or "")[:10]
                            if stream_entry else None),
            ("followed_at", (follow_rec.get("followed_at") or "")[:10]
                            if follow_rec else None),
            ("source", rec.get("source")),
            ("album_count", rec.get("album_count")),
            ("discarded", True if rec.get("discard") else None),
            ("collaborators", collab_map.get(name) or None),
            ("tags", tags),
        ])

        parts = [fm, "", f"# {name}", ""]

        # The artist's single edge into the taxonomy tree: its subcategory hub
        # when it has one (that hub links onward to its category), else its
        # category hub directly. The top-level name stays plain text in the
        # subcategory case so the graph keeps a strict two-tier tree.
        sub = rec.get("subcategory")
        if cat and sub:
            parts.append(f"**Category:** {cat} › {link(sub_base[(cat, sub)], sub)}")
        elif cat:
            parts.append(f"**Category:** {link(cat_base[cat], cat)}")
        else:
            parts.append(f"**Filed under:** {link(fixed[RESERVOIR_HUB])}")
        parts.append("")

        parts.extend(rotation_lines(rotation, stream_entry,
                                    months=recent_months, floor=play_floor))

        # Collaboration edges: direct artist-to-artist links parsed from the
        # combo key, drawn only to constituents that are themselves nodes.
        collaborators = collab_map.get(name, [])
        if collaborators:
            parts.append(
                "**With:** " + " · ".join(link(artist_base[c], c) for c in collaborators)
            )
            parts.append("")

        # Personnel edges: other roster artists who played on this artist's
        # albums (or on whose albums this artist played), from the credits layer.
        ties = [t for t in sorted(personnel_edges.get(name, ()), key=str.lower)
                if t not in set(collaborators)]
        if ties:
            parts.append(
                "**Session ties:** " + " · ".join(link(artist_base[t], t) for t in ties)
            )
            parts.append("")

        # Follow provenance + seed ties. Seed ties are the trigger track's
        # co-artists that are nodes and not already linked another way.
        if follow_rec:
            drawn = set(collaborators) | set(ties)
            seed_ties = [t for t in follow_rec.get("seed_ties", [])
                         if t in active and t != name and t not in drawn]
            seed_tie_links = [link(artist_base[t], t)
                              for t in sorted(seed_ties, key=str.lower)]
            parts.extend(follow_line(follow_rec, seed_tie_links))

        if rec.get("note"):
            parts.append(f"> {rec['note']}")
            parts.append("")
        if rec.get("discard") and rec.get("discard_reason"):
            parts.append(f"> **Discarded:** {rec['discard_reason']}")
            parts.append("")

        albums = rec.get("albums") or []
        if albums:
            parts.append(f"## Albums ({rec.get('album_count', len(albums))})")
            parts.extend(f"- {prettify_album(a)}" for a in albums)

        disco = (discographies or {}).get("artists", {}).get(name)
        if disco:
            if albums:
                parts.append("")
            parts.extend(discography_section(disco, name, active, artist_base))

        write_note(out_dir, "Artists", artist_base[name], "\n".join(parts))

    # --- Category + subcategory hub notes -------------------------------------
    subs_of = {}            # category -> [subcategory names, sorted]
    for cat, sub in sorted(sub_members):
        subs_of.setdefault(cat, []).append(sub)
    cat_total = {
        cat: len(category_members[cat])
        + sum(len(sub_members[(cat, s)]) for s in subs_of.get(cat, []))
        for cat in category_members
    }

    for cat in sorted(category_members):
        direct = category_members[cat]
        subs = subs_of.get(cat, [])
        fm = frontmatter([
            ("aliases", [cat] if cat_base[cat] != cat else None),
            ("type", "category"),
            ("member_count", cat_total[cat]),
            ("tags", ["category", category_slug(cat)]),
        ])
        body = [
            fm, "", f"# {cat}", "",
            f"*Category — {cat_total[cat]} artists in the collection.*", "",
        ]
        if subs:
            body.append("## Subcategories")
            body.extend(
                f"- {link(sub_base[(cat, s)], s)} ({len(sub_members[(cat, s)])})"
                for s in subs
            )
            body.append("")
        if direct:
            body.append("## Artists (no subcategory)" if subs else "## Artists")
            body.extend(
                f"- {link(artist_base[m], m)}" for m in sorted(direct, key=str.lower)
            )
        write_note(out_dir, "Categories", cat_base[cat], "\n".join(body))

    # Subcategory hubs: each links up to its category — that link is the
    # tree edge between the tiers — and carries the top-level slug tag so
    # it colors with its cluster. They live in Categories/<category>/ so the
    # file explorer mirrors the tree; links are basename-resolved, so the
    # nesting is purely cosmetic.
    for (cat, sub), members in sorted(sub_members.items()):
        fm = frontmatter([
            ("aliases", [sub] if sub_base[(cat, sub)] != sub else None),
            ("type", "subcategory"),
            ("category", cat),
            ("member_count", len(members)),
            ("tags", ["subcategory", category_slug(cat)]),
        ])
        body = [
            fm, "", f"# {sub}", "",
            f"*Subcategory of {link(cat_base[cat], cat)} — {len(members)} artists.*", "",
            "## Artists",
        ]
        body.extend(
            f"- {link(artist_base[m], m)}" for m in sorted(members, key=str.lower)
        )
        write_note(
            out_dir,
            os.path.join("Categories", cat_base[cat]),
            sub_base[(cat, sub)],
            "\n".join(body),
        )

    # --- Reservoir hub --------------------------------------------------------
    reservoir_body = [
        frontmatter([("type", "moc"), ("tags", ["moc", "reservoir"])]), "",
        f"# {RESERVOIR_HUB}", "",
    ]
    if reservoir_members:
        reservoir_body.extend([
            f"The untagged reservoir — {len(reservoir_members)} artists kept in "
            "the collection but not yet assigned a category. These are "
            "exploration inventory, not confident taste signal: mine them before "
            "reaching for external recommendations. Give one a category and it "
            "graduates into the graph proper.", "",
            "## Artists",
        ])
        reservoir_body.extend(
            f"- {link(artist_base[m], m)}"
            for m in sorted(reservoir_members, key=str.lower)
        )
    else:
        # The hub stays even when empty — the home MOC links to it, and the
        # reservoir refills whenever new artists are ingested untagged.
        reservoir_body.append(
            "**The reservoir is empty.** Every artist in the collection now "
            "carries a category, so there is no untagged exploration inventory "
            "left to mine. New artists land here whenever they are ingested "
            "without a category; tagging one graduates it into the graph proper."
        )
    write_note(out_dir, "", fixed[RESERVOIR_HUB], "\n".join(reservoir_body))

    # --- Rotation MOC ---------------------------------------------------------
    # Tagged #moc like the other meta notes, so the default graph filter hides
    # it and its several hundred links never distort the taxonomy tree.
    if streaming:
        smeta = streaming.get("meta", {})
        as_of = (smeta.get("newest_play") or "")[:10]
        floor = smeta.get("current_min_recent_plays", 10)
        months = smeta.get("recent_months", 18)
        in_rotation = [e for e in stream_only if e.get("recent_plays", 0) >= floor]
        dormant_anchors = []
        for name, rec in active.items():
            if rec.get("rotation") == "current":
                continue
            if not (rec.get("anchor") or (rec.get("album_count") or 0) >= 4):
                continue
            entry = stream_by_key.get(name)
            dormant_anchors.append((
                name,
                rec.get("album_count") or 0,
                rec.get("rotation") or "—",
                (entry.get("last_played") or "")[:10] if entry else "never",
            ))
        dormant_anchors.sort(key=lambda t: (-t[1], t[0].lower()))

        rot = [
            frontmatter([("type", "moc"), ("tags", ["moc", "rotation"])]), "",
            f"# {ROTATION_MOC}", "",
            "The **listening lens** over the collection. The shelf is a "
            "*historical* taste artifact; streaming shows what is *currently* in "
            "play, and the two do not fully overlap. Every artist carries a "
            "`rotation` class derived from the Spotify Extended Streaming "
            f"History export (as of **{as_of}**):", "",
            f"- **current** — {floor}+ plays in the trailing {months} months",
            f"- **dormant** — streamed at some point, but under that bar lately",
            "- **historical** — in the collection, effectively absent from the "
            "stream", "",
            "Open the **graph view** with the `rotation` preset to see these "
            "colors laid over the taste map — where a category cluster is all "
            "slate blue, the shelf has outlived the listening.", "",
            "## By the numbers", "",
        ]
        rot.extend(
            f"- **{len(rotation_members[cls])}** {cls} — {ROTATION_BLURB[cls]}"
            for cls in ROTATION_CLASSES
        )
        rot.extend([
            "",
            f"## Current ({len(rotation_members['current'])})", "",
            "Artists the collection has roots in that are still in play.", "",
        ])
        rot.extend(f"- {link(artist_base[m], m)}"
                   for m in sorted(rotation_members["current"], key=str.lower))
        rot.extend([
            "",
            f"## Dormant ({len(rotation_members['dormant'])})", "",
            "Streamed, but not lately — the re-entry candidates.", "",
        ])
        rot.extend(f"- {link(artist_base[m], m)}"
                   for m in sorted(rotation_members["dormant"], key=str.lower))
        rot.extend([
            "",
            f"## Historical ({len(rotation_members['historical'])})", "",
            "Owned but effectively unstreamed — too many to list; browse them "
            "with the `rotation` graph preset or the `#rotation-historical` tag.",
            "",
            f"## In rotation, no collection roots ({len(in_rotation)})", "",
            "Artists above the current-rotation bar that the collection has "
            "**no** albums by — the exploration worklist, and the sharpest "
            "signal the streaming layer produces. Not wikilinked: they are not "
            "in the collection, so they are not nodes.", "",
        ])
        shown = in_rotation[:40]
        rot.extend(f"- **{e['recent_plays']:,}** recent plays — {e['artist']}"
                   for e in shown)
        if len(in_rotation) > len(shown):
            rot.append(f"- *…and {len(in_rotation) - len(shown)} more below the "
                       f"top {len(shown)}.*")
        rot.extend([
            "",
            f"## Anchors off the rotation ({len(dormant_anchors)})", "",
            "Deep shelf presence, absent from current play — the other half of "
            "the gap. Sorted by shelf weight.", "",
            "| Artist | Albums | Rotation | Last streamed |",
            "|---|---:|---|---|",
        ])
        rot.extend(
            f"| {link(artist_base[n], n)} | {c} | {r} | {last} |"
            for n, c, r, last in dormant_anchors
        )
        write_note(out_dir, "", fixed[ROTATION_MOC], "\n".join(rot))

    # --- Home MOC -------------------------------------------------------------
    collab_edges = sum(len(v) for v in collab_map.values())
    personnel_edge_count = sum(len(v) for v in personnel_edges.values()) // 2
    disco_artists = [n for n in (discographies or {}).get("artists", {}) if n in active]
    disco_recordings = sum(
        len(discographies["artists"][n].get("recordings", [])) for n in disco_artists
    )
    by_size = sorted(cat_total.items(), key=lambda kv: (-kv[1], kv[0]))
    home = [
        frontmatter([("type", "moc"), ("tags", ["moc"])]), "",
        f"# {HOME_MOC}", "",
        "A taste map of the collection. Open the **graph view** (Ctrl/Cmd-G): "
        "every artist sits in one branch of a two-tier **category** tree, each "
        "top-level category is its own color, combo acts link straight to the "
        "members they share, and **session ties** wire artists together through "
        "shared personnel. Nothing is pre-weighted — the densest nodes are "
        "whatever the connectivity makes them.", "",
        "## By the numbers", "",
        f"- **{len(active)}** artists",
        f"- **{len(category_members)}** top-level categories · "
        f"**{len(sub_members)}** subcategories",
        f"- **{collab_edges}** collaboration edges · **{personnel_edge_count}** "
        "session-tie edges (shared personnel)",
        f"- **{len(reservoir_members)}** in the untagged {link(fixed[RESERVOIR_HUB])}",
    ] + ([
        "- " + " · ".join(f"**{len(rotation_members[c])}** {c}"
                          for c in ROTATION_CLASSES)
        + f" in {link(fixed[ROTATION_MOC])}",
    ] if streaming else []) + ([
        f"- **{disco_recordings}** recordings in seeded full discographies "
        "(" + ", ".join(link(artist_base[n], n)
                        for n in sorted(disco_artists, key=str.lower)) + ")",
    ] if disco_artists else []) + [
        "",
        "## Start here", "",
        f"- {link(fixed[RESERVOIR_HUB])} — exploration inventory",
    ] + ([
        f"- {link(fixed[ROTATION_MOC])} — what is actually still in play",
    ] if streaming else []) + [
        f"- {link(fixed[ABOUT_NOTE])} — how to read this vault",
        "",
        "## Categories", "",
    ]
    for cat, total in by_size:
        home.append(f"- {link(cat_base[cat], cat)} ({total})")
        home.extend(
            f"    - {link(sub_base[(cat, s)], s)} ({len(sub_members[(cat, s)])})"
            for s in subs_of.get(cat, [])
        )
    write_note(out_dir, "", fixed[HOME_MOC], "\n".join(home))

    # --- About note -----------------------------------------------------------
    about = [
        frontmatter([("type", "moc"), ("tags", ["moc"])]), "",
        f"# {ABOUT_NOTE}", "",
        "This vault is **generated** from `music-inventory.json` by "
        "`obsidian_driver.py` in the [music-curator]"
        "(https://github.com/lentago/music-curator) repo. Don't hand-edit the "
        "notes — regenerate instead; edits are overwritten.", "",
        "## Reading the graph", "",
        "- Every **artist** links to exactly one hub — its **subcategory** where "
        "it has one (Hip-Hop › Underground), else its top-level **category**. "
        "Subcategory hubs link up to their category, so the graph is a two-tier "
        "tree, and every node in a branch carries its top-level tag — each "
        "top-level category is a distinct color, so the clusters read at a "
        "glance.",
        "- **Combo acts link directly to their members** (`El-P & Cannibal Ox` "
        "→ El-P + Cannibal Ox), so the graph also shows the collaboration social "
        "graph, not just category membership. See a note's **With:** line.",
        "- **Session ties** link artists who share personnel — a musician who "
        "played on both their albums (Marc Ribot across Tom Waits and John Zorn; "
        "Jerry Douglas across the bluegrass records). Only roster artists become "
        "ties; see a note's **Session ties:** line. These edges cross category "
        "clusters and are the collection's hidden wiring.",
        "- Some artists carry a seeded **Discography** section — the *complete* "
        "known catalog harvested from a canonical source, not just the owned "
        "albums. ◆ marks recordings that are in the collection; recordings "
        "credited to another roster artist link to it, so a seeded artist's "
        "side-projects wire straight into the graph.",
        "- Most artists carry a **rotation** class — `current`, `dormant` or "
        "`historical` — merged in from the Spotify streaming history. It is a "
        "second, independent axis over the same graph: switch to the "
        "`rotation` graph preset to recolor every node by what is still in "
        f"play. {link(fixed[ROTATION_MOC])} collects the gaps in both "
        "directions — artists in rotation the collection has no roots in, and "
        "deep shelf anchors that have fallen out of play.",
        "- Artists you **follow** on Spotify carry a `followed_at` and a "
        "**Followed:** line naming the song that triggered the follow when it "
        "was caught live. A follow can *seed* a new artist into the reservoir, "
        "so the `source-follow` preset shows the whole follow set at once — "
        "connected follows in their clusters and freshly seeded ones as loose "
        "nodes waiting to be tagged.",
        "- No artist is singled out — node size follows degree, so importance "
        "emerges from the graph, not a prior.",
        "- The graph opens **filtered** (`-tag:#moc`, orphans hidden) so the meta "
        "notes (this one, Music Collection, Reservoir, Rotation) and the untagged "
        "reservoir don't clutter the taste map. Clear the filter and enable *Show "
        "orphans* to browse the whole collection, including the reservoir.", "",
        f"Start at {link(fixed[HOME_MOC])}.",
    ]
    write_note(out_dir, "", fixed[ABOUT_NOTE], "\n".join(about))

    # --- Pre-styled graph config + vault .gitignore --------------------------
    write_graph_config(out_dir, sorted(category_members), graph=graph)
    write_gitignore(out_dir)

    return {
        "artists": len(active),
        "categories": len(category_members),
        "subcategories": len(sub_members),
        "collab_edges": collab_edges,
        "personnel_edges": personnel_edge_count,
        "reservoir": len(reservoir_members),
        "discography_artists": len(disco_artists),
        "discography_recordings": disco_recordings,
        "rotation": {c: len(rotation_members[c]) for c in ROTATION_CLASSES},
        "stream_only": len(stream_only),
        "follows": len(follow_members),
        "meta_total": meta.get("total_unique_artists"),
    }


def _hsl_to_rgb_int(h, s, l):
    """HSL (each in [0, 1]) -> 0xRRGGBB integer, the form Obsidian graph.json wants."""
    def channel(n):
        k = (n + h * 12) % 12
        a = s * min(l, 1 - l)
        return l - a * max(-1, min(k - 3, 9 - k, 1))
    r, g, b = channel(0), channel(8), channel(4)
    return (round(r * 255) << 16) | (round(g * 255) << 8) | round(b * 255)


def category_palette(categories):
    """One well-separated color per category, as graph.json color groups.

    Hues are spaced by the golden ratio so adjacent categories stay visually
    distinct regardless of list order; each color group matches the category's
    slug tag, which is carried by both the hub and its artists so the whole
    cluster shares a color.
    """
    groups = []
    for i, cat in enumerate(categories):
        hue = (i * 0.6180339887) % 1.0
        rgb = _hsl_to_rgb_int(hue, 0.58, 0.60)
        groups.append({"query": f"tag:#{category_slug(cat)}", "color": {"a": 1, "rgb": rgb}})
    return groups


def graph_presets(categories):
    """Named graph.json configurations — a switchable library of graph filters.

    Every preset carries the same category color groups, so nodes always color
    by the artist's top-level category; presets differ only in which slice of
    the vault the search filter shows.

    default — the full taste map. The meta / navigation notes (Music
    Collection, About, Reservoir) are all tagged #moc, so `-tag:#moc` hides
    them while they remain in the vault for reading. With the Reservoir hub
    hidden, the untagged artists that only linked to it become orphans, so
    showOrphans is off — leaving a clean, connected map of artists clustered
    around their category hubs.

    artist-web — only the direct artist↔artist edges (collaborations and
    session ties). Restricting to the Artists folder removes every hub and
    with it the whole taxonomy tree; with orphans off, only artists that
    actually share an edge remain.

    rotation — the same taste map, recolored by listening rather than genre.
    This is the one preset that overrides the category palette: nodes color on
    the `rotation-*` tags instead, so a category cluster that has gone cold
    reads as a block of slate blue against the green of what is still in play.

    source-follow — highlights the Spotify follow set. Orphans are shown (unlike
    the others) because a freshly seeded follow has no category and no edges
    until it is tagged or its trigger song wires it, so it would otherwise be
    hidden -- and seeing those loose follows is the whole point of the preset.
    Followed artists carry the highlight color; everything else stays muted.
    """
    base = {
        "collapse-filter": True,
        "search": "-tag:#moc",
        "showTags": False,
        "showAttachments": False,
        "hideUnresolved": False,
        "showOrphans": False,
        "collapse-color-groups": False,
        "colorGroups": category_palette(categories),
        "collapse-display": False,
        "showArrow": False,
        "textFadeMultiplier": -0.5,
        "nodeSizeMultiplier": 1.1,
        "lineSizeMultiplier": 1,
        "collapse-forces": False,
        "centerStrength": 0.4,
        "repelStrength": 12,
        "linkStrength": 1,
        "linkDistance": 220,
        "scale": 0.5,
        "close": True,
    }
    artist_web = dict(base, search='path:"Artists"')
    rotation = dict(base, colorGroups=[
        {"query": f"tag:#rotation-{cls}",
         "color": {"a": 1, "rgb": _hsl_to_rgb_int(*ROTATION_COLORS[cls])}}
        for cls in ROTATION_CLASSES
    ])
    source_follow = dict(base, showOrphans=True, colorGroups=[
        {"query": f"tag:#{SOURCE_FOLLOW_TAG}",
         "color": {"a": 1, "rgb": _hsl_to_rgb_int(*SOURCE_FOLLOW_COLOR)}},
    ])
    return {"default": base, "artist-web": artist_web, "rotation": rotation,
            "source-follow": source_follow}


def write_graph_config(out_dir, categories, graph="default"):
    """Write the preset library and install the chosen preset as graph.json.

    All presets land in .obsidian/graph-presets/<name>.json; the active one is
    also written to .obsidian/graph.json, which is what Obsidian reads. Switch
    presets by re-running the driver with --graph <name> (or copying a preset
    file over graph.json); reopen the graph view to pick up the change.
    """
    presets = graph_presets(categories)
    preset_dir = os.path.join(out_dir, ".obsidian", "graph-presets")
    os.makedirs(preset_dir, exist_ok=True)
    for name, cfg in presets.items():
        with open(os.path.join(preset_dir, f"{name}.json"), "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
    with open(os.path.join(out_dir, ".obsidian", "graph.json"), "w", encoding="utf-8") as fh:
        json.dump(presets[graph], fh, indent=2)


def write_gitignore(out_dir):
    """Keep the generated graph config tracked; ignore Obsidian's runtime state.

    Opening the vault in Obsidian writes workspace.json, core-plugins.json, etc.
    into .obsidian/. This keeps those out of git while preserving graph.json.
    """
    body = (
        "# Obsidian runtime state — keep the generated graph config, ignore the rest.\n"
        ".obsidian/*\n"
        "!.obsidian/graph.json\n"
        "!.obsidian/graph-presets\n"
    )
    with open(os.path.join(out_dir, ".gitignore"), "w", encoding="utf-8") as fh:
        fh.write(body)


def main():
    parser = argparse.ArgumentParser(description="Render music-inventory.json into an Obsidian vault.")
    parser.add_argument("inventory", nargs="?", default=DEFAULT_INVENTORY,
                        help="path to music-inventory.json")
    parser.add_argument("--out", default=DEFAULT_OUT, help="output vault directory")
    parser.add_argument("--include-discarded", action="store_true",
                        help="keep discarded artists (tagged #discarded)")
    parser.add_argument("--credits", default=DEFAULT_CREDITS,
                        help="path to credits.json (personnel research layer); optional")
    parser.add_argument("--discographies", default=DEFAULT_DISCOGRAPHIES,
                        help="path to discographies.json (seeded full-discography layer); optional")
    parser.add_argument("--streaming", default=DEFAULT_STREAMING,
                        help="path to streaming-summary.json (rotation layer); optional")
    parser.add_argument("--follows", default=DEFAULT_FOLLOWS,
                        help="path to follows.json (Spotify follow provenance); optional")
    parser.add_argument("--graph", default="default", choices=sorted(graph_presets([])),
                        help="graph preset installed as the active graph.json")
    args = parser.parse_args()

    inventory = load_json(args.inventory)
    credits = load_json(args.credits) if os.path.exists(args.credits) else None
    discographies = (load_json(args.discographies)
                     if os.path.exists(args.discographies) else None)
    streaming = load_json(args.streaming) if os.path.exists(args.streaming) else None
    follows = load_json(args.follows) if os.path.exists(args.follows) else None
    stats = build_vault(inventory, args.out, include_discarded=args.include_discarded,
                        credits=credits, discographies=discographies,
                        streaming=streaming, follows=follows, graph=args.graph)

    print(f"Wrote vault to: {args.out}")
    print(f"  artists:    {stats['artists']}")
    print(f"  categories: {stats['categories']}  subcategories: {stats['subcategories']}")
    print(f"  collab edges: {stats['collab_edges']}  personnel edges: {stats['personnel_edges']}")
    print(f"  reservoir:  {stats['reservoir']}")
    if stats["discography_artists"]:
        print(f"  discographies: {stats['discography_artists']} artists seeded, "
              f"{stats['discography_recordings']} recordings")
    if any(stats["rotation"].values()):
        print("  rotation:   " + "  ".join(f"{c}: {n}"
                                           for c, n in stats["rotation"].items()))
    if stats["follows"]:
        print(f"  follows:    {stats['follows']} artists tagged #{SOURCE_FOLLOW_TAG}")


if __name__ == "__main__":
    main()
