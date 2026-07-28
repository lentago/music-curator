#!/usr/bin/env python3
"""Render the name-variant merge worksheet for pub.lan (issue #42).

Third in the family after build_review_sheet.py (revise categories) and
build_reservoir_sheet.py (first-tag follows). This one merges artists that the
inventory carries under two spellings, which fragments their albums, graph
edges and rotation stamps across two nodes.

Merging is more consequential than recategorising: a node disappears, album
lists union, and every sidecar that joins on the artist key has to follow. The
sheet therefore shows the sidecar impact per pair, and treats album-level
collapses that need judgment as their own decisions rather than folding them in
silently.

    python build_dedup_sheet.py [--out /mnt/lentago/web/music-dedup/index.html]
"""
import argparse
import html
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dedup_lib import merge_albums  # noqa: E402

INVENTORY = os.path.join(HERE, 'data', 'music-inventory.json')
CREDITS = os.path.join(HERE, 'data', 'credits.json')
STREAMING = os.path.join(HERE, 'data', 'streaming-summary.json')
DEFAULT_OUT = '/mnt/lentago/web/music-dedup/index.html'

# (key_a, key_b, proposed_canonical, rationale)
PAIRS = [
    ('16 Horsepower', 'Sixteen Horsepower', '16 Horsepower',
     'The band\'s usual styling, and the spelling credits.json already points '
     'at via collection_match.'),
    ('Beat Junkies', 'The Beat Junkies', 'The Beat Junkies',
     'Billed as The World Famous Beat Junkies; the article is part of the name.'),
    ('Dave Matthews Band', 'The Dave Matthews Band', 'Dave Matthews Band',
     'Official name carries no article.'),
    ('Dresden Dolls', 'The Dresden Dolls', 'The Dresden Dolls',
     'Official name carries the article.'),
    ('Grateful Dead', 'The Grateful Dead', 'Grateful Dead',
     'Official name carries no article, despite common usage. Ten '
     'collection_match references point at "The Grateful Dead" and would be '
     'remapped.'),
    ('Magnetic Fields', 'The Magnetic Fields', 'The Magnetic Fields',
     'Official name carries the article, 28 collection_match references '
     'already point here, and the streaming export matched this spelling — '
     'all three agree.'),
    ('Microphones', 'The Microphones', 'The Microphones',
     'Official name carries the article.'),
    ('Red Hot Chili Peppers', 'The Red Hot Chili Peppers',
     'Red Hot Chili Peppers',
     'Official name carries no article. collection_match is currently split '
     '2:1 across the two spellings — exactly the fragmentation this fixes.'),
    ('Sigur Ros', 'Sigur Rós', 'Sigur Rós',
     'Correct Icelandic spelling. Also the side holding 10 of the 13 album '
     'entries and the streaming match. This pair is the one hard '
     'normalization collision the validator reports.'),
    ('The xx', 'Xx', 'The xx',
     'Official styling, lowercase. Note the two albums are genuinely '
     'different records — the debut xx and Coexist — so nothing collapses.'),
    ('Neko Case & Her Boyfriends', 'Neko Case And Her Boyfriends',
     'Neko Case & Her Boyfriends',
     'Ampersand matches the sibling entries elsewhere in the inventory.'),
    ('Juan Luis Guerra 440', 'Juan Luis Guerra y 440', 'Juan Luis Guerra 440',
     'Matches the existing collection_match. The strictly official styling is '
     '"Juan Luis Guerra 4.40" if you would rather be correct than stable.'),
    ('Sonny Terry with Johnny Winter& Willie Dixon',
     'Sonny Terry with Johnny Winter& Willie D',
     'Sonny Terry with Johnny Winter& Willie Dixon',
     'The short form is a filesystem truncation, not a name.'),
    ('Joshua Bell-Edgar Meyer-Sam Bush-Mike Marshall',
     'Joshua Bell_Edgar Meyer_Sam Bush_Mike Ma',
     'Joshua Bell-Edgar Meyer-Sam Bush-Mike Marshall',
     'The underscore form is a truncated rip folder.'),
    ('Vishwa Mohan Bhatt With Bela Fleck and Jie Bing Chen',
     'Vishwa Mohan Bhatt With Bela Fleck and J',
     'Vishwa Mohan Bhatt With Bela Fleck and Jie Bing Chen',
     'The short form is a truncation.'),
    ('The Beatles', 'TheBeatles-WhiteAbum-2009StereoRemaster', 'The Beatles',
     'The second key is a rip folder name, misspelling "Album". Its two discs '
     'are the White Album, which the main entry already holds — see the album '
     'decisions below.'),
    ('Old & In the Way', 'Old & in the Way-Jerry Garcia-David Grisman',
     'Old & In the Way',
     'The second key appends the performers to the band name. Its single '
     'album is the same live record the main entry holds.'),
]

# Album-level calls that the conservative merge deliberately refuses to make.
ALBUMS = [
    dict(id='A1', pair='16 Horsepower',
         title='Two Wovenhand albums are filed under 16 Horsepower',
         body='blush_music and consider_the_birds are Wovenhand records — '
              'David Eugene Edwards\' later band — and both already exist '
              'correctly under the Wovenhand entry as "Blush Music" and '
              '"Consider the Birds". This is the three-family spread issue '
              '#42 describes: the credits layer sees Edwards across three '
              'artist families when there are only two.',
         options=[('Drop both from 16 Horsepower',
                   'Wovenhand already holds both. Nothing is lost and the '
                   'credits layer collapses to two families, which is correct.'),
                  ('Keep them on both entries',
                   'Treats them as jointly attributable. Leaves the '
                   'three-family spread in place.')],
         recommended=0),
    dict(id='A2', pair='16 Horsepower',
         title='Three editions of Low Estate',
         body='"Low estate", "Low Estate (Nouvelle)" and "Low Estate Tour '
              'Promo" are three rips of one album — the standard release, the '
              'French Nouvelle edition, and a promo.',
         options=[('Keep all three',
                   'They are distinct physical releases and the collection '
                   'preserves edition detail elsewhere.'),
                  ('Collapse to a single "Low Estate"',
                   'One album, one entry. Loses the edition distinction.')],
         recommended=0),
    dict(id='A3', pair='The Beat Junkies',
         title='An unresolvable truncation',
         body='"The World Famous Beat Junkies, Vol. 2 Di" is a truncated '
              'folder name that could be either Disc 1 or Disc 2 — both of '
              'which are present in full. The merge tool refuses to guess.',
         options=[('Drop the truncated entry',
                   'Both discs are already present under their full names, so '
                   'it carries no information.'),
                  ('Keep it as a third entry',
                   'Preserves the raw rip listing at the cost of a phantom '
                   'album in the count.')],
         recommended=0),
    dict(id='A4', pair='The Magnetic Fields',
         title='69 Love Songs: box plus volumes',
         body='The merged list holds "69 Love Songs" alongside "69 Love Songs '
              'Vol. 1", "Vol. 2" and "Vol. 3" — the box set and its three '
              'discs, ripped twice.',
         options=[('Keep the three volumes, drop the box entry',
                   'The volumes are what is actually on disc; the bare box '
                   'title duplicates them.'),
                  ('Keep all four', 'Preserves both rips as-is.'),
                  ('Collapse to one "69 Love Songs"',
                   'Treats the box as a single album, consistent with how a '
                   'listener thinks of it.')],
         recommended=0),
    dict(id='A5', pair='Sigur Rós',
         title='Hvarf/Heim ripped twice',
         body='"Hvarf - Heim" appears alongside "Hvarf-Heim [Disc 1] (Hvarf)" '
              'and "Hvarf-Heim [Disc 2] (Heim)" — the same double album, once '
              'as a single entry and once split by disc.',
         options=[('Keep the two disc entries, drop the combined one',
                   'Consistent with how other multi-disc sets in the '
                   'collection are listed.'),
                  ('Keep the combined entry, drop the two discs',
                   'One release, one entry.'),
                  ('Keep all three', 'Preserves both rips.')],
         recommended=0),
    dict(id='A6', pair='The Beatles',
         title='The White Album, twice',
         body='The main entry holds "The Beatles Disc 1 (2009 Stere" and '
              '"Disc 2" — the White Album, whose title is just "The Beatles". '
              'The rip-folder entry holds bare "Disc 1" and "Disc 2", which '
              'are the same two discs.',
         options=[('Drop the bare "Disc 1"/"Disc 2" entries',
                   'They are uninformative titles duplicating discs already '
                   'present, and the truncated pair is at least identifiable.'),
                  ('Keep them and rename to "The Beatles [White Album] Disc N"',
                   'Repairs both rips into one clean pair of titles.')],
         recommended=1),
]

DECISIONS = [
    dict(
        id='D1',
        title='What decides the canonical spelling?',
        body='Each merge keeps one key and retires the other. The proposals '
             'below mostly follow the artist\'s official styling, but that is '
             'not the only defensible rule — and it sometimes fights the join '
             'stability of the sidecars.',
        options=[
            ('Official styling of the artist name',
             'The Magnetic Fields keeps its article, Grateful Dead loses '
             'its, Sigur Rós keeps its accent. Correct, but requires '
             'remapping 54 collection_match references.'),
            ('Whichever spelling the sidecars already use',
             'Minimises churn in credits.json and the streaming join. Would '
             'pick "The Grateful Dead" and "16 Horsepower". Locks in some '
             'incorrect names.'),
            ('Whichever variant holds more albums',
             'Purely mechanical, no judgment. Would pick "Magnetic Fields" '
             '(7 albums) over "The Magnetic Fields" (2) — against both '
             'official styling and the sidecars.'),
        ],
        recommended=0,
        affects=[],
    ),
    dict(
        id='D2',
        title='The validator will keep warning about pairs that are not duplicates',
        body='Six flagged pairs are distinct entities that merely look alike: '
             'Charlie Hunter Quartet vs Quintet, Trey Anastasio vs Trey '
             'Anastasio Band, Cannibal Ox vs El-P & Cannibal Ox, Talib Kweli '
             'vs Talib Kweli & Hi Tek, Steve Earle & The Dukes vs (& '
             'Duchesses), and the Masada/Bar Kokhba ensembles settled during '
             'the reservoir pass. After this merge they are all that remains '
             'in the near-dup report, so the signal degrades into noise.',
        options=[
            ('Add a reviewed-pairs allowlist to validate.py',
             'Known-distinct pairs stop warning; genuinely new duplicates '
             'stand out immediately. The allowlist is the record of what was '
             'reviewed and why.'),
            ('Leave the warnings',
             'They are warnings, not violations, and a standing reminder to '
             're-examine. Costs nothing but attention.'),
        ],
        recommended=0,
        affects=['Charlie Hunter Quartet / Quintet',
                 'Trey Anastasio / Trey Anastasio Band',
                 'Cannibal Ox / El-P & Cannibal Ox',
                 'Talib Kweli / Talib Kweli & Hi Tek',
                 'Steve Earle & The Dukes / (& Duchesses)',
                 'Masada / Masada Quintet / Masada String Trio',
                 'Bar Kokhba / Bar Kokhba Sextet'],
    ),
    dict(
        id='D3',
        title='How should rotation be recomputed after merging?',
        body='Rotation (current / dormant / historical) is stamped from '
             'streaming history, and the two sides of a pair often disagree — '
             'Grateful Dead is current while The Grateful Dead is historical, '
             'Magnetic Fields is historical while The Magnetic Fields is '
             'dormant. The raw GDPR export is present locally, so this can be '
             're-derived rather than guessed.',
        options=[
            ('Re-run streaming_merge.py after the merge',
             'Re-derives rotation and the sidecar inventory_key from the raw '
             'export against the merged roster. The principled fix.'),
            ('Take the most active rotation of the pair',
             'current beats dormant beats historical. No re-run needed, but '
             'the sidecar keys still have to be hand-patched.'),
        ],
        recommended=0,
        affects=[],
    ),
]


def esc(s):
    return html.escape(str(s), quote=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=DEFAULT_OUT)
    args = ap.parse_args()

    with open(INVENTORY) as f:
        inv = json.load(f)['artists']
    with open(CREDITS) as f:
        credits = json.load(f)['artists']
    with open(STREAMING) as f:
        stream = json.load(f)['artists']
    stream_keys = {e.get('inventory_key') or e.get('artist') for e in stream}

    cm_counts = {}
    for _art, albums in credits.items():
        for _al, rec in albums.items():
            for p in rec.get('personnel', []):
                cm = p.get('collection_match')
                if cm:
                    cm_counts[cm] = cm_counts.get(cm, 0) + 1

    rows, total_removed, total_cm = [], 0, 0
    for a, b, canon, why in PAIRS:
        ra, rb = inv.get(a), inv.get(b)
        if ra is None or rb is None:
            sys.exit(f'ABORT — missing key: {a if ra is None else b!r}')
        albums = (ra.get('albums') or []) + (rb.get('albums') or [])
        groups, ambiguous = merge_albums(albums)
        collapsed = sum(len(v) - 1 for v in groups.values())
        total_removed += 1
        other = b if canon == a else a

        side = []
        for n, r in ((a, ra), (b, rb)):
            marks = []
            if n in credits:
                marks.append(f'credits: {len(credits[n])} albums')
            if n in stream_keys:
                marks.append('streaming match')
            if cm_counts.get(n):
                marks.append(f'{cm_counts[n]} collection_match refs')
                total_cm += cm_counts[n]
            keep = ' <span class="keepmark">keep</span>' if n == canon else \
                   ' <span class="dropmark">retire</span>'
            side.append(
                f'<div class="side"><code>{esc(n)}</code>{keep}'
                f'<span class="meta">{r.get("album_count", 0)} albums · '
                f'rotation {esc(r.get("rotation") or "—")}'
                + (' · ' + ' · '.join(esc(m) for m in marks) if marks else '')
                + '</span></div>')

        alist = ''.join(
            f'<li>{esc(d)}'
            + (f' <span class="fold">⟵ {len(v)} rips</span>' if len(v) > 1 else '')
            + '</li>'
            for d, v in sorted(groups.items(), key=lambda kv: kv[0].lower()))
        amb = ''.join(
            f'<p class="amb">Unresolvable truncation — matches '
            f'{len(l)} releases, left alone</p>' for _k, l in ambiguous)

        rid = f'M_{esc(canon).replace(" ", "_")[:36]}'
        rows.append(f'''
      <tr data-pair="{esc(a)} + {esc(b)}" data-canon="{esc(canon)}">
        <td class="c-pair">{''.join(side)}
          <p class="why">{esc(why)}</p></td>
        <td class="c-alb"><span class="cnt">{len(albums)} raw → '''
                    f'''{len(groups)} unique</span>
          <ul>{alist}</ul>{amb}</td>
        <td class="c-choice">
          <label class="opt sm"><input type="radio" name="{rid}" value="canon" checked>
            <span class="opt-label">Merge, keep <code>{esc(canon)}</code></span></label>
          <label class="opt sm"><input type="radio" name="{rid}" value="flip">
            <span class="opt-label">Merge, keep <code>{esc(other)}</code></span></label>
          <label class="opt sm"><input type="radio" name="{rid}" value="skip">
            <span class="opt-label">Don't merge</span></label>
          <label class="opt sm"><input type="radio" name="{rid}" value="other">
            <span class="opt-label">Other name</span></label>
          <input type="text" class="other-text row-other" name="{rid}__other"
                 placeholder="canonical name">
        </td>
      </tr>''')

    def card(d):
        opts = ''.join(
            f'<label class="opt"><input type="radio" name="{d["id"]}" value="{i}">'
            f'<span class="opt-body"><span class="opt-label">{esc(lab)}'
            + (' <span class="badge rec">recommended</span>'
               if i == d['recommended'] else '')
            + f'</span><span class="opt-detail">{esc(det)}</span></span></label>'
            for i, (lab, det) in enumerate(d['options']))
        aff = ''
        if d.get('affects'):
            aff = ('<div class="affects"><span class="affects-label">Affects'
                   '</span>' + ' '.join(f'<span class="chip">{esc(x)}</span>'
                                        for x in d['affects']) + '</div>')
        return (f'<article class="card" data-decision="{d["id"]}">'
                f'<div class="card-head"><span class="tag">{d["id"]}</span>'
                f'<h3>{esc(d["title"])}</h3></div>'
                f'<p class="card-body">{esc(d["body"])}</p>'
                f'<div class="opts">{opts}'
                f'<label class="opt"><input type="radio" name="{d["id"]}" value="other">'
                f'<span class="opt-body"><span class="opt-label">Something else</span>'
                f'<input type="text" class="other-text" name="{d["id"]}__other"'
                f' placeholder="your call…"></span></label></div>{aff}</article>')

    page = TEMPLATE.format(
        n_pairs=len(PAIRS),
        n_albums=len(ALBUMS),
        n_dec=len(DECISIONS),
        n_cm=total_cm,
        decisions=''.join(card(d) for d in DECISIONS),
        albums=''.join(card(dict(a, options=a['options'])) for a in ALBUMS),
        rows=''.join(rows),
    )
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, 'w') as f:
        f.write(page)
    print(f'wrote {args.out}')
    print(f'  merge pairs: {len(PAIRS)}  album calls: {len(ALBUMS)}  '
          f'rules: {len(DECISIONS)}')
    print(f'  collection_match refs needing remap: {total_cm}')


TEMPLATE = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Music collection — duplicate merge</title>
<style>
  :root {{ --bg:#faf9f7; --panel:#fff; --ink:#1a1a1a; --muted:#6b6b6b;
    --line:#e2ded8; --accent:#6b4a7c; --accent-soft:#efeaf3;
    --to:#2f6b4f; --warn:#b8860b; --from:#a3453a; --rad:10px; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#17161a; --panel:#1f1e23; --ink:#ece9e4; --muted:#9a958d;
      --line:#33313a; --accent:#b795cf; --accent-soft:#2a2432;
      --to:#7fc4a0; --warn:#d9b45c; --from:#e08b7f; }} }}
  :root[data-theme="dark"] {{ --bg:#17161a; --panel:#1f1e23; --ink:#ece9e4;
    --muted:#9a958d; --line:#33313a; --accent:#b795cf; --accent-soft:#2a2432;
    --to:#7fc4a0; --warn:#d9b45c; --from:#e08b7f; }}
  :root[data-theme="light"] {{ --bg:#faf9f7; --panel:#fff; --ink:#1a1a1a;
    --muted:#6b6b6b; --line:#e2ded8; --accent:#6b4a7c; --accent-soft:#efeaf3;
    --to:#2f6b4f; --warn:#b8860b; --from:#a3453a; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink); padding-bottom:5rem;
    font:15px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif; }}
  .wrap {{ max-width:1240px; margin:0 auto; padding:2rem 1.25rem; }}
  h1 {{ font-size:1.75rem; margin:0 0 .35rem; letter-spacing:-.02em; }}
  .sub {{ color:var(--muted); margin:0 0 1.5rem; max-width:72ch; }}
  code {{ background:var(--accent-soft); padding:.08rem .3rem; border-radius:4px;
    font-size:.88em; }}
  .stats {{ display:flex; flex-wrap:wrap; gap:.6rem; margin-bottom:2rem; }}
  .stat {{ background:var(--panel); border:1px solid var(--line);
    border-radius:var(--rad); padding:.55rem .85rem; }}
  .stat b {{ display:block; font-size:1.35rem; line-height:1.1; }}
  .stat span {{ color:var(--muted); font-size:.78rem; text-transform:uppercase;
    letter-spacing:.06em; }}
  h2 {{ font-size:1.05rem; text-transform:uppercase; letter-spacing:.09em;
    color:var(--accent); margin:2.75rem 0 .4rem; padding-bottom:.4rem;
    border-bottom:2px solid var(--accent-soft); }}
  h2 .n {{ color:var(--muted); font-weight:400; letter-spacing:0;
    text-transform:none; }}
  .lead {{ color:var(--muted); margin:0 0 1.25rem; max-width:76ch; }}
  .card {{ background:var(--panel); border:1px solid var(--line);
    border-radius:var(--rad); padding:1.1rem 1.2rem; margin-bottom:.9rem; }}
  .card-head {{ display:flex; align-items:baseline; gap:.6rem; }}
  .card-head h3 {{ margin:0 0 .4rem; font-size:1.05rem; }}
  .tag {{ background:var(--accent-soft); color:var(--accent); font-weight:700;
    font-size:.72rem; padding:.18rem .45rem; border-radius:5px; }}
  .card-body {{ margin:0 0 .9rem; color:var(--muted); max-width:82ch; }}
  .opts {{ display:flex; flex-direction:column; gap:.35rem; }}
  .opt {{ display:flex; gap:.55rem; align-items:flex-start; padding:.45rem .55rem;
    border-radius:7px; cursor:pointer; border:1px solid transparent; }}
  .opt:hover {{ background:var(--accent-soft); }}
  .opt:has(input:checked) {{ background:var(--accent-soft);
    border-color:var(--accent); }}
  .opt input[type=radio] {{ margin-top:.28rem; accent-color:var(--accent);
    flex-shrink:0; }}
  .opt-body {{ display:flex; flex-direction:column; gap:.15rem; }}
  .opt-label {{ font-weight:600; font-size:.92rem; }}
  .opt-detail {{ color:var(--muted); font-size:.86rem; }}
  .opt.sm {{ padding:.2rem .35rem; }}
  .opt.sm .opt-label {{ font-weight:500; font-size:.85rem; }}
  .badge.rec {{ background:var(--to); color:#fff; font-size:.66rem;
    padding:.1rem .35rem; border-radius:4px; text-transform:uppercase;
    font-weight:700; letter-spacing:.04em; }}
  .other-text {{ margin-top:.25rem; background:var(--bg); color:var(--ink);
    border:1px solid var(--line); border-radius:6px; padding:.3rem .45rem;
    font:inherit; font-size:.85rem; width:100%; max-width:22rem; }}
  .affects {{ margin-top:.85rem; padding-top:.75rem;
    border-top:1px dashed var(--line); }}
  .affects-label {{ display:block; color:var(--muted); font-size:.78rem;
    text-transform:uppercase; letter-spacing:.06em; margin-bottom:.4rem; }}
  .chip {{ display:inline-block; background:var(--accent-soft);
    border-radius:20px; padding:.12rem .55rem; font-size:.8rem;
    margin:0 .25rem .3rem 0; }}
  .table-wrap {{ overflow-x:auto; border:1px solid var(--line);
    border-radius:var(--rad); background:var(--panel); }}
  table {{ border-collapse:collapse; width:100%; min-width:960px; }}
  th {{ text-align:left; font-size:.74rem; text-transform:uppercase;
    letter-spacing:.07em; color:var(--muted); font-weight:600;
    padding:.7rem .8rem; border-bottom:1px solid var(--line);
    background:var(--bg); }}
  td {{ padding:.8rem; border-bottom:1px solid var(--line); vertical-align:top;
    font-size:.9rem; }}
  tr:last-child td {{ border-bottom:0; }}
  .c-pair {{ width:34%; }} .c-alb {{ width:38%; }} .c-choice {{ width:28%; }}
  .side {{ margin-bottom:.5rem; }}
  .side .meta {{ display:block; color:var(--muted); font-size:.79rem;
    margin-top:.12rem; }}
  .keepmark {{ background:var(--to); color:#fff; font-size:.64rem;
    font-weight:700; padding:.08rem .3rem; border-radius:4px;
    text-transform:uppercase; margin-left:.3rem; }}
  .dropmark {{ background:var(--from); color:#fff; font-size:.64rem;
    font-weight:700; padding:.08rem .3rem; border-radius:4px;
    text-transform:uppercase; margin-left:.3rem; }}
  .why {{ margin:.5rem 0 0; color:var(--muted); font-size:.84rem; }}
  .c-alb ul {{ margin:.35rem 0 0; padding-left:1.1rem; }}
  .c-alb li {{ font-size:.82rem; margin-bottom:.12rem; }}
  .cnt {{ color:var(--accent); font-weight:700; font-size:.8rem; }}
  .fold {{ color:var(--to); font-size:.74rem; }}
  .amb {{ color:var(--warn); font-size:.79rem; margin:.4rem 0 0;
    font-style:italic; }}
  .bar {{ position:fixed; bottom:0; left:0; right:0; background:var(--panel);
    border-top:1px solid var(--line); padding:.7rem 1.25rem; display:flex;
    gap:.7rem; align-items:center; flex-wrap:wrap; z-index:20;
    box-shadow:0 -3px 14px rgba(0,0,0,.07); }}
  button {{ font:inherit; font-weight:600; font-size:.88rem; cursor:pointer;
    border-radius:7px; padding:.5rem .9rem; border:1px solid var(--line);
    background:var(--panel); color:var(--ink); }}
  button.primary {{ background:var(--accent); color:#fff;
    border-color:var(--accent); }}
  button:hover {{ filter:brightness(1.06); }}
  .bar .status {{ color:var(--muted); font-size:.85rem; margin-left:auto; }}
  dialog {{ border:1px solid var(--line); border-radius:var(--rad); padding:0;
    background:var(--panel); color:var(--ink); max-width:720px; width:92%; }}
  dialog::backdrop {{ background:rgba(0,0,0,.45); }}
  .dlg-head {{ padding:1rem 1.2rem .4rem; }}
  .dlg-head h3 {{ margin:0 0 .2rem; }}
  .dlg-head p {{ margin:0; color:var(--muted); font-size:.88rem; }}
  dialog textarea {{ width:calc(100% - 2.4rem); margin:.8rem 1.2rem; height:46vh;
    background:var(--bg); color:var(--ink); border:1px solid var(--line);
    border-radius:7px; padding:.7rem; font-family:ui-monospace,Menlo,monospace;
    font-size:.82rem; resize:vertical; }}
  .dlg-foot {{ padding:0 1.2rem 1.1rem; display:flex; gap:.6rem; }}
  @media (max-width:720px) {{ .wrap {{ padding:1.25rem .85rem; }}
    h1 {{ font-size:1.4rem; }} }}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>Music collection — duplicate merge</h1>
  <p class="sub">Issue #42. {n_pairs} artists are carried under two spellings,
  which splits their albums, graph edges and rotation stamps across two nodes.
  Merging retires one key, so it reaches further than a recategorisation:
  <strong>{n_cm}</strong> <code>collection_match</code> references in
  <code>credits.json</code> point at a key that is about to disappear. Album
  lists are merged conservatively — only exact, case, accent and unambiguous
  truncation matches fold automatically; everything requiring judgment is a
  decision below.</p>
</header>

<div class="stats">
  <div class="stat"><b>{n_pairs}</b><span>merge pairs</span></div>
  <div class="stat"><b>{n_dec}</b><span>rules to set</span></div>
  <div class="stat"><b>{n_albums}</b><span>album calls</span></div>
  <div class="stat"><b>{n_cm}</b><span>refs to remap</span></div>
</div>

<h2>1 · Rules <span class="n">— decide these first</span></h2>
<p class="lead">Each sets policy for the whole pass rather than one pair.</p>
{decisions}

<h2>2 · Album-level calls <span class="n">— {n_albums} the merge refuses to guess</span></h2>
<p class="lead">The conservative merge preserves disc numbers, bracketed
editions and parenthetical suffixes, because stripping them collapses
genuinely distinct releases. These are the cases it deliberately left alone.</p>
{albums}

<h2>3 · The merges <span class="n">— {n_pairs} pairs, pre-set to the proposal</span></h2>
<p class="lead">Each row shows both keys with what depends on them, and the
merged album list the conservative fold produces. <span class="keepmark">keep</span>
marks the proposed canonical name.</p>
<div class="table-wrap"><table>
<thead><tr><th>Pair</th><th>Merged albums</th><th>Your call</th></tr></thead>
<tbody>{rows}</tbody></table></div>
</div>

<div class="bar">
  <button class="primary" id="copy">Copy decisions</button>
  <button id="acceptall">Accept all proposals</button>
  <button id="reset">Reset</button>
  <button id="theme" title="Toggle light/dark">◐</button>
  <span class="status" id="status"></span>
</div>

<dialog id="dlg">
  <div class="dlg-head"><h3>Your decisions</h3>
  <p>Copied to the clipboard. If that failed, select and copy manually.</p></div>
  <textarea id="out" readonly></textarea>
  <div class="dlg-foot"><button class="primary" id="copy2">Copy again</button>
  <button id="close">Close</button></div>
</dialog>

<script>
const KEY='music-dedup-v1';
const $=s=>document.querySelector(s);
function save(){{
  const d={{}};
  document.querySelectorAll('input[type=radio]:checked').forEach(r=>d[r.name]=r.value);
  document.querySelectorAll('input.other-text').forEach(t=>{{if(t.value)d[t.name]=t.value;}});
  localStorage.setItem(KEY,JSON.stringify(d));
  const rows=[...document.querySelectorAll('tr[data-pair] input[type=radio]:checked')];
  const merging=rows.filter(r=>r.value!=='skip').length;
  const cards=document.querySelectorAll('.card[data-decision]').length;
  const done=document.querySelectorAll('.card[data-decision] input[type=radio]:checked').length;
  $('#status').textContent=`rules+albums ${{done}}/${{cards}} · ${{merging}} merging, ${{rows.length-merging}} left alone`;
}}
function restore(){{
  let d; try{{d=JSON.parse(localStorage.getItem(KEY)||'{{}}');}}catch(e){{return;}}
  for(const [n,v] of Object.entries(d)){{
    if(n.endsWith('__other')){{
      const t=document.querySelector(`input[name="${{CSS.escape(n)}}"]`); if(t)t.value=v;
    }} else {{
      const r=document.querySelector(`input[name="${{CSS.escape(n)}}"][value="${{CSS.escape(v)}}"]`);
      if(r)r.checked=true;
    }}
  }}
}}
function build(){{
  const L=['# Duplicate merge — decisions',''];
  L.push('## Rules and album calls');
  document.querySelectorAll('.card[data-decision]').forEach(c=>{{
    const id=c.dataset.decision, title=c.querySelector('h3').textContent.trim();
    const s=c.querySelector('input[type=radio]:checked');
    if(!s){{L.push(`${{id}}: (no answer) — ${{title}}`);return;}}
    if(s.value==='other'){{
      const t=c.querySelector('.other-text');
      L.push(`${{id}}: OTHER — ${{(t&&t.value)||'(blank)'}}   [${{title}}]`);
    }} else {{
      const lab=s.closest('.opt').querySelector('.opt-label')
        .textContent.replace('recommended','').trim();
      L.push(`${{id}}: ${{lab}}   [${{title}}]`);
    }}
  }});
  L.push('','## Merges');
  document.querySelectorAll('tr[data-pair]').forEach(tr=>{{
    const s=tr.querySelector('input[type=radio]:checked'); if(!s)return;
    const p=tr.dataset.pair, c=tr.dataset.canon;
    if(s.value==='canon') L.push(`- ${{p}}: MERGE → ${{c}}`);
    else if(s.value==='skip') L.push(`- ${{p}}: DO NOT MERGE`);
    else if(s.value==='other'){{
      const t=tr.querySelector('.row-other');
      L.push(`- ${{p}}: MERGE → ${{(t&&t.value)||'(blank)'}}`);
    }} else if(s.value==='flip'){{
      const lab=s.closest('.opt').querySelector('.opt-label').textContent
        .replace('Merge, keep','').trim();
      L.push(`- ${{p}}: MERGE → ${{lab}}`);
    }}
  }});
  return L.join('\n');
}}
async function copyOut(){{
  const t=build(); $('#out').value=t;
  try{{await navigator.clipboard.writeText(t);}}catch(e){{}}
  if(!$('#dlg').open)$('#dlg').showModal();
}}
$('#copy').onclick=copyOut; $('#copy2').onclick=copyOut;
$('#close').onclick=()=>$('#dlg').close();
$('#acceptall').onclick=()=>{{
  document.querySelectorAll('tr[data-pair] input[value=canon]').forEach(r=>r.checked=true);
  document.querySelectorAll('.card[data-decision]').forEach(c=>{{
    if(!c.querySelector('input[type=radio]:checked')){{
      const r=c.querySelector('input[type=radio]'); if(r)r.checked=true;
    }}
  }});
  save();
}};
$('#reset').onclick=()=>{{if(confirm('Clear every recorded decision?')){{
  localStorage.removeItem(KEY);location.reload();}}}};
$('#theme').onclick=()=>{{
  const c=document.documentElement.dataset.theme;
  const n=c==='dark'?'light':c==='light'?'':'dark';
  if(n)document.documentElement.dataset.theme=n;
  else delete document.documentElement.dataset.theme;
  localStorage.setItem(KEY+'-theme',n);
}};
const st=localStorage.getItem(KEY+'-theme');
if(st)document.documentElement.dataset.theme=st;
document.addEventListener('change',save);
document.addEventListener('input',e=>{{
  if(e.target.classList.contains('other-text')){{
    const g=e.target.closest('.opt, td');
    const o=g&&g.querySelector('input[value=other]');
    if(o)o.checked=true; save();
  }}
}});
restore(); save();
</script>
</body>
</html>
'''

if __name__ == '__main__':
    main()
