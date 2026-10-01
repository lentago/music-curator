# Contributing

This is a personal lab project ([README.md](README.md) has the full pitch),
but it runs on real CI/CD conventions and welcomes changes. This doc covers
local setup, the conventions the code already follows, how the checks that
gate a PR work, and how to submit a change.

## Local setup

The toolchain is Python 3.11+, stdlib-only except for `validate.py`'s schema
check. `pyproject.toml` + a pip-tools-generated `requirements-lock.txt`
(hashed) is the whole dependency surface:

```bash
python3 -m pip install --require-hashes -r requirements-lock.txt
```

`jsonschema` is imported inside a `try`/`except` in `validate.py`, so every
other script runs fine with no install step at all — clone the repo and run
them directly with `python3 <script>.py`.

## Running the project

Everything is a flat collection of top-level scripts invoked directly, not a
package meant to be imported. The two you'll touch most:

```bash
# Validate the inventory against schema/music-inventory.schema.json plus
# cross-field checks (near-duplicate artist keys, count mismatches, etc.)
python3 validate.py data/music-inventory.json

# Regenerate vault/ from data/
python3 obsidian_driver.py
```

`obsidian_driver.py` takes an optional positional path to the inventory and
flags for the sidecar layers and graph preset — run `python3
obsidian_driver.py --help` for the full list. The other top-level scripts
(`streaming_merge.py`, `harvest_merge.py`, `discography_merge.py`,
`merge_duplicates.py`, `repair_titles.py`, the `build_*_sheet.py` family) each
fold one data source into a `data/` sidecar or produce a review sheet; see
their module docstrings for usage — every script opens with a `"""Usage:
..."""` block at the top of the file, so `head -20 <script>.py` is usually
enough to know how to invoke it.

## Conventions observed in the code

- **Stdlib only.** No script here reaches for a third-party dependency
  beyond `jsonschema`, and that import is guarded and optional. Keep new
  tooling dependency-free unless there's a strong reason not to.
- **Module docstring with a `Usage:` block.** Every script opens with a
  `#!/usr/bin/env python3` shebang and a top-of-file docstring describing
  what it does, how to invoke it, and (where relevant) what it exits
  non-zero on. See `validate.py` or `curator_lib.py` for the shape.
- **`argparse` for CLI scripts**, with `parser = argparse.ArgumentParser(...)`
  and long, descriptive `help=` strings on every flag (see `main()` in
  `obsidian_driver.py` or `streaming_merge.py`).
- **`if __name__ == "__main__":` + a `main()` function** at the bottom of
  every runnable script.
- **Double-quoted strings**, `snake_case` for functions and variables,
  module-level constants in `SCREAMING_SNAKE_CASE` near the top of the file
  (e.g. `SCHEMA_PATH`, `NEAR_DUP_THRESHOLD` in `validate.py`).
- **Comments explain *why*, not *what*.** See the header comment in
  `curator_lib.py`'s `alnum()` — it justifies the accent-folding pass with
  the specific bug it prevents, rather than restating the code.
- **Shared logic lives in `curator_lib.py` / `dedup_lib.py`**, not copied
  across scripts. `alnum()` is the single dedup key every merge layer joins
  through — if you need to normalize an artist or title name, use it rather
  than writing a new regex.
- **Sidecar architecture.** Each new data dimension is its own merge tool
  reading/writing its own `data/*.json` file, keyed to the roster by
  `alnum()`, rather than folded into a monolith. See
  [`docs/adr/0001-generated-obsidian-vault.md`](docs/adr/0001-generated-obsidian-vault.md)
  for the reasoning.
- **Generated artifacts are never hand-edited.** `vault/` is rendered by
  `obsidian_driver.py` from `data/`; edit the data source and regenerate,
  don't touch files under `vault/` directly (CI enforces this — see below).

## Tests / checks

There is no separate test suite or test framework in this repo — correctness
is enforced by two things, both of which run in CI on every PR via
`.github/workflows/integrity.yml`:

```bash
python3 validate.py data/music-inventory.json   # schema + cross-field checks
python3 obsidian_driver.py                       # regenerate the vault
git diff --quiet -- vault/                       # must produce no diff
```

Run both locally before opening a PR if your change touches `data/` or the
driver. If you edit anything under `data/`, regenerate `vault/` in the same
PR — a mismatch fails the required `integrity` check.

`.github/workflows/docs-check.yml` also runs on every PR and checks that
relative markdown links resolve; fix any links you add or rename.

## Submitting a change

1. Branch off `main`.
2. Make your change, following the conventions above. If you touched
   `data/music-inventory.json` or any sidecar, run `python3
   obsidian_driver.py` and commit the regenerated `vault/` alongside it.
3. Run `python3 validate.py data/music-inventory.json` if you touched the
   inventory.
4. Commit with a [Conventional Commits](https://www.conventionalcommits.org/)
   style message (`feat:`, `fix:`, `chore:`, `docs:`, with an optional scope
   like `chore(ci):` or `docs(adr):`) — see `git log` for examples from this
   repo.
5. Open a pull request against `main`. The `integrity` and `docs-check`
   required checks must pass; `CODEOWNERS` will request review from the
   repo owner automatically. PRs are squash-merged.
