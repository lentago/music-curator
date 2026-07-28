#!/usr/bin/env python3
"""Render the outcome page for the categorization pass.

Companion to build_review_sheet.py: the worksheet collects decisions, this
records what landed. Diffs the working inventory against a git ref so the
change log is derived from the data rather than hand-maintained.

    python build_results_page.py [--ref HEAD] [--out /mnt/lentago/web/music-categories/index.html]
"""
import argparse
import collections
import html
import json
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
INVENTORY = os.path.join(HERE, 'data', 'music-inventory.json')
DEFAULT_OUT = '/mnt/lentago/web/music-categories/index.html'

DECISIONS = [
    ('T1', 'Add "Golden Age" as a sibling of Underground',
     'Underground held 55 artists including the foundational canon. Nine acts '
     'from the 1986–1997 canon moved out: A Tribe Called Quest, De La Soul, '
     'Eric B & Rakim, Run-D.M.C, The Pharcyde, Common, Fu-Schnickens, Das EFX, '
     'EPMD. Post-1997 and underground-leaning acts stayed put. A follow-up '
     'decision added a third sibling, Mainstream, for commercial rap that is '
     'neither the canon nor underground: Eminem, OutKast, DMX, Insane Clown '
     'Posse, N.E.R.D. That took the bare Hip-Hop tier from ten artists to '
     'one.'),
    ('T2', 'Move Standards & Vocal from Pop to Jazz',
     'One home for the songbook. The rule applied: singer-led interpretation '
     'of the standards goes to Jazz › Standards & Vocal; instrumentalist-led '
     'artists stay bare in Jazz. Nine artists moved in; Pop › Standards & '
     'Vocal is retired.'),
    ('T3', 'Add the four subcategories with existing mass',
     'Jazz › Gypsy Jazz (4), Jazz › Fusion (4), Soul › Gospel (2), '
     'Soul › New Orleans Funk (4). Jazz\'s bare tier dropped from 39 to 22.'),
    ('T4', 'Add World › Reggae & Dub',
     'The 13 top-level categories stay intact; reggae gets a real home one '
     'tier down. Jimmy Cliff moved in.'),
    ('T5', 'Split the klezmer cluster on intent, not label',
     'Traditional/revival klezmer to World (The Klezmatics, Daniel Kahn & the '
     'Painted Bird). Zorn\'s Radical Jewish Culture project pieces stay '
     'Avant-Garde because the composition — not the Tzadik imprint — is the '
     'reason.'),
    ('T6', 'Collabs inherit unless the record contradicts it',
     'Applied as an audit across all ~30 combo entries. Tier A and the artist '
     'pass had already resolved every violation but one: Mermaid Avenue, '
     'where Billy Bragg (Folk) and Wilco (Rock › Indie & Alternative) no '
     'longer share a category, so inheritance was undefined and the record '
     'decided it — Woody Guthrie lyrics, acoustic, filed Folk.'),
    ('T7', 'Keep one category per artist',
     'The anchors get their nuance from anchor notes and personnel edges, not '
     'from multi-category membership. No changes.'),
]

OPEN = [
    ('The Disposable Heroes of Hiphoprisy',
     'Hip-Hop (bare)',
     'The last artist with no Hip-Hop subcategory. Political/alternative rap '
     '(1992) that reads as Underground on content but sold like neither '
     'Underground nor Mainstream — left bare rather than forced onto a shelf.'),
    ('Xzibit, Tha Liks',
     'Underground',
     'Both are plausible members of the new Mainstream shelf — Xzibit '
     'especially, as a Dr. Dre-affiliated West Coast act. They were not part '
     'of the five that Mainstream was created for, so they were left in place '
     'rather than swept in.'),
    ('Bahamadia, Jurassic 5, Hieroglyphics, Blackalicious, '
     'Dilated Peoples, Prince Paul',
     'Underground',
     'Golden Age borderline. The line was drawn at the 1986–1997 canon, which '
     'leaves these in Underground — several are era-eligible but read as '
     'underground, and the owned albums for Jurassic 5 (2000) and Dilated '
     'Peoples (2001) are post-window.'),
    ('Louis Armstrong, Sidney Bechet, Norah Jones, Nellie McKay',
     'Jazz (bare)',
     'Left out of Standards & Vocal by the T2 rule: Armstrong and Bechet are '
     'instrumentalist-led, Jones and McKay sing mostly originals. Armstrong is '
     'the arguable one — he is also the archetypal jazz vocalist.'),
    ('Cracow Klezmer Band', 'Avant-Garde & Experimental',
     'The one case where the T5 rule cuts against the band\'s own identity: '
     'they are a klezmer revival group, but the owned record is literally a '
     'Zorn Book of Angels volume (Masada Book II), so by intent it is a Zorn '
     'project piece.'),
    ('Beirut', 'Folk & Singer-Songwriter',
     'Carries the same "Balkan and klezmer" confirmation note as The '
     'Klezmatics, which moved to World. Under T5 they now resolve differently '
     '— Beirut is indie songwriting with Balkan color, not klezmer revival. '
     'That is the rule working as intended, but it is worth an explicit nod.'),
    ('Jaya the Cat', 'Rock › Punk & Hardcore',
     'Reggae-punk. Not moved to the new Reggae & Dub shelf because its peers '
     'are punk, but it is the obvious second candidate.'),
    ('Billy Bragg & Wilco — Mermaid Avenue', 'Country & Americana',
     'The only T6 violation left. Billy Bragg is Folk and Wilco is now Rock › '
     'Indie & Alternative, so the principals no longer share a category and '
     'inheritance is undefined. The record itself — Woody Guthrie lyrics, '
     'acoustic — argues Folk & Singer-Songwriter.'),
]

NOT_IN_SCOPE = [
    ('~15 name-variant duplicate pairs',
     'Sigur Ros/Sigur Rós, 16 Horsepower/Sixteen Horsepower, The xx/Xx, '
     'Grateful Dead/The Grateful Dead and others. They agree on category, so '
     'they are not a categorization bug — but each is two votes for one '
     'artist. validate.py reports all 13 pairs plus one normalization '
     'collision.'),
    ('48-artist follow reservoir',
     'Untagged Spotify follows awaiting a first categorization. A tagging '
     'pass, not a revision pass.'),
]


def esc(s):
    return html.escape(str(s), quote=True)


def dist(artists):
    cat, sub = collections.Counter(), collections.Counter()
    for rec in artists.values():
        if rec.get('discard') or not rec.get('category'):
            continue
        cat[rec['category']] += 1
        sub[(rec['category'], rec.get('subcategory') or '—')] += 1
    return cat, sub


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ref', default='HEAD')
    ap.add_argument('--out', default=DEFAULT_OUT)
    args = ap.parse_args()

    old = json.loads(subprocess.run(
        ['git', 'show', f'{args.ref}:data/music-inventory.json'],
        capture_output=True, text=True, cwd=HERE).stdout)['artists']
    with open(INVENTORY) as f:
        new = json.load(f)['artists']

    def key(rec):
        return (rec.get('category'), rec.get('subcategory'))

    changed = sorted(n for n in new
                     if n in old and key(old[n]) != key(new[n]))

    oc, os_ = dist(old)
    nc, ns = dist(new)

    def label(c, s):
        return c + (f' › {s}' if s and s != '—' else '')

    # --- change log, grouped by destination category ---
    by_dest = collections.defaultdict(list)
    for n in changed:
        by_dest[new[n]['category']].append(n)
    log_html = []
    for cat in sorted(by_dest, key=lambda c: -len(by_dest[c])):
        rows = ''.join(
            f'<tr><td><strong>{esc(n)}</strong></td>'
            f'<td class="from">{esc(label(*key(old[n])))}</td>'
            f'<td class="to">{esc(label(*key(new[n])))}</td></tr>'
            for n in by_dest[cat])
        log_html.append(
            f'<details class="log"><summary>{esc(cat)} '
            f'<span class="cnt">{len(by_dest[cat])} moved in</span></summary>'
            f'<div class="table-wrap"><table><thead><tr><th>Artist</th>'
            f'<th>Was</th><th>Now</th></tr></thead><tbody>{rows}</tbody>'
            f'</table></div></details>')

    # --- tree diff ---
    tree = []
    for c in sorted(set(oc) | set(nc), key=lambda k: -nc.get(k, 0)):
        o, n = oc.get(c, 0), nc.get(c, 0)
        d = n - o
        delta = f'<span class="{"up" if d > 0 else "down"}">{d:+d}</span>' if d else ''
        tree.append(f'<tr class="lvl1"><td>{esc(c)}</td><td>{o}</td>'
                    f'<td>{n}</td><td>{delta}</td></tr>')
        subs = sorted({s for (cc, s) in set(os_) | set(ns) if cc == c})
        for s in subs:
            o2, n2 = os_.get((c, s), 0), ns.get((c, s), 0)
            if o2 == 0 and n2 > 0:
                mark = '<span class="new">new</span>'
            elif n2 == 0:
                mark = '<span class="gone">retired</span>'
            else:
                d2 = n2 - o2
                mark = (f'<span class="{"up" if d2 > 0 else "down"}">{d2:+d}</span>'
                        if d2 else '')
            tree.append(f'<tr class="lvl2"><td>{esc(s)}</td><td>{o2}</td>'
                        f'<td>{n2}</td><td>{mark}</td></tr>')

    dec_html = ''.join(
        f'<article class="card"><div class="card-head"><span class="tag">{d}</span>'
        f'<h3>{esc(t)}</h3></div><p class="card-body">{esc(b)}</p></article>'
        for d, t, b in DECISIONS)

    open_html = ''.join(
        f'<tr><td><strong>{esc(who)}</strong></td>'
        f'<td class="cur">{esc(where)}</td>'
        f'<td class="why-cell">{esc(why)}</td></tr>'
        for who, where, why in OPEN)

    scope_html = ''.join(
        f'<li><strong>{esc(t)}</strong> — {esc(b)}</li>'
        for t, b in NOT_IN_SCOPE)

    n_new_subs = sum(1 for (c, s) in ns if s != '—' and (c, s) not in os_)
    n_gone_subs = sum(1 for (c, s) in os_ if s != '—' and (c, s) not in ns)

    page = TEMPLATE.format(
        n_changed=len(changed),
        n_scope=sum(nc.values()),
        n_new_subs=n_new_subs,
        n_gone_subs=n_gone_subs,
        decisions=dec_html,
        tree=''.join(tree),
        log=''.join(log_html),
        open_rows=open_html,
        scope=scope_html,
    )

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, 'w') as f:
        f.write(page)
    print(f'wrote {args.out}')
    print(f'  records changed: {len(changed)}')
    print(f'  new subcategories: {n_new_subs}  retired: {n_gone_subs}')


TEMPLATE = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Music collection — categorization pass, applied</title>
<style>
  :root {{
    --bg:#faf9f7; --panel:#fff; --ink:#1a1a1a; --muted:#6b6b6b;
    --line:#e2ded8; --accent:#7c4a2d; --accent-soft:#f3ece6;
    --from:#a3453a; --to:#2f6b4f; --warn:#b8860b; --rad:10px;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#17161a; --panel:#1f1e23; --ink:#ece9e4; --muted:#9a958d;
      --line:#33313a; --accent:#d29b6e; --accent-soft:#2a2630;
      --from:#e08b7f; --to:#7fc4a0; --warn:#d9b45c; }}
  }}
  :root[data-theme="dark"] {{ --bg:#17161a; --panel:#1f1e23; --ink:#ece9e4;
    --muted:#9a958d; --line:#33313a; --accent:#d29b6e; --accent-soft:#2a2630;
    --from:#e08b7f; --to:#7fc4a0; --warn:#d9b45c; }}
  :root[data-theme="light"] {{ --bg:#faf9f7; --panel:#fff; --ink:#1a1a1a;
    --muted:#6b6b6b; --line:#e2ded8; --accent:#7c4a2d; --accent-soft:#f3ece6;
    --from:#a3453a; --to:#2f6b4f; --warn:#b8860b; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font:15px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif; }}
  .wrap {{ max-width:1060px; margin:0 auto; padding:2rem 1.25rem 4rem; }}
  .done {{ display:inline-block; background:var(--to); color:#fff;
    font-size:.7rem; font-weight:700; letter-spacing:.08em;
    text-transform:uppercase; padding:.2rem .5rem; border-radius:5px;
    margin-bottom:.7rem; }}
  h1 {{ font-size:1.75rem; margin:0 0 .35rem; letter-spacing:-.02em; }}
  .sub {{ color:var(--muted); margin:0 0 1.5rem; max-width:70ch; }}
  .stats {{ display:flex; flex-wrap:wrap; gap:.6rem; margin-bottom:2rem; }}
  .stat {{ background:var(--panel); border:1px solid var(--line);
    border-radius:var(--rad); padding:.55rem .85rem; }}
  .stat b {{ display:block; font-size:1.35rem; line-height:1.1; }}
  .stat span {{ color:var(--muted); font-size:.78rem;
    text-transform:uppercase; letter-spacing:.06em; }}
  h2 {{ font-size:1.05rem; text-transform:uppercase; letter-spacing:.09em;
    color:var(--accent); margin:2.75rem 0 .4rem; padding-bottom:.4rem;
    border-bottom:2px solid var(--accent-soft); }}
  .lead {{ color:var(--muted); margin:0 0 1.25rem; max-width:72ch; }}
  .card {{ background:var(--panel); border:1px solid var(--line);
    border-radius:var(--rad); padding:1rem 1.15rem; margin-bottom:.7rem; }}
  .card-head {{ display:flex; align-items:baseline; gap:.6rem; }}
  .card-head h3 {{ margin:0 0 .35rem; font-size:1rem; }}
  .tag {{ background:var(--accent-soft); color:var(--accent); font-weight:700;
    font-size:.72rem; padding:.18rem .45rem; border-radius:5px; }}
  .card-body {{ margin:0; color:var(--muted); max-width:80ch; font-size:.92rem; }}
  .table-wrap {{ overflow-x:auto; border:1px solid var(--line);
    border-radius:var(--rad); background:var(--panel); }}
  table {{ border-collapse:collapse; width:100%; min-width:560px; }}
  th {{ text-align:left; font-size:.74rem; text-transform:uppercase;
    letter-spacing:.07em; color:var(--muted); font-weight:600;
    padding:.65rem .8rem; border-bottom:1px solid var(--line);
    background:var(--bg); }}
  td {{ padding:.55rem .8rem; border-bottom:1px solid var(--line);
    vertical-align:top; font-size:.89rem; }}
  tr:last-child td {{ border-bottom:0; }}
  .from {{ color:var(--from); }} .to {{ color:var(--to); font-weight:600; }}
  .cur {{ color:var(--warn); white-space:nowrap; }}
  .why-cell {{ color:var(--muted); font-size:.86rem; }}
  .tree td:nth-child(2), .tree td:nth-child(3) {{ text-align:right;
    font-variant-numeric:tabular-nums; width:5rem; }}
  .tree td:nth-child(4) {{ width:6rem; }}
  .lvl1 td:first-child {{ font-weight:700; }}
  .lvl2 td:first-child {{ padding-left:2rem; color:var(--muted); }}
  .up {{ color:var(--to); font-weight:600; }}
  .down {{ color:var(--from); font-weight:600; }}
  .new {{ background:var(--to); color:#fff; font-size:.66rem; font-weight:700;
    padding:.1rem .35rem; border-radius:4px; text-transform:uppercase; }}
  .gone {{ background:var(--from); color:#fff; font-size:.66rem;
    font-weight:700; padding:.1rem .35rem; border-radius:4px;
    text-transform:uppercase; }}
  details.log {{ background:var(--panel); border:1px solid var(--line);
    border-radius:var(--rad); padding:.7rem .9rem; margin-bottom:.55rem; }}
  details.log summary {{ cursor:pointer; font-weight:600; }}
  details.log .cnt {{ color:var(--muted); font-weight:400; font-size:.86rem; }}
  details.log .table-wrap {{ margin-top:.7rem; }}
  ul {{ padding-left:1.15rem; color:var(--muted); max-width:76ch; }}
  li {{ margin-bottom:.5rem; }}
  li strong {{ color:var(--ink); }}
  .theme {{ position:fixed; top:.8rem; right:.8rem; font:inherit;
    cursor:pointer; border:1px solid var(--line); background:var(--panel);
    color:var(--ink); border-radius:7px; padding:.35rem .6rem; }}
  @media (max-width:720px) {{ .wrap {{ padding:1.25rem .85rem 3rem; }}
    h1 {{ font-size:1.4rem; }} }}
</style>
</head>
<body>
<button class="theme" id="theme" title="Toggle light/dark">◐</button>
<div class="wrap">
<span class="done">applied</span>
<h1>Music collection — categorization pass</h1>
<p class="sub">Full revision pass over the categorized artists in
<code>music-curator</code>. All seven taxonomy questions were decided and every
artist proposal accepted. This page records what landed and what is still
open — it replaces the review worksheet that lived at this URL.</p>

<div class="stats">
  <div class="stat"><b>{n_changed}</b><span>records changed</span></div>
  <div class="stat"><b>{n_new_subs}</b><span>subcategories added</span></div>
  <div class="stat"><b>{n_gone_subs}</b><span>retired</span></div>
  <div class="stat"><b>{n_scope}</b><span>artists in scope</span></div>
</div>

<h2>Taxonomy decisions</h2>
<p class="lead">Settled first, because each one changed the answers available
to the artist pass below it.</p>
{decisions}

<h2>The tree, before and after</h2>
<div class="table-wrap"><table class="tree">
<thead><tr><th>Category</th><th>Before</th><th>After</th><th></th></tr></thead>
<tbody>{tree}</tbody></table></div>

<h2>Change log</h2>
<p class="lead">Every record whose category or subcategory moved, grouped by
where it landed. Derived from the data, not hand-maintained.</p>
{log}

<h2>Still open</h2>
<p class="lead">Calls I had to make to finish the pass that are worth a second
look, and one rule violation the pass could not resolve on its own.</p>
<div class="table-wrap"><table>
<thead><tr><th>Artist(s)</th><th>Currently</th><th>Why it is open</th></tr></thead>
<tbody>{open_rows}</tbody></table></div>

<h2>Deliberately out of scope</h2>
<ul>{scope}</ul>
</div>
<script>
const K='music-cat-results-theme';
const saved=localStorage.getItem(K);
if(saved) document.documentElement.dataset.theme=saved;
document.getElementById('theme').onclick=()=>{{
  const c=document.documentElement.dataset.theme;
  const n=c==='dark'?'light':c==='light'?'':'dark';
  if(n) document.documentElement.dataset.theme=n;
  else delete document.documentElement.dataset.theme;
  localStorage.setItem(K,n);
}};
</script>
</body>
</html>
'''

if __name__ == '__main__':
    main()
