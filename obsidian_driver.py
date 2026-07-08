#!/usr/bin/env python3
"""
Render a music-inventory JSON file into an Obsidian vault whose graph view
clusters artists by scene and genre.

Each active artist becomes a note that wikilinks to its scene(s) and genre;
those scene/genre notes are the hub nodes the graph clusters around. Anchors
get an MOC, untagged artists hang off a single Reservoir hub, and the whole
thing opens in Obsidian with a pre-styled graph (color-grouped by note type)
and no plugins required.

Usage:
    python obsidian_driver.py [path/to/music-inventory.json] [--out DIR]

    # defaults: reads examples/music-inventory.json, writes examples/obsidian-vault/
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
DEFAULT_INVENTORY = os.path.join(HERE, "examples", "music-inventory.json")
DEFAULT_OUT = os.path.join(HERE, "examples", "obsidian-vault")

# Written to the output dir so a later run knows the dir is ours to wipe.
MARKER = ".generated-by-music-curator"

# Characters that are illegal in filenames on common OSes or that break
# Obsidian wikilink resolution (#, ^, [, ], |, and path separators).
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f#^\[\]]')

RESERVOIR_HUB = "Reservoir"
ANCHORS_MOC = "Anchors"
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


def prettify_scene(slug):
    """`radical-jewish-culture` -> `Radical Jewish Culture` for display."""
    return slug.replace("-", " ").replace("_", " ").title()


def prettify_album(name):
    """Gentle read-friendly cleanup of slug-style folder names."""
    return re.sub(r"\s+", " ", name.replace("_", " ")).strip()


def genre_components(genre):
    """Split a compound genre string on '/' into its component hub names.

    `jazz rap / hip-hop` -> ['jazz rap', 'hip-hop'], so two artists that share
    only the `hip-hop` component still cluster together. A simple genre with no
    '/' is returned as a single-element list.
    """
    if not genre:
        return []
    return [part.strip() for part in re.split(r"\s*/\s*", genre) if part.strip()]


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
    """An artist with neither scene tags nor a genre is exploration inventory."""
    return not record.get("scenes") and not record.get("genre")


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


def build_vault(inventory, out_dir, include_discarded=False):
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

    # Collect scene and genre hub nodes and their members.
    scene_members = {}     # scene slug      -> [artist display names]
    genre_members = {}     # genre component -> [artist display names]
    reservoir_members = []
    anchors = []
    collab_map = {}        # artist name -> [constituent artist names that are nodes]

    for name, rec in active.items():
        if is_reservoir(rec):
            reservoir_members.append(name)
        for scene in rec.get("scenes", []) or []:
            scene_members.setdefault(scene, []).append(name)
        for component in genre_components(rec.get("genre")):
            genre_members.setdefault(component, []).append(name)
        if rec.get("anchor"):
            anchors.append(name)
        constituents = parse_collaborators(name, name_lookup)
        if constituents:
            collab_map[name] = constituents

    # Allocate globally-unique basenames. Reserve the MOC names first so they
    # keep clean titles, then artists, then hubs.
    alloc = BasenameAllocator()
    fixed = {n: alloc.take(n) for n in (HOME_MOC, ANCHORS_MOC, RESERVOIR_HUB, ABOUT_NOTE)}
    artist_base = {name: alloc.take(name) for name in active}
    scene_base = {scene: alloc.take(scene) for scene in sorted(scene_members)}
    genre_base = {genre: alloc.take(genre) for genre in sorted(genre_members)}

    prepare_output_dir(out_dir)

    # --- Artist notes ---------------------------------------------------------
    for name, rec in active.items():
        tags = ["artist"]
        if rec.get("anchor"):
            tags.append("anchor")
        if rec.get("discard"):
            tags.append("discarded")
        reservoir = is_reservoir(rec)
        if reservoir:
            tags.append("reservoir")

        fm = frontmatter([
            ("aliases", [name] if artist_base[name] != name else None),
            ("type", "artist"),
            ("scenes", rec.get("scenes")),
            ("genre", rec.get("genre")),
            ("era", rec.get("era")),
            ("album_count", rec.get("album_count")),
            ("anchor", True if rec.get("anchor") else None),
            ("discarded", True if rec.get("discard") else None),
            ("collaborators", collab_map.get(name) or None),
            ("tags", tags),
        ])

        parts = [fm, "", f"# {name}", ""]

        # Edge links: scenes, then each genre component, then Reservoir.
        edges = []
        for scene in rec.get("scenes", []) or []:
            edges.append(link(scene_base[scene], prettify_scene(scene)))
        for component in genre_components(rec.get("genre")):
            edges.append(link(genre_base[component], component))
        if reservoir:
            edges.append(link(fixed[RESERVOIR_HUB]))
        if edges:
            label = "Scenes / genre" if not reservoir else "Filed under"
            parts.append(f"**{label}:** " + " · ".join(edges))
            parts.append("")

        # Collaboration edges: direct artist-to-artist links parsed from the
        # combo key, drawn only to constituents that are themselves nodes.
        collaborators = collab_map.get(name, [])
        if collaborators:
            parts.append(
                "**With:** " + " · ".join(link(artist_base[c], c) for c in collaborators)
            )
            parts.append("")

        if rec.get("anchor") and rec.get("anchor_note"):
            parts.append(f"> **Anchor.** {rec['anchor_note']}")
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

    # --- Scene hub notes ------------------------------------------------------
    for scene, members in sorted(scene_members.items()):
        fm = frontmatter([
            ("aliases", [scene] if scene_base[scene] != scene else None),
            ("type", "scene"),
            ("member_count", len(members)),
            ("tags", ["scene"]),
        ])
        body = [
            fm, "", f"# {prettify_scene(scene)}", "",
            f"*Scene — {len(members)} artist(s) in the collection.*", "",
            "## Artists",
        ]
        body.extend(
            f"- {link(artist_base[m], m)}" for m in sorted(members, key=str.lower)
        )
        write_note(out_dir, "Scenes", scene_base[scene], "\n".join(body))

    # --- Genre hub notes ------------------------------------------------------
    for genre, members in sorted(genre_members.items()):
        fm = frontmatter([
            ("aliases", [genre] if genre_base[genre] != genre else None),
            ("type", "genre"),
            ("member_count", len(members)),
            ("tags", ["genre"]),
        ])
        body = [
            fm, "", f"# {genre}", "",
            f"*Genre — {len(members)} artist(s) in the collection.*", "",
            "## Artists",
        ]
        body.extend(
            f"- {link(artist_base[m], m)}" for m in sorted(members, key=str.lower)
        )
        write_note(out_dir, "Genres", genre_base[genre], "\n".join(body))

    # --- Anchors MOC ----------------------------------------------------------
    anchor_body = [
        frontmatter([("type", "moc"), ("tags", ["moc"])]), "",
        f"# {ANCHORS_MOC}", "",
        "The foundational artists everything else routes through — the "
        "highest-degree hubs in the graph.", "",
    ]
    for name in sorted(anchors, key=str.lower):
        note = active[name].get("anchor_note", "")
        anchor_body.append(f"- {link(artist_base[name], name)}" + (f" — {note}" if note else ""))
    write_note(out_dir, "", fixed[ANCHORS_MOC], "\n".join(anchor_body))

    # --- Reservoir hub --------------------------------------------------------
    reservoir_body = [
        frontmatter([("type", "moc"), ("tags", ["moc", "reservoir"])]), "",
        f"# {RESERVOIR_HUB}", "",
        f"The untagged reservoir — {len(reservoir_members)} artists kept in the "
        "collection but not yet scene-tagged. These are exploration inventory, "
        "not confident taste signal: mine them before reaching for external "
        "recommendations. Tag one with a scene/genre and it graduates into the "
        "graph proper.", "",
        "## Artists",
    ]
    reservoir_body.extend(
        f"- {link(artist_base[m], m)}" for m in sorted(reservoir_members, key=str.lower)
    )
    write_note(out_dir, "", fixed[RESERVOIR_HUB], "\n".join(reservoir_body))

    # --- Home MOC -------------------------------------------------------------
    bridges = sum(1 for r in active.values() if len(r.get("scenes", []) or []) > 1)
    collab_edges = sum(len(v) for v in collab_map.values())
    top_scenes = sorted(scene_members.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    home = [
        frontmatter([("type", "moc"), ("tags", ["moc"])]), "",
        f"# {HOME_MOC}", "",
        "A taste map of the collection. Open the **graph view** (Ctrl/Cmd-G) to "
        "see artists cluster around the scene and genre hubs they link to; the "
        "four anchors sit at the densest nodes, multi-scene artists bridge the "
        "clusters, and combo acts link straight to the members they share.", "",
        "## By the numbers", "",
        f"- **{len(active)}** artists",
        f"- **{len(scene_members)}** scenes · **{len(genre_members)}** genre components",
        f"- **{len(anchors)}** anchors · **{bridges}** multi-scene bridge artists",
        f"- **{collab_edges}** direct artist-to-artist collaboration edges",
        f"- **{len(reservoir_members)}** in the untagged {link(fixed[RESERVOIR_HUB])}",
        "",
        "## Start here", "",
        f"- {link(fixed[ANCHORS_MOC])} — the foundational hubs",
        f"- {link(fixed[RESERVOIR_HUB])} — exploration inventory",
        f"- {link(fixed[ABOUT_NOTE])} — how to read this vault",
        "",
        "## Largest scenes", "",
    ]
    for scene, members in top_scenes[:15]:
        home.append(f"- {link(scene_base[scene], prettify_scene(scene))} ({len(members)})")
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
        "- **Artist** notes link to the **scene** and **genre** hubs they "
        "belong to — those links are the graph edges. Compound genres are split "
        "on `/` so artists sharing just one component (e.g. `hip-hop`) still "
        "connect.",
        "- **Combo acts link directly to their members** (`El-P & Cannibal Ox` "
        "→ El-P + Cannibal Ox), so the graph shows the collaboration social "
        "graph, not just hub membership. See a note's **With:** line.",
        "- Color groups are pre-set: anchors gold, scenes blue, genres green, "
        "the reservoir grey, ordinary artists light.",
        "- Multi-scene artists are the bridges between clusters — follow them to "
        "find cross-pollination (a jazz guitarist who is also in the klezmer and "
        "Tom Waits orbits, say).",
        "- The grey **Reservoir** blob is untagged inventory; hide it with a "
        "`-tag:#reservoir` graph filter for a clean taste map.", "",
        f"Start at {link(fixed[HOME_MOC])}.",
    ]
    write_note(out_dir, "", fixed[ABOUT_NOTE], "\n".join(about))

    # --- Pre-styled graph config + vault .gitignore --------------------------
    write_graph_config(out_dir)
    write_gitignore(out_dir)

    return {
        "artists": len(active),
        "scenes": len(scene_members),
        "genres": len(genre_members),
        "anchors": len(anchors),
        "bridges": bridges,
        "collab_edges": collab_edges,
        "reservoir": len(reservoir_members),
        "meta_total": meta.get("total_unique_artists"),
    }


def write_graph_config(out_dir):
    """Drop a .obsidian/graph.json so the graph opens color-grouped by type."""
    graph = {
        "collapse-filter": True,
        "search": "",
        "showTags": False,
        "showAttachments": False,
        "hideUnresolved": False,
        "showOrphans": True,
        "collapse-color-groups": False,
        "colorGroups": [
            {"query": "tag:#anchor", "color": {"a": 1, "rgb": 16755763}},     # gold
            {"query": "tag:#scene", "color": {"a": 1, "rgb": 4827094}},       # blue
            {"query": "tag:#genre", "color": {"a": 1, "rgb": 6605645}},       # green
            {"query": "tag:#reservoir", "color": {"a": 1, "rgb": 8355711}},   # grey
            {"query": "tag:#artist", "color": {"a": 1, "rgb": 14737632}},     # light grey
        ],
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
    args = parser.parse_args()

    inventory = load_json(args.inventory)
    stats = build_vault(inventory, args.out, include_discarded=args.include_discarded)

    print(f"Wrote vault to: {args.out}")
    print(f"  artists:   {stats['artists']}")
    print(f"  scenes:    {stats['scenes']}  genre components: {stats['genres']}")
    print(f"  anchors:   {stats['anchors']}  bridges: {stats['bridges']}")
    print(f"  collab edges: {stats['collab_edges']}")
    print(f"  reservoir: {stats['reservoir']}")


if __name__ == "__main__":
    main()
