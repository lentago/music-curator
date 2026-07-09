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

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_INVENTORY = os.path.join(HERE, "data", "music-inventory.json")
DEFAULT_CREDITS = os.path.join(HERE, "data", "credits.json")
DEFAULT_OUT = os.path.join(HERE, "vault")

# Written to the output dir so a later run knows the dir is ours to wipe.
MARKER = ".generated-by-music-curator"

# Characters that are illegal in filenames on common OSes or that break
# Obsidian wikilink resolution (#, ^, [, ], |, and path separators).
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f#^\[\]]')

RESERVOIR_HUB = "Reservoir"
HOME_MOC = "Music Collection"
ABOUT_NOTE = "About this vault"


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
                if not person.get("in_collection"):
                    continue
                for match in resolve(person.get("collection_match")):
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


def build_vault(inventory, out_dir, include_discarded=False, credits=None):
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
    fixed = {n: alloc.take(n) for n in (HOME_MOC, RESERVOIR_HUB, ABOUT_NOTE)}
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

        fm = frontmatter([
            ("aliases", [name] if artist_base[name] != name else None),
            ("type", "artist"),
            ("category", cat),
            ("subcategory", rec.get("subcategory")),
            ("era", rec.get("era")),
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
        f"The untagged reservoir — {len(reservoir_members)} artists kept in the "
        "collection but not yet assigned a category. These are exploration "
        "inventory, not confident taste signal: mine them before reaching for "
        "external recommendations. Give one a category and it graduates into the "
        "graph proper.", "",
        "## Artists",
    ]
    reservoir_body.extend(
        f"- {link(artist_base[m], m)}" for m in sorted(reservoir_members, key=str.lower)
    )
    write_note(out_dir, "", fixed[RESERVOIR_HUB], "\n".join(reservoir_body))

    # --- Home MOC -------------------------------------------------------------
    collab_edges = sum(len(v) for v in collab_map.values())
    personnel_edge_count = sum(len(v) for v in personnel_edges.values()) // 2
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
        "",
        "## Start here", "",
        f"- {link(fixed[RESERVOIR_HUB])} — exploration inventory",
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
        "- No artist is singled out — node size follows degree, so importance "
        "emerges from the graph, not a prior.",
        "- The graph opens **filtered** (`-tag:#moc`, orphans hidden) so the meta "
        "notes (this one, Music Collection, Reservoir) and the untagged reservoir "
        "don't clutter the taste map. Clear the filter and enable *Show orphans* "
        "to browse the whole collection, including the reservoir.", "",
        f"Start at {link(fixed[HOME_MOC])}.",
    ]
    write_note(out_dir, "", fixed[ABOUT_NOTE], "\n".join(about))

    # --- Pre-styled graph config + vault .gitignore --------------------------
    write_graph_config(out_dir, sorted(category_members))
    write_gitignore(out_dir)

    return {
        "artists": len(active),
        "categories": len(category_members),
        "subcategories": len(sub_members),
        "collab_edges": collab_edges,
        "personnel_edges": personnel_edge_count,
        "reservoir": len(reservoir_members),
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


def write_graph_config(out_dir, categories):
    """Drop a .obsidian/graph.json so the graph opens filtered and colored by category.

    The meta / navigation notes (Music Collection, About, Reservoir) are all
    tagged #moc, so `-tag:#moc` hides them from the graph while they remain in
    the vault for reading. With the Reservoir hub hidden, the untagged artists
    that only linked to it become orphans, so showOrphans is off — leaving a
    clean, connected taste map of artists clustered around their category hubs,
    each category its own color.
    """
    graph = {
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
    folder = os.path.join(out_dir, ".obsidian")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "graph.json"), "w", encoding="utf-8") as fh:
        json.dump(graph, fh, indent=2)


def write_gitignore(out_dir):
    """Keep the generated graph config tracked; ignore Obsidian's runtime state.

    Opening the vault in Obsidian writes workspace.json, core-plugins.json, etc.
    into .obsidian/. This keeps those out of git while preserving graph.json.
    """
    body = (
        "# Obsidian runtime state — keep the generated graph config, ignore the rest.\n"
        ".obsidian/*\n"
        "!.obsidian/graph.json\n"
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
    args = parser.parse_args()

    inventory = load_json(args.inventory)
    credits = load_json(args.credits) if os.path.exists(args.credits) else None
    stats = build_vault(inventory, args.out, include_discarded=args.include_discarded,
                        credits=credits)

    print(f"Wrote vault to: {args.out}")
    print(f"  artists:    {stats['artists']}")
    print(f"  categories: {stats['categories']}  subcategories: {stats['subcategories']}")
    print(f"  collab edges: {stats['collab_edges']}  personnel edges: {stats['personnel_edges']}")
    print(f"  reservoir:  {stats['reservoir']}")


if __name__ == "__main__":
    main()
