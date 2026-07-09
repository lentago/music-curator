---
type: "moc"
tags: ["moc"]
---

# About this vault

This vault is **generated** from `music-inventory.json` by `obsidian_driver.py` in the [music-curator](https://github.com/lentago/music-curator) repo. Don't hand-edit the notes — regenerate instead; edits are overwritten.

## Reading the graph

- Every **artist** links to exactly one **category** hub — that link is the graph edge, and each category is a distinct color, so the clusters read at a glance.
- **Combo acts link directly to their members** (`El-P & Cannibal Ox` → El-P + Cannibal Ox), so the graph also shows the collaboration social graph, not just category membership. See a note's **With:** line.
- **Session ties** link artists who share personnel — a musician who played on both their albums (Marc Ribot across Tom Waits and John Zorn; Jerry Douglas across the bluegrass records). Only roster artists become ties; see a note's **Session ties:** line. These edges cross category clusters and are the collection's hidden wiring.
- No artist is singled out — node size follows degree, so importance emerges from the graph, not a prior.
- The graph opens **filtered** (`-tag:#moc`, orphans hidden) so the meta notes (this one, Music Collection, Reservoir) and the untagged reservoir don't clutter the taste map. Clear the filter and enable *Show orphans* to browse the whole collection, including the reservoir.

Start at [[Music Collection]].
