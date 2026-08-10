#!/usr/bin/env bash
# Apply a graph preset to the running Obsidian app via the official CLI
# (Obsidian >= 1.12, Settings -> General -> Command line interface enabled).
#
#   apply.sh              list available presets
#   apply.sh <name>       apply <name>.json from this directory
#
# Settings are pushed straight into the open graph view's dataEngine, so the
# switch is live and Obsidian persists it to .obsidian/graph.json itself —
# no file races with the app (editing graph.json on disk while Obsidian is
# open gets clobbered by the app's in-memory state; this route doesn't).
set -euo pipefail

vault="Music"
dir="$(cd "$(dirname "$0")" && pwd)"

if [ $# -eq 0 ]; then
  for f in "$dir"/*.json; do basename "$f" .json; done
  exit 0
fi

preset="$dir/${1%.json}.json"
[ -f "$preset" ] || { echo "no such preset: $1" >&2; exit 1; }

obsidian eval vault="$vault" code="
const preset = $(cat "$preset");
app.commands.executeCommandById('graph:open');
app.workspace.getLeavesOfType('graph')[0].view.dataEngine.setOptions(preset);
'applied ${1%.json}';
"
