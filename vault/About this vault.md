---
type: "moc"
tags: ["moc"]
---

# About this vault

This vault is **generated** from `music-inventory.json` by `obsidian_driver.py` in the [music-curator](https://github.com/lentago/music-curator) repo. Don't hand-edit the notes — regenerate instead; edits are overwritten.

## Reading the graph

- Every **artist** links to exactly one hub — its **subcategory** where it has one (Hip-Hop › Underground), else its top-level **category**. Subcategory hubs link up to their category, so the graph is a two-tier tree, and every node in a branch carries its top-level tag — each top-level category is a distinct color, so the clusters read at a glance.
- **Combo acts link directly to their members** (`El-P & Cannibal Ox` → El-P + Cannibal Ox), so the graph also shows the collaboration social graph, not just category membership. See a note's **With:** line.
- **Session ties** link artists who share personnel — a musician who played on both their albums (Marc Ribot across Tom Waits and John Zorn; Jerry Douglas across the bluegrass records). Only roster artists become ties; see a note's **Session ties:** line. These edges cross category clusters and are the collection's hidden wiring.
- Some artists carry a seeded **Discography** section — the *complete* known catalog harvested from a canonical source, not just the owned albums. ◆ marks recordings that are in the collection; recordings credited to another roster artist link to it, so a seeded artist's side-projects wire straight into the graph.
- Most artists carry a **rotation** class — `current`, `dormant` or `historical` — merged in from the Spotify streaming history. It is a second, independent axis over the same graph: switch to the `rotation` graph preset to recolor every node by what is still in play. [[Rotation]] collects the gaps in both directions — artists in rotation the collection has no roots in, and deep shelf anchors that have fallen out of play.
- No artist is singled out — node size follows degree, so importance emerges from the graph, not a prior.
- The graph opens **filtered** (`-tag:#moc`, orphans hidden) so the meta notes (this one, Music Collection, Reservoir, Rotation) and the untagged reservoir don't clutter the taste map. Clear the filter and enable *Show orphans* to browse the whole collection, including the reservoir.

Start at [[Music Collection]].
