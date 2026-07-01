#!/usr/bin/env python3
"""
Validate a music-inventory JSON file against the schema and cross-field rules.

Usage:
    python validate.py [path/to/music-inventory.json]

Exits 0 on clean validation, 1 on any error (schema violation, count
mismatch, etc.).  Near-duplicate artist-key warnings do NOT cause a non-zero
exit on their own, but are printed so a human can decide whether to merge them.

Dependencies: jsonschema >= 4.0  (pip install jsonschema)
"""

import difflib
import json
import os
import sys

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema", "music-inventory.schema.json")
DEFAULT_INVENTORY = os.path.join(os.path.dirname(__file__), "examples", "music-inventory.json")

# Similarity threshold for near-duplicate artist-key detection.
# 0.85 catches obvious variants (The X / X, truncated names, & vs and)
# while staying below the Quartet/Quintet false-positive floor in practice.
NEAR_DUP_THRESHOLD = 0.85


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


def validate_schema(inventory, schema):
    """Validate inventory against JSON Schema. Returns list of error strings."""
    try:
        import jsonschema
    except ImportError:
        print(
            "WARNING: jsonschema not installed — skipping structural schema check.\n"
            "         Install it with:  pip install jsonschema>=4.0",
            file=sys.stderr,
        )
        return []

    validator_cls = jsonschema.Draft7Validator
    validator = validator_cls(schema)
    errors = []
    for err in sorted(validator.iter_errors(inventory), key=lambda e: list(e.absolute_path)):
        path = "/".join(str(p) for p in err.absolute_path) or "(root)"
        errors.append(f"  [{path}] {err.message}")
    return errors


def validate_meta_counts(inventory):
    """
    Verify that the three meta counters match the actual artist records.

    Rules:
      meta.total_unique_artists == len(artists)
      meta.tagged_artists       == count(a where tagged == true)
      meta.untagged_artists     == count(a where tagged == false)
    """
    errors = []
    meta = inventory.get("meta", {})
    artists = inventory.get("artists", {})

    actual_total = len(artists)
    actual_tagged = sum(1 for a in artists.values() if a.get("tagged") is True)
    actual_untagged = sum(1 for a in artists.values() if a.get("tagged") is False)

    claimed_total = meta.get("total_unique_artists")
    claimed_tagged = meta.get("tagged_artists")
    claimed_untagged = meta.get("untagged_artists")

    if claimed_total != actual_total:
        errors.append(
            f"  meta.total_unique_artists is {claimed_total} "
            f"but len(artists) is {actual_total}"
        )
    if claimed_tagged != actual_tagged:
        errors.append(
            f"  meta.tagged_artists is {claimed_tagged} "
            f"but count(tagged==true) is {actual_tagged}"
        )
    if claimed_untagged != actual_untagged:
        errors.append(
            f"  meta.untagged_artists is {claimed_untagged} "
            f"but count(tagged==false) is {actual_untagged}"
        )
    return errors


def validate_album_counts(inventory):
    """album_count must equal len(albums) for every artist record."""
    errors = []
    for name, record in inventory.get("artists", {}).items():
        declared = record.get("album_count")
        actual = len(record.get("albums", []))
        if declared != actual:
            errors.append(
                f"  {name!r}: album_count={declared} but len(albums)={actual}"
            )
    return errors


def find_near_duplicate_keys(inventory):
    """
    Best-effort detection of artist keys that are likely spelling variants
    of the same artist (truncated folder names, 'The' prefix, '&' vs 'and',
    diacritic variants, etc.).

    Returns a list of (ratio, key_a, key_b) tuples, sorted descending.
    """
    keys = list(inventory.get("artists", {}).keys())
    hits = []
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            ratio = difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()
            if ratio >= NEAR_DUP_THRESHOLD:
                hits.append((ratio, a, b))
    hits.sort(reverse=True)
    return hits


def main():
    inventory_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_INVENTORY
    schema = load_json(SCHEMA_PATH)
    inventory = load_json(inventory_path)

    print(f"Validating: {inventory_path}")
    print(f"Schema:     {SCHEMA_PATH}")
    print()

    all_errors = []

    # 1. JSON Schema structural validation
    schema_errors = validate_schema(inventory, schema)
    if schema_errors:
        print(f"SCHEMA VIOLATIONS ({len(schema_errors)}):")
        for e in schema_errors:
            print(e)
        print()
        all_errors.extend(schema_errors)

    # 2. Meta count cross-field check
    count_errors = validate_meta_counts(inventory)
    if count_errors:
        print(f"META COUNT MISMATCHES ({len(count_errors)}):")
        for e in count_errors:
            print(e)
        print()
        all_errors.extend(count_errors)

    # 3. Per-artist album_count vs len(albums)
    album_errors = validate_album_counts(inventory)
    if album_errors:
        print(f"ALBUM COUNT MISMATCHES ({len(album_errors)}):")
        for e in album_errors:
            print(e)
        print()
        all_errors.extend(album_errors)

    # 4. Near-duplicate artist key detection (warnings only — not counted as errors)
    near_dups = find_near_duplicate_keys(inventory)
    if near_dups:
        print(f"NEAR-DUPLICATE ARTIST KEYS — review and merge if same artist ({len(near_dups)} pairs):")
        for ratio, a, b in near_dups:
            print(f"  {ratio:.2f}  {a!r}  vs  {b!r}")
        print()

    # Summary
    if not all_errors:
        dups_note = f" ({len(near_dups)} near-dup warnings)" if near_dups else ""
        print(f"OK — no violations{dups_note}.")
        sys.exit(0)
    else:
        n = len(all_errors)
        print(f"FAILED — {n} violation{'s' if n != 1 else ''}.")
        sys.exit(1)


if __name__ == "__main__":
    main()
