---
type: "moc"
tags: ["moc"]
---

# About this vault

This vault is **generated** from `music-inventory.json` by `obsidian_driver.py` in the [music-curator](https://github.com/lentago/music-curator) repo. Don't hand-edit the notes — regenerate instead; edits are overwritten.

## Reading the graph

- **Artist** notes link to the **scene** and **genre** hubs they belong to — those links are the graph edges. Compound genres are split on `/` so artists sharing just one component (e.g. `hip-hop`) still connect.
- **Combo acts link directly to their members** (`El-P & Cannibal Ox` → El-P + Cannibal Ox), so the graph shows the collaboration social graph, not just hub membership. See a note's **With:** line.
- Color groups are pre-set by node type: **scene** hubs blue, **genre** hubs orange, artists light grey. No artist is singled out — node size follows degree, so importance emerges from the graph, not a prior.
- Multi-scene artists are the bridges between clusters — follow them to find cross-pollination (a jazz guitarist who is also in the klezmer and Tom Waits orbits, say).
- The graph opens **filtered** (`-tag:#moc`, orphans hidden) so the meta notes (this one, Music Collection, Reservoir) and the untagged reservoir don't clutter the taste map. Clear the filter and enable *Show orphans* to browse the whole collection, including the grey reservoir inventory.

Start at [[Music Collection]].
