#!/usr/bin/env python3
"""Render the reservoir-intake worksheet for pub.lan.

Companion to build_review_sheet.py. That sheet revises artists that already
carry a category; this one gives a first category to the untagged follow
reservoir. The evidence is different — these artists own no albums, so the
columns are streaming history, credits ties into owned albums, and follow date.

Because mistagging pollutes later analysis more than leaving an artist
untagged, low-confidence rows default to "leave untagged" rather than to the
proposal.

    python build_reservoir_sheet.py [--out /mnt/lentago/web/music-reservoir/index.html]
"""
import argparse
import html
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from curator_lib import alnum  # noqa: E402

INVENTORY = os.path.join(HERE, 'data', 'music-inventory.json')
STREAMING = os.path.join(HERE, 'data', 'streaming-summary.json')
CREDITS = os.path.join(HERE, 'data', 'credits.json')
FOLLOWS = os.path.join(HERE, 'data', 'follows.json')
DEFAULT_OUT = '/mnt/lentago/web/music-reservoir/index.html'

TAXONOMY = [
    dict(
        id='R1',
        title='The reservoir has a prog cluster with nowhere to go',
        body='Six follows are progressive rock or prog-metal — Wobbler, OSI, '
             'Blackfield, Joey Eppard, Polyphia, Twelve Foot Ninja. Rock has '
             'six subcategories and none of them fit: they are not Classic '
             'Rock, not Indie & Alternative, and only some are Metal. The '
             'collection already holds Rush and Genesis (Classic Rock), Tool '
             '(Metal), The Mars Volta (Punk & Hardcore) and Mew (Indie & '
             'Alternative), so the gap predates the reservoir.',
        options=[
            ('Add Rock › Progressive, intake only',
             'Create it and file the six follows there. Leave the existing '
             'Rush/Genesis/Tool/Mars Volta filings alone for now — revisiting '
             'them is a separate decision.'),
            ('Add Rock › Progressive, and re-file the existing members too',
             'Create it and pull Rush, Genesis, The Mars Volta and Mew across '
             'in the same pass. Bigger blast radius; Classic Rock drops to 16.'),
            ('No new subcategory — split them across Metal and Indie',
             'Polyphia, Twelve Foot Ninja and OSI to Metal; Blackfield and '
             'Joey Eppard to Indie & Alternative; Wobbler to bare Rock.'),
        ],
        recommended=0,
        affects=['Wobbler', 'OSI', 'Blackfield', 'Joey Eppard', 'Polyphia',
                 'Twelve Foot Ninja'],
    ),
    dict(
        id='R2',
        title='Funk-jam bands straddle Jam and Soul/Funk',
        body='The Motet (578 plays — the most-streamed artist in the whole '
             'reservoir), The Main Squeeze and The Filthy Six are funk bands '
             'that work the jam circuit. Rock › Jam currently holds the '
             'jam-scene acts regardless of what they play; Soul, Funk & R&B '
             'holds funk regardless of scene. The two rules disagree here.',
        options=[
            ('Genre wins — file them under Soul, Funk & R&B',
             'Jam stays a rock subcategory for rock bands. Consistent with '
             'how every other category is assigned by what the music is.'),
            ('Scene wins — file them under Rock › Jam',
             'Jam is a scene bucket by design, sitting alongside Phish, moe. '
             'and Widespread Panic; these bands belong to that world.'),
            ('Split them individually',
             'The Motet and The Main Squeeze to Jam (jam-circuit bands), The '
             'Filthy Six to Soul/Funk (a UK acid-jazz studio combo with no '
             'jam-scene connection).'),
        ],
        recommended=2,
        affects=['The Motet', 'The Main Squeeze', 'The Filthy Six'],
    ),
    dict(
        id='R3',
        title='20 of the 48 follows have no streaming history at all',
        body='These were bulk-backfilled follows: no trigger track, no seed '
             'ties, and no plays above the 10-play floor in the GDPR export. '
             'The repo rule is explicit that leaving an artist untagged is '
             'correct and mistagging pollutes later analysis — so the '
             'question is whether a follow alone is enough evidence to tag on.',
        options=[
            ('Tag them anyway where the genre is unambiguous',
             'A follow is a deliberate act, and genre is a fact about the '
             'artist rather than about your listening. Bad Bunny is Latin '
             'whether or not it shows up in the export.'),
            ('Leave all 20 untagged until they show plays',
             'Strictest reading of the rule. The reservoir keeps doing its '
             'job; these get tagged when listening evidence arrives.'),
            ('Tag only the ones with a graph tie',
             'Bill Laswell and David Krakauer have credits ties into owned '
             'albums; the Zorn ensembles are named siblings of existing '
             'entries. Tag those, leave the rest.'),
        ],
        recommended=0,
        affects=[],
    ),
]

# (artist, cat, sub, alternates, rationale, confidence)
# confidence 'low' => the row defaults to "leave untagged"
GROUPS = [
    ('Zorn / Downtown orbit',
     'The collection already files every Masada and Bar Kokhba ensemble under '
     'Avant-Garde, and T5 settled that Zorn project pieces stay there. These '
     'are distinct ensembles, not duplicate spellings of existing entries.',
     [
        ('Bar Kokhba', 'Avant-Garde & Experimental', None, [],
         'Zorn ensemble. "Bar Kokhba Sextet" is already in the collection as '
         'a separate ensemble; this is the parent project.', 'high'),
        ('Masada Quintet', 'Avant-Garde & Experimental', None, [],
         'Zorn ensemble. "Masada" and "Masada Quintet Featuring Joe Lovano" '
         'are both already filed here.', 'high'),
        ('Masada String Trio', 'Avant-Garde & Experimental', None, [],
         'Zorn ensemble, sibling of the above.', 'high'),
        ('Painkiller', 'Avant-Garde & Experimental', None, [('Rock', 'Metal')],
         'Zorn / Bill Laswell / Mick Harris trio — grindcore-jazz. Sits with '
         'the rest of the Downtown material.', 'medium'),
        ('Bill Laswell', 'Avant-Garde & Experimental', None, [],
         'Credits tie: appears on owned John Zorn and David Byrne & Brian Eno '
         'albums. Enters the graph as a person node, like Marc Ribot and '
         'Trevor Dunn.', 'high'),
        ('David Krakauer', 'World', None,
         [('Avant-Garde & Experimental', None)],
         'Credits tie: John Zorn, Masada Chamber Ensembles AND The Klezmatics '
         '— which T5 just moved to World. His own catalog is klezmer '
         'clarinet, so the intent rule points to World; his credits point to '
         'Avant-Garde. Genuinely split.', 'medium'),
        ('Sleepytime Gorilla Museum', 'Avant-Garde & Experimental', None,
         [('Rock', 'Metal')],
         'Avant-metal / experimental. Could sit with Mr. Bungle, which just '
         'moved to Avant-Garde on the same logic.', 'medium'),
     ]),

    ('Hip-Hop — the Aesop Rock orbit',
     'The largest cluster in the reservoir. Several are direct collaborators '
     'of artists already in the collection.',
     [
        ('Hail Mary Mallon', 'Hip-Hop', 'Underground', [],
         'Aesop Rock\'s group with Rob Sonic and DJ Big Wiz. 104 plays.',
         'high'),
        ('Homeboy Sandman', 'Hip-Hop', 'Underground', [],
         'Credits tie into an owned Aesop Rock album. 182 plays.', 'high'),
        ('Lice', 'Hip-Hop', 'Underground', [],
         'Aesop Rock & Homeboy Sandman collaborative project. 212 plays — '
         'among the most-streamed in the reservoir.', 'high'),
        ('Hemlock Ernst', 'Hip-Hop', 'Underground', [],
         'Samuel T. Herring\'s rap alias, works with Kenny Segal. 22 plays.',
         'high'),
        ('Kenny Segal', 'Hip-Hop', 'Turntablism & Beats',
         [('Hip-Hop', 'Underground')],
         'Producer rather than MC — the beats shelf is where Madlib and '
         'Blockhead sit. 24 plays.', 'medium'),
        ('BUSDRIVER', 'Hip-Hop', 'Underground', [],
         'LA abstract/underground rap. 88 plays.', 'high'),
        ('Prof', 'Hip-Hop', 'Underground', [],
         'Rhymesayers, Minneapolis — same label world as Atmosphere, already '
         'in the collection. 74 plays.', 'high'),
        ('Sage Francis', 'Hip-Hop', 'Underground', [],
         'Anticon/Epitaph underground rap. No streaming history.', 'medium'),
        ('Eyedea & Abilities', 'Hip-Hop', 'Underground', [],
         'Rhymesayers duo. No streaming history.', 'medium'),
        ('Murs', 'Hip-Hop', 'Underground', [],
         'Living Legends / Rhymesayers. No streaming history.', 'medium'),
        ('Zion I', 'Hip-Hop', 'Underground', [],
         'Bay Area underground. No streaming history.', 'medium'),
        ('Greydon Square', 'Hip-Hop', 'Underground', [],
         'Independent atheist rap. No streaming history.', 'low'),
        ('Vince Staples', 'Hip-Hop', 'Mainstream',
         [('Hip-Hop', 'Underground')],
         'Critically acclaimed and commercially distributed — the new '
         'Mainstream shelf fits better than Underground. No streaming '
         'history.', 'medium'),
        ('Childish Gambino', 'Hip-Hop', 'Mainstream', [],
         'Donald Glover — thoroughly commercial. 97 plays.', 'high'),
     ]),

    ('Jazz and classical',
     'A clear jazz intake, mostly European piano trios and UK ensembles.',
     [
        ('Brad Mehldau', 'Jazz', None, [],
         'The Vince Guaraldi note in the inventory already describes a '
         '"Mehldau/Goldberg lane" — he is named in the collection\'s own '
         'reasoning without being in it. 157 plays.', 'high'),
        ('Hiromi', 'Jazz', None, [],
         'Japanese jazz piano. No streaming history.', 'medium'),
        ('Tingvall Trio', 'Jazz', None, [],
         'Swedish-German piano trio, same lane as Esbjörn Svensson Trio which '
         'is already in the collection. 115 plays.', 'high'),
        ('Portico Quartet', 'Jazz', None, [('Electronic', None)],
         'UK ambient jazz — genuinely amphibious between Jazz and Electronic. '
         '36 plays.', 'medium'),
        ('Ishmael Ensemble', 'Jazz', None, [('Electronic', None)],
         'Bristol spiritual-jazz/electronic hybrid. Same ambiguity as Portico '
         'Quartet. 15 plays.', 'low'),
        ('Quatuor Molinari', 'Classical', None, [],
         'Montreal string quartet specialising in contemporary composition. '
         'Would be the 6th artist in Classical. No streaming history.',
         'medium'),
     ]),

    ('Soul, funk and the Daptone world',
     'Instrumental soul and funk revival bands.',
     [
        ('The Budos Band', 'Soul, Funk & R&B', None, [],
         'Daptone afrobeat-soul instrumental band — label-mates of Sharon '
         'Jones & The Dap-Kings, already in the collection. 287 plays.',
         'high'),
        ('Orgone', 'Soul, Funk & R&B', None, [],
         'LA funk band. 318 plays.', 'high'),
        ('Say She She', 'Soul, Funk & R&B', None, [],
         'Discodelic soul, Daptone-adjacent. No streaming history.', 'medium'),
        ('St. Paul & The Broken Bones', 'Soul, Funk & R&B', None, [],
         'Birmingham retro-soul. 23 plays.', 'high'),
     ]),

    ('Country, Americana and folk',
     'Includes one direct family tie to an artist already in the collection.',
     [
        ('Sturgill Simpson', 'Country & Americana', None, [],
         'Modern outlaw country. 36 plays.', 'high'),
        ('Zach Bryan', 'Country & Americana', None, [],
         'Contemporary Americana. No streaming history.', 'medium'),
        ('Justin Townes Earle', 'Country & Americana', None,
         [('Folk & Singer-Songwriter', None)],
         'Steve Earle\'s son — Steve Earle and Steve Earle & The Dukes are '
         'both in the collection, so this wires straight into the existing '
         'Americana cluster. No streaming history.', 'high'),
        ('Jonah Tolchin', 'Country & Americana', None,
         [('Folk & Singer-Songwriter', None), ('Blues', None)],
         'Roots/blues singer-songwriter. 11 plays — barely over the floor.',
         'low'),
        ('All Them Witches', 'Rock', 'Indie & Alternative',
         [('Rock', 'Metal')],
         'Nashville psych/stoner rock. No streaming history.', 'medium'),
     ]),

    ('Prog and metal',
     'The cluster that motivates R1. Proposals below assume R1 option 1 '
     '(create Rock › Progressive for intake); if you pick a different R1, '
     'these follow it instead.',
     [
        ('Wobbler', 'Rock', 'Progressive', [('Rock', None)],
         'Norwegian retro-prog. No streaming history.', 'medium'),
        ('OSI', 'Rock', 'Progressive', [('Rock', 'Metal')],
         'Jim Matheos / Kevin Moore prog-metal project. 62 plays.', 'medium'),
        ('Blackfield', 'Rock', 'Progressive', [('Rock', 'Indie & Alternative')],
         'Steven Wilson and Aviv Geffen — art rock rather than heavy prog. '
         '16 plays.', 'medium'),
        ('Joey Eppard', 'Rock', 'Progressive', [('Rock', 'Indie & Alternative')],
         'Frontman of the band 3; acoustic-leaning prog. 50 plays.', 'medium'),
        ('Polyphia', 'Rock', 'Progressive', [('Rock', 'Metal')],
         'Instrumental prog / math rock. 39 plays.', 'medium'),
        ('Twelve Foot Ninja', 'Rock', 'Progressive', [('Rock', 'Metal')],
         'Australian genre-hopping prog metal. 10 plays — at the floor.',
         'low'),
        ('Type O Negative', 'Rock', 'Metal', [],
         'Gothic metal. Unambiguous. No streaming history.', 'high'),
     ]),

    ('Funk-jam, electronic and Latin',
     'The R2 cluster plus two singletons.',
     [
        ('The Motet', 'Rock', 'Jam', [('Soul, Funk & R&B', None)],
         'Colorado funk jam band. 578 plays — the most-streamed artist in the '
         'reservoir by a wide margin. Proposal follows R2 option 3.', 'medium'),
        ('The Main Squeeze', 'Rock', 'Jam', [('Soul, Funk & R&B', None)],
         'Funk-rock jam band. 50 plays. Proposal follows R2 option 3.',
         'medium'),
        ('The Filthy Six', 'Soul, Funk & R&B', None, [('Jazz', None)],
         'UK acid-jazz organ combo, no jam-scene connection. 67 plays. '
         'Proposal follows R2 option 3.', 'medium'),
        ('GRiZ', 'Electronic', None, [],
         'Bass/future-funk producer. 61 plays.', 'high'),
        ('Bad Bunny', 'Latin', None, [],
         'Reggaeton. Unambiguous genre; would be the 14th artist in Latin. '
         '36 plays.', 'high'),
     ]),
]


def esc(s):
    return html.escape(str(s), quote=True)


def cat_str(cat, sub):
    if not cat:
        return '—'
    return f'{cat} › {sub}' if sub else cat


def load_evidence():
    with open(INVENTORY) as f:
        inv = json.load(f)['artists']
    with open(STREAMING) as f:
        stream = {alnum(e['artist']): e for e in json.load(f)['artists']
                  if e.get('artist')}
    with open(FOLLOWS) as f:
        follows = json.load(f)['artists']

    # reservoir artists appearing as personnel on owned albums
    with open(CREDITS) as f:
        credits = json.load(f)
    reservoir = {alnum(n): n for n, r in inv.items()
                 if not r.get('discard') and not r.get('category')}
    ties = {}

    def walk(obj, path):
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, path + [k])
        elif isinstance(obj, list):
            for v in obj:
                walk(v, path)
        elif isinstance(obj, str):
            a = alnum(obj)
            if a in reservoir and len(a) > 4:
                owner = path[1] if len(path) > 1 else (path[0] if path else '')
                ties.setdefault(reservoir[a], set()).add(owner)

    walk(credits, [])
    return inv, stream, follows, ties


def evidence_cell(name, stream, follows, ties):
    bits = []
    e = stream.get(alnum(name))
    if e:
        bits.append(f'<span class="plays">{e["plays"]} plays</span>'
                    f'<span class="mins">{round(e.get("minutes") or 0)} min</span>')
    else:
        bits.append('<span class="noplay">no streaming history</span>')
    t = ties.get(name)
    if t:
        bits.append('<span class="tie">credits tie: '
                    + esc(', '.join(sorted(t)[:3])) + '</span>')
    fol = follows.get(name, {})
    if fol.get('followed_at'):
        bits.append(f'<span class="fol">followed '
                    f'{esc(str(fol["followed_at"])[:10])}</span>')
    return ''.join(bits)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=DEFAULT_OUT)
    args = ap.parse_args()

    inv, stream, follows, ties = load_evidence()
    reservoir = {n for n, r in inv.items()
                 if not r.get('discard') and not r.get('category')}

    listed = {a for _t, _b, items in GROUPS for a, *_ in items}
    missing = sorted(reservoir - listed)
    extra = sorted(listed - reservoir)
    if extra:
        sys.exit(f'ABORT — proposed for artists not in the reservoir: {extra}')

    tax_html = []
    for t in TAXONOMY:
        opts = []
        for i, (label, detail) in enumerate(t['options']):
            rec = (' <span class="badge rec">recommended</span>'
                   if i == t['recommended'] else '')
            opts.append(
                f'<label class="opt"><input type="radio" name="{t["id"]}" '
                f'value="{i}"><span class="opt-body">'
                f'<span class="opt-label">{esc(label)}{rec}</span>'
                f'<span class="opt-detail">{esc(detail)}</span></span></label>')
        affects = ''
        if t.get('affects'):
            chips = ' '.join(f'<span class="chip">{esc(a)}</span>'
                             for a in t['affects'])
            affects = ('<div class="affects"><span class="affects-label">'
                       'Affects</span>' + chips + '</div>')
        tax_html.append(f'''
    <article class="card" data-decision="{t['id']}">
      <div class="card-head"><span class="tag">{t['id']}</span>
        <h3>{esc(t['title'])}</h3></div>
      <p class="card-body">{esc(t['body'])}</p>
      <div class="opts">{''.join(opts)}
        <label class="opt"><input type="radio" name="{t['id']}" value="other">
          <span class="opt-body"><span class="opt-label">Something else</span>
          <input type="text" class="other-text" name="{t['id']}__other"
                 placeholder="your call…"></span></label>
      </div>{affects}
    </article>''')

    grp_html = []
    n_total = n_low = 0
    for gi, (title, blurb, items) in enumerate(GROUPS):
        rows = []
        for artist, pcat, psub, alts, why, conf in items:
            n_total += 1
            if conf == 'low':
                n_low += 1
            rid = f'R{gi}_{esc(artist).replace(" ", "_")[:40]}'
            prop = cat_str(pcat, psub)
            tag_checked = '' if conf == 'low' else ' checked'
            skip_checked = ' checked' if conf == 'low' else ''
            alt_opts = ''.join(
                f'<label class="opt sm"><input type="radio" name="{rid}" '
                f'value="alt:{esc(cat_str(ac, asub))}">'
                f'<span class="opt-label">{esc(cat_str(ac, asub))}</span>'
                f'</label>' for ac, asub in alts)
            rows.append(f'''
        <tr data-artist="{esc(artist)}" data-prop="{esc(prop)}" data-conf="{conf}">
          <td class="c-artist"><strong>{esc(artist)}</strong>
            <span class="conf conf-{conf}">{conf}</span></td>
          <td class="c-ev">{evidence_cell(artist, stream, follows, ties)}</td>
          <td class="c-move"><span class="to">{esc(prop)}</span>
            <p class="why">{esc(why)}</p></td>
          <td class="c-choice">
            <label class="opt sm"><input type="radio" name="{rid}"
              value="tag"{tag_checked}><span class="opt-label">Tag as proposed</span></label>
            {alt_opts}
            <label class="opt sm"><input type="radio" name="{rid}"
              value="skip"{skip_checked}><span class="opt-label">Leave untagged</span></label>
            <label class="opt sm"><input type="radio" name="{rid}" value="other">
              <span class="opt-label">Other</span></label>
            <input type="text" class="other-text row-other" name="{rid}__other"
                   placeholder="category › subcategory">
          </td>
        </tr>''')
        grp_html.append(f'''
    <section class="group"><h3>{esc(title)}</h3>
      <p class="blurb">{esc(blurb)}</p>
      <div class="table-wrap"><table>
      <thead><tr><th>Artist</th><th>Evidence</th><th>Proposed</th>
        <th>Your call</th></tr></thead>
      <tbody>{''.join(rows)}</tbody></table></div>
    </section>''')

    page = TEMPLATE.format(
        n_total=n_total,
        n_low=n_low,
        n_tax=len(TAXONOMY),
        n_nostream=sum(1 for a in listed if alnum(a) not in stream),
        taxonomy=''.join(tax_html),
        groups=''.join(grp_html),
    )
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, 'w') as f:
        f.write(page)
    print(f'wrote {args.out}')
    print(f'  reservoir artists: {n_total}  (all {len(reservoir)} covered)')
    print(f'  defaulting to "leave untagged": {n_low}')
    if missing:
        print(f'  WARNING uncovered: {missing}')


TEMPLATE = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Music collection — reservoir intake</title>
<style>
  :root {{ --bg:#faf9f7; --panel:#fff; --ink:#1a1a1a; --muted:#6b6b6b;
    --line:#e2ded8; --accent:#2f5d7c; --accent-soft:#e8eff4;
    --to:#2f6b4f; --warn:#b8860b; --from:#a3453a; --rad:10px; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#17161a; --panel:#1f1e23; --ink:#ece9e4; --muted:#9a958d;
      --line:#33313a; --accent:#7fb0d4; --accent-soft:#242c33;
      --to:#7fc4a0; --warn:#d9b45c; --from:#e08b7f; }}
  }}
  :root[data-theme="dark"] {{ --bg:#17161a; --panel:#1f1e23; --ink:#ece9e4;
    --muted:#9a958d; --line:#33313a; --accent:#7fb0d4; --accent-soft:#242c33;
    --to:#7fc4a0; --warn:#d9b45c; --from:#e08b7f; }}
  :root[data-theme="light"] {{ --bg:#faf9f7; --panel:#fff; --ink:#1a1a1a;
    --muted:#6b6b6b; --line:#e2ded8; --accent:#2f5d7c; --accent-soft:#e8eff4;
    --to:#2f6b4f; --warn:#b8860b; --from:#a3453a; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink); padding-bottom:5rem;
    font:15px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif; }}
  .wrap {{ max-width:1180px; margin:0 auto; padding:2rem 1.25rem; }}
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
  h2 .n {{ color:var(--muted); font-weight:400; letter-spacing:0;
    text-transform:none; }}
  .lead {{ color:var(--muted); margin:0 0 1.25rem; max-width:74ch; }}
  .card {{ background:var(--panel); border:1px solid var(--line);
    border-radius:var(--rad); padding:1.1rem 1.2rem; margin-bottom:.9rem; }}
  .card-head {{ display:flex; align-items:baseline; gap:.6rem; }}
  .card-head h3 {{ margin:0 0 .4rem; font-size:1.05rem; }}
  .tag {{ background:var(--accent-soft); color:var(--accent); font-weight:700;
    font-size:.72rem; padding:.18rem .45rem; border-radius:5px; }}
  .card-body {{ margin:0 0 .9rem; color:var(--muted); max-width:80ch; }}
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
    font-weight:700; letter-spacing:.04em; vertical-align:.1em; }}
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
  .group {{ margin-bottom:2rem; }}
  .group h3 {{ font-size:1.02rem; margin:0 0 .3rem; }}
  .blurb {{ color:var(--muted); margin:0 0 .8rem; max-width:80ch;
    font-size:.9rem; }}
  .table-wrap {{ overflow-x:auto; border:1px solid var(--line);
    border-radius:var(--rad); background:var(--panel); }}
  table {{ border-collapse:collapse; width:100%; min-width:900px; }}
  th {{ text-align:left; font-size:.74rem; text-transform:uppercase;
    letter-spacing:.07em; color:var(--muted); font-weight:600;
    padding:.7rem .8rem; border-bottom:1px solid var(--line);
    background:var(--bg); }}
  td {{ padding:.8rem; border-bottom:1px solid var(--line);
    vertical-align:top; font-size:.9rem; }}
  tr:last-child td {{ border-bottom:0; }}
  .c-artist {{ width:17%; }} .c-ev {{ width:20%; }}
  .c-move {{ width:38%; }} .c-choice {{ width:25%; }}
  .c-ev span {{ display:block; font-size:.8rem; margin-bottom:.15rem; }}
  .plays {{ color:var(--to); font-weight:700; }}
  .mins, .fol {{ color:var(--muted); }}
  .noplay {{ color:var(--warn); font-style:italic; }}
  .tie {{ color:var(--accent); }}
  .to {{ color:var(--to); font-weight:600; }}
  .why {{ margin:.4rem 0 0; color:var(--muted); font-size:.84rem; }}
  .conf {{ display:inline-block; font-size:.66rem; text-transform:uppercase;
    letter-spacing:.05em; padding:.1rem .35rem; border-radius:4px;
    margin-left:.3rem; font-weight:700; vertical-align:.08em; }}
  .conf-high {{ background:rgba(47,107,79,.16); color:var(--to); }}
  .conf-medium {{ background:rgba(184,134,11,.18); color:var(--warn); }}
  .conf-low {{ background:rgba(163,69,58,.15); color:var(--from); }}
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
  dialog textarea {{ width:calc(100% - 2.4rem); margin:.8rem 1.2rem;
    height:46vh; background:var(--bg); color:var(--ink);
    border:1px solid var(--line); border-radius:7px; padding:.7rem;
    font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
    font-size:.82rem; resize:vertical; }}
  .dlg-foot {{ padding:0 1.2rem 1.1rem; display:flex; gap:.6rem; }}
  @media (max-width:720px) {{ .wrap {{ padding:1.25rem .85rem; }}
    h1 {{ font-size:1.4rem; }} }}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>Music collection — reservoir intake</h1>
  <p class="sub">First categorization for the {n_total} untagged Spotify
  follows. These own no albums, so the evidence is streaming history, credits
  ties into owned albums, and the follow itself. The repo rule is that leaving
  an artist untagged beats mistagging it — so the {n_low} weakest rows default
  to <strong>leave untagged</strong>, and everything else defaults to the
  proposal.</p>
</header>

<div class="stats">
  <div class="stat"><b>{n_total}</b><span>follows to triage</span></div>
  <div class="stat"><b>{n_tax}</b><span>taxonomy calls</span></div>
  <div class="stat"><b>{n_nostream}</b><span>no streaming history</span></div>
  <div class="stat"><b>{n_low}</b><span>default to untagged</span></div>
</div>

<h2>1 · Taxonomy <span class="n">— decide these first</span></h2>
<p class="lead">Two genuine gaps the reservoir exposed, plus one question
about how much evidence a follow is worth.</p>
{taxonomy}

<h2>2 · Artist intake <span class="n">— {n_total} follows</span></h2>
<p class="lead">Evidence column shows what the data actually knows about each
one. Play counts come from the GDPR export; credits ties mean the artist
appears as personnel on an album you own, which is a real graph edge rather
than a guess.</p>
{groups}
</div>

<div class="bar">
  <button class="primary" id="copy">Copy decisions</button>
  <button id="tagall">Tag all as proposed</button>
  <button id="skipall">Leave all untagged</button>
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
const KEY='music-reservoir-v1';
const $=s=>document.querySelector(s);
function save(){{
  const d={{}};
  document.querySelectorAll('input[type=radio]:checked').forEach(r=>d[r.name]=r.value);
  document.querySelectorAll('input.other-text').forEach(t=>{{if(t.value)d[t.name]=t.value;}});
  localStorage.setItem(KEY,JSON.stringify(d));
  const rows=[...document.querySelectorAll('tr[data-artist] input[type=radio]:checked')];
  const tagged=rows.filter(r=>r.value!=='skip').length;
  const tax=document.querySelectorAll('.card[data-decision] input[type=radio]:checked').length;
  const nTax=document.querySelectorAll('.card[data-decision]').length;
  $('#status').textContent=`taxonomy ${{tax}}/${{nTax}} · ${{tagged}} to tag, ${{rows.length-tagged}} staying in the reservoir`;
}}
function restore(){{
  let d; try{{d=JSON.parse(localStorage.getItem(KEY)||'{{}}');}}catch(e){{return;}}
  for(const [n,v] of Object.entries(d)){{
    if(n.endsWith('__other')){{
      const t=document.querySelector(`input[name="${{CSS.escape(n)}}"]`);
      if(t)t.value=v;
    }} else {{
      const r=document.querySelector(`input[name="${{CSS.escape(n)}}"][value="${{CSS.escape(v)}}"]`);
      if(r)r.checked=true;
    }}
  }}
}}
function build(){{
  const L=['# Reservoir intake — decisions',''];
  L.push('## Taxonomy');
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
  L.push('','## Intake');
  document.querySelectorAll('tr[data-artist]').forEach(tr=>{{
    const s=tr.querySelector('input[type=radio]:checked');
    if(!s)return;
    const a=tr.dataset.artist, p=tr.dataset.prop;
    if(s.value==='tag') L.push(`- ${{a}}: TAG → ${{p}}`);
    else if(s.value==='skip') L.push(`- ${{a}}: LEAVE UNTAGGED`);
    else if(s.value==='other'){{
      const t=tr.querySelector('.row-other');
      L.push(`- ${{a}}: OTHER → ${{(t&&t.value)||'(blank)'}}`);
    }} else if(s.value.startsWith('alt:')) L.push(`- ${{a}}: ALT → ${{s.value.slice(4)}}`);
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
$('#tagall').onclick=()=>{{document.querySelectorAll('tr[data-artist] input[value=tag]')
  .forEach(r=>r.checked=true);save();}};
$('#skipall').onclick=()=>{{document.querySelectorAll('tr[data-artist] input[value=skip]')
  .forEach(r=>r.checked=true);save();}};
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
