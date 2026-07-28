#!/usr/bin/env python3
"""Render the album-title repair worksheet for pub.lan.

Fourth in the family. The three previous passes worked on artist records; this
one works on album titles, which carry a different kind of damage: the library
was ripped by tooling that truncated at 40 characters, substituted characters
Windows forbids in filenames (: ? " * become _ or -), and sometimes wrote the
folder name instead of the title.

Album titles are the join key for credits.json, so every rename here has to
carry there too — 90 of its 1668 artist/album keys are damaged titles.

    python build_title_sheet.py [--out /mnt/lentago/web/music-titles/index.html]
"""
import argparse
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dedup_lib import album_key  # noqa: E402

INVENTORY = os.path.join(HERE, 'data', 'music-inventory.json')
CREDITS = os.path.join(HERE, 'data', 'credits.json')
DEFAULT_OUT = '/mnt/lentago/web/music-titles/index.html'

RULES = [
    dict(id='S1', title='Placeholder and non-album entries',
         body='Twelve albums are literally titled "Unknown Album" (four with a '
              'rip timestamp appended), two are "Torrent downloaded from '
              'Demonoid.com.txt", one is "Dub Kweli - tracklist and '
              'information.txt", and one is "Amazon MP3". None is a record. '
              'They inflate album_count and appear in the vault as albums.',
         options=[('Drop them all',
                   'They carry no information. album_count drops accordingly '
                   'and the vault stops listing phantom records.'),
                  ('Keep them as evidence the rip is incomplete',
                   'A visible "Unknown Album" is a reminder that something '
                   'was not identified.'),
                  ('Drop the .txt and Amazon MP3 entries, keep Unknown Album',
                   'Removes the definitely-not-music entries while leaving '
                   'the unidentified-rip markers.')],
         recommended=0),
    dict(id='S2', title='Truncated copies whose full title is already present',
         body='25 albums appear twice under the same artist: once complete and '
              'once cut at exactly 40 characters. This is the same class of '
              'duplication the merge pass fixed at artist level, one tier '
              'down. Billy Bragg has three rips of one album, two of them '
              'truncated.',
         options=[('Drop the truncated copy, keep the full title',
                   'No information is lost — the full title is right there.'),
                  ('Keep both', 'Preserves the raw rip listing.')],
         recommended=0),
    dict(id='S3', title='Filename-style titles',
         body='23 titles are lowercase with underscores for spaces — '
              'hail_to_the_thief, nothing\'s_shocking, dos_dedos_mis_amigos. '
              'These are folder names, not titles. A few are genuine '
              'stylizations though: cLOUDDEAD\'s "clouddead", A Perfect '
              'Circle\'s "eMOTIVe".',
         options=[('Restore normal title case, preserving known stylizations',
                   'hail_to_the_thief becomes "Hail to the Thief"; '
                   '"eMOTIVe" and "cLOUDDEAD" keep their intentional casing.'),
                  ('Restore title case mechanically',
                   'Simpler, but flattens the deliberate stylizations.'),
                  ('Leave them', 'They are recognisable as-is.')],
         recommended=0),
    dict(id='S4', title='Characters Windows forbids in filenames',
         body='The ripper replaced : ? " and * with _ or -. So "Spy Vs. Spy_ '
              'The Music of Ornette Coleman" wants a colon, and Metric\'s '
              '"Old World Underground, Where Are You Now" is complete except '
              'for a lost question mark. This affects roughly 30 titles, '
              'including ones not otherwise damaged.',
         options=[('Restore the punctuation where it is unambiguous',
                   'Colons before subtitles, question marks where the title '
                   'is a question. Leave anything uncertain alone.'),
                  ('Leave them',
                   'The substitution is legible and restoring it means '
                   'guessing at some titles.')],
         recommended=0),
    dict(id='S5', title='Should credits.json follow the renames?',
         body='credits.json is keyed by album title, and 90 of its 1668 '
              'artist/album keys are damaged titles. If the inventory is '
              'repaired and credits is not, the personnel research silently '
              'detaches from the albums it describes.',
         options=[('Yes — rename in both, in the same pass',
                   'Same discipline the merge pass used for artist keys.'),
                  ('Repair the inventory only',
                   'Leaves credits keyed on damaged titles; the join breaks.')],
         recommended=0),
]

# Titles with no surviving full-title sibling. Each needs a reconstruction,
# which is external knowledge rather than something the data can supply.
RECONSTRUCT = [
    ('Explosions In The Sky', 'Those Who Tell the Truth Shall Die, Thos',
     'Those Who Tell the Truth Shall Die, Those Who Tell the Truth Shall Live '
     'Forever', 'high', 'Well-known full title; the truncation is mid-word.'),
    ('Mew', "No More Stories Are Told Today I'm Sorry",
     "No More Stories Are Told Today, I'm Sorry They Washed Away // No More "
     "Stories, The World Is Grey, I'm Tired, Let's Wash Away", 'high',
     'The real title is famously long; 40 characters is a small fraction.'),
    ('Ray Charles', 'Modern Sounds in Country and Western Mus',
     'Modern Sounds in Country and Western Music, Vols 1 & 2', 'high',
     'Two damaged rips of one album. A sibling exists — "Modern SoundsIn '
     'Country And Western Music, Vols 1 & 2" — but the automatic scan missed '
     'the pairing because that sibling is itself damaged (a missing space in '
     '"SoundsIn"). Applying here drops the truncated copy AND repairs the '
     'survivor to the clean title shown.'),
    ('The Neville Brothers', "Uptown Rulin'_ The Best of the Neville B",
     "Uptown Rulin': The Best of the Neville Brothers", 'high',
     'Truncation plus a substituted colon.'),
    ('The Pogues', 'If I Should Fall From Grace With God [Ex',
     'If I Should Fall From Grace With God [Expanded]', 'high',
     'The bracket is left open by the cut.'),
    ('The Smithereens', 'From Jersey It Came! The Smithereens Ant',
     'From Jersey It Came! The Smithereens Anthology', 'high',
     'Note the same artist also holds "Anthology_ From Jersey It Came" — a '
     'differently-ordered rip of the same compilation, so this may be a '
     'duplicate to drop rather than a repair.'),
    ('James Brown', 'The CD Of JB (Sex Machine & Other Soul C',
     'The CD Of JB (Sex Machine & Other Soul Classics)', 'medium',
     'Unbalanced parenthesis confirms truncation; the closing text is a guess.'),
    ('John Zorn', 'Astaroth_ Book Of Angels Volume One - Ja',
     'Astaroth: Book Of Angels Volume One - Jamie Saft Trio', 'medium',
     'Book of Angels Vol. 1 was recorded by the Jamie Saft Trio.'),
    ('Cracow Klezmer Band', 'Masada Book II - The Book Of Angels - Vo',
     'Masada Book II - The Book Of Angels - Vol. 5: Balan', 'medium',
     'Cracow Klezmer Band recorded Balan, Book of Angels Vol. 5.'),
    ('Imogen Heap', 'Various Artists - New Dawn (Class of 94}',
     'Various Artists - New Dawn (Class of 94)', 'medium',
     'Not truncated — the closing brace is a typo for a parenthesis. Also '
     'note this is a various-artists compilation filed under Imogen Heap.'),
    ('Metric', 'Old World Underground, Where Are You Now',
     'Old World Underground, Where Are You Now?', 'high',
     'Complete apart from the question mark the ripper stripped.'),
    ('Beth Orton', 'Pass in Time - The Definitive Collection',
     'Pass in Time: The Definitive Collection', 'medium',
     'Not truncated — the dash stands in for a colon.'),
    ('Paul Simon', 'The Rhythm Of The Saints (2011 Remaster)',
     'The Rhythm Of The Saints (2011 Remaster)', 'high',
     'False positive: exactly 40 characters but complete and balanced. No '
     'change proposed.'),
    ('Ray Charles', 'Ray - Original Motion Picture Soundtrack',
     'Ray - Original Motion Picture Soundtrack', 'medium',
     'Complete, but the same artist also holds "Ray [Original Soundtrack]" '
     'and "More Music from Ray Disc 1" — possibly the same release ripped '
     'more than once. Left alone unless you want them reconciled.'),
    ('David Grisman Quintet', '1',
     '1', 'low',
     'The artist\'s only album, titled "1". The debut is "The David Grisman '
     'Quintet" and there is also a "DGQ-20"; this is probably a damaged '
     'folder name but there is nothing in the data to recover it from. '
     'Recommend leaving it and checking the actual files.'),
    ('Warren Zevon - I\'ll Sleep When I\'m Dead (An Anthology)', 'Disc 1',
     "I'll Sleep When I'm Dead (An Anthology) Disc 1", 'high',
     'Bare disc numbers, same as the White Album case the merge pass '
     'repaired. Applies to Disc 2 as well.'),
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

    rows = [(n, t) for n, x in inv.items() if not x.get('discard')
            for t in (x.get('albums') or [])]

    JUNK = re.compile(r'\.txt$|^Unknown Album|^Amazon MP3$', re.I)
    junk = sorted((n, t) for n, t in rows if JUNK.search(t))

    dup_trunc = []
    for n, x in inv.items():
        if x.get('discard'):
            continue
        al = x.get('albums') or []
        keys = {t: album_key(t) for t in al}
        for t in al:
            if len(t) != 40:
                continue
            sib = [u for u in al if u != t and keys[u].startswith(keys[t])]
            if sib:
                dup_trunc.append((n, t, max(sib, key=len)))
    dup_trunc.sort()

    fn = re.compile(r'^[a-z0-9][a-z0-9_\'\-\.\(\)]*$')
    filename = sorted((n, t) for n, t in rows
                      if fn.match(t) and ('_' in t or t.islower()))

    subst = sorted({(n, t) for n, t in rows if '_' in t and not fn.match(t)})

    cred_damaged = sum(
        1 for a, albums in credits.items() for t in albums
        if len(t) == 40 or t.startswith('Unknown Album') or t.endswith('.txt')
        or (t.islower() and '_' in t))

    def listing(items, cap=None):
        shown = items if cap is None else items[:cap]
        out = ''.join(f'<li><span class="art">{esc(n)}</span>'
                      f'<span class="ttl">{esc(t)}</span></li>'
                      for n, t, *_ in shown)
        if cap and len(items) > cap:
            out += f'<li class="more">+{len(items) - cap} more</li>'
        return f'<ul class="titles">{out}</ul>'

    EVIDENCE = {
        'S1': listing(junk),
        'S2': ''.join(
            f'<li><span class="art">{esc(n)}</span>'
            f'<span class="ttl bad">{esc(t)}</span>'
            f'<span class="ttl good">keep: {esc(s)}</span></li>'
            for n, t, s in dup_trunc),
        'S3': listing(filename),
        'S4': listing(subst, cap=14),
        'S5': '',
    }

    def card(d):
        opts = ''.join(
            f'<label class="opt"><input type="radio" name="{d["id"]}" value="{i}">'
            f'<span class="opt-body"><span class="opt-label">{esc(lab)}'
            + (' <span class="badge rec">recommended</span>'
               if i == d['recommended'] else '')
            + f'</span><span class="opt-detail">{esc(det)}</span></span></label>'
            for i, (lab, det) in enumerate(d['options']))
        ev = EVIDENCE.get(d['id'], '')
        if ev:
            body = ev if ev.startswith('<ul') else f'<ul class="titles">{ev}</ul>'
            ev = (f'<details class="ev"><summary>show the affected titles'
                  f'</summary>{body}</details>')
        return (f'<article class="card" data-decision="{d["id"]}">'
                f'<div class="card-head"><span class="tag">{d["id"]}</span>'
                f'<h3>{esc(d["title"])}</h3></div>'
                f'<p class="card-body">{esc(d["body"])}</p>'
                f'<div class="opts">{opts}'
                f'<label class="opt"><input type="radio" name="{d["id"]}" value="other">'
                f'<span class="opt-body"><span class="opt-label">Something else</span>'
                f'<input type="text" class="other-text" name="{d["id"]}__other"'
                f' placeholder="your call…"></span></label></div>{ev}</article>')

    rec_rows = []
    for i, (art, cur, prop, conf, why) in enumerate(RECONSTRUCT):
        rid = f'T{i}'
        nochange = cur == prop
        rec_rows.append(f'''
      <tr data-artist="{esc(art)}" data-cur="{esc(cur)}" data-prop="{esc(prop)}">
        <td class="c-art">{esc(art)}<span class="conf conf-{conf}">{conf}</span></td>
        <td class="c-cur"><code>{esc(cur)}</code></td>
        <td class="c-new">'''
                        + (f'<em class="nochange">no change proposed</em>'
                           if nochange else f'<code>{esc(prop)}</code>')
                        + f'''<p class="why">{esc(why)}</p></td>
        <td class="c-choice">
          <label class="opt sm"><input type="radio" name="{rid}" value="apply"
            {'' if nochange else 'checked'}><span class="opt-label">Apply</span></label>
          <label class="opt sm"><input type="radio" name="{rid}" value="leave"
            {'checked' if nochange else ''}><span class="opt-label">Leave as-is</span></label>
          <label class="opt sm"><input type="radio" name="{rid}" value="drop">
            <span class="opt-label">Drop the entry</span></label>
          <label class="opt sm"><input type="radio" name="{rid}" value="other">
            <span class="opt-label">Other</span></label>
          <input type="text" class="other-text row-other" name="{rid}__other"
                 placeholder="correct title">
        </td>
      </tr>''')

    page = TEMPLATE.format(
        n_titles=len(rows), n_junk=len(junk), n_dup=len(dup_trunc),
        n_fn=len(filename), n_subst=len(subst), n_rec=len(RECONSTRUCT),
        n_cred=cred_damaged, n_rules=len(RULES),
        n_flagged=len(junk) + len(dup_trunc) + len(filename) + len(RECONSTRUCT),
        rules=''.join(card(d) for d in RULES),
        rec_rows=''.join(rec_rows),
    )
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, 'w') as f:
        f.write(page)
    print(f'wrote {args.out}')
    print(f'  live titles {len(rows)} | junk {len(junk)} | trunc-dupes '
          f'{len(dup_trunc)} | filename-style {len(filename)} | '
          f'underscore {len(subst)} | reconstructions {len(RECONSTRUCT)}')
    print(f'  damaged credits keys: {cred_damaged}')


TEMPLATE = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Music collection — album title repair</title>
<style>
  :root {{ --bg:#faf9f7; --panel:#fff; --ink:#1a1a1a; --muted:#6b6b6b;
    --line:#e2ded8; --accent:#2f6b5c; --accent-soft:#e6f0ec;
    --to:#2f6b4f; --warn:#b8860b; --from:#a3453a; --rad:10px; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#17161a; --panel:#1f1e23; --ink:#ece9e4; --muted:#9a958d;
      --line:#33313a; --accent:#7fc4b0; --accent-soft:#212c29;
      --to:#7fc4a0; --warn:#d9b45c; --from:#e08b7f; }} }}
  :root[data-theme="dark"] {{ --bg:#17161a; --panel:#1f1e23; --ink:#ece9e4;
    --muted:#9a958d; --line:#33313a; --accent:#7fc4b0; --accent-soft:#212c29;
    --to:#7fc4a0; --warn:#d9b45c; --from:#e08b7f; }}
  :root[data-theme="light"] {{ --bg:#faf9f7; --panel:#fff; --ink:#1a1a1a;
    --muted:#6b6b6b; --line:#e2ded8; --accent:#2f6b5c; --accent-soft:#e6f0ec;
    --to:#2f6b4f; --warn:#b8860b; --from:#a3453a; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink); padding-bottom:5rem;
    font:15px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif; }}
  .wrap {{ max-width:1200px; margin:0 auto; padding:2rem 1.25rem; }}
  h1 {{ font-size:1.75rem; margin:0 0 .35rem; letter-spacing:-.02em; }}
  .sub {{ color:var(--muted); margin:0 0 1.5rem; max-width:74ch; }}
  code {{ background:var(--accent-soft); padding:.08rem .3rem;
    border-radius:4px; font-size:.86em; word-break:break-word; }}
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
  .lead {{ color:var(--muted); margin:0 0 1.25rem; max-width:78ch; }}
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
    font:inherit; font-size:.85rem; width:100%; max-width:26rem; }}
  details.ev {{ margin-top:.9rem; padding-top:.75rem;
    border-top:1px dashed var(--line); }}
  details.ev summary {{ cursor:pointer; color:var(--accent); font-size:.85rem;
    font-weight:600; }}
  ul.titles {{ list-style:none; padding:0; margin:.6rem 0 0; }}
  ul.titles li {{ display:flex; flex-wrap:wrap; gap:.5rem; padding:.22rem 0;
    border-bottom:1px solid var(--line); font-size:.82rem; }}
  ul.titles li:last-child {{ border-bottom:0; }}
  .art {{ color:var(--muted); min-width:13rem; }}
  .ttl {{ font-family:ui-monospace,Menlo,monospace; }}
  .ttl.bad {{ color:var(--from); }} .ttl.good {{ color:var(--to); }}
  .more {{ color:var(--muted); font-style:italic; }}
  .table-wrap {{ overflow-x:auto; border:1px solid var(--line);
    border-radius:var(--rad); background:var(--panel); }}
  table {{ border-collapse:collapse; width:100%; min-width:980px; }}
  th {{ text-align:left; font-size:.74rem; text-transform:uppercase;
    letter-spacing:.07em; color:var(--muted); font-weight:600;
    padding:.7rem .8rem; border-bottom:1px solid var(--line);
    background:var(--bg); }}
  td {{ padding:.75rem .8rem; border-bottom:1px solid var(--line);
    vertical-align:top; font-size:.88rem; }}
  tr:last-child td {{ border-bottom:0; }}
  .c-art {{ width:15%; }} .c-cur {{ width:24%; }} .c-new {{ width:38%; }}
  .c-choice {{ width:23%; }}
  .why {{ margin:.4rem 0 0; color:var(--muted); font-size:.83rem; }}
  .nochange {{ color:var(--muted); }}
  .conf {{ display:inline-block; font-size:.64rem; text-transform:uppercase;
    letter-spacing:.05em; padding:.08rem .32rem; border-radius:4px;
    margin-left:.35rem; font-weight:700; }}
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
  dialog textarea {{ width:calc(100% - 2.4rem); margin:.8rem 1.2rem; height:46vh;
    background:var(--bg); color:var(--ink); border:1px solid var(--line);
    border-radius:7px; padding:.7rem; font-family:ui-monospace,Menlo,monospace;
    font-size:.82rem; resize:vertical; }}
  .dlg-foot {{ padding:0 1.2rem 1.1rem; display:flex; gap:.6rem; }}
  @media (max-width:720px) {{ .wrap {{ padding:1.25rem .85rem; }}
    h1 {{ font-size:1.4rem; }} .art {{ min-width:0; }} }}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>Music collection — album title repair</h1>
  <p class="sub">The library was ripped by tooling that cut titles at exactly
  40 characters, replaced the characters Windows forbids in filenames
  (<code>:</code> <code>?</code> <code>"</code> <code>*</code>) with
  <code>_</code> or <code>-</code>, and sometimes wrote a folder name where a
  title belongs. <strong>{n_flagged}</strong> of {n_titles} live album titles
  carry some form of this damage. Album titles are also the join key for
  <code>credits.json</code>, where <strong>{n_cred}</strong> keys are damaged —
  so repairs have to carry across both files or the personnel research
  detaches from the albums it describes.</p>
</header>

<div class="stats">
  <div class="stat"><b>{n_dup}</b><span>truncated duplicates</span></div>
  <div class="stat"><b>{n_fn}</b><span>filename-style</span></div>
  <div class="stat"><b>{n_junk}</b><span>non-album entries</span></div>
  <div class="stat"><b>{n_rec}</b><span>need reconstruction</span></div>
  <div class="stat"><b>{n_cred}</b><span>damaged credits keys</span></div>
</div>

<h2>1 · Rules <span class="n">— {n_rules} classes, each covering many titles</span></h2>
<p class="lead">Each rule decides a whole damage class at once. Expand
<em>show the affected titles</em> to see exactly what it touches before
choosing.</p>
{rules}

<h2>2 · One-off reconstructions <span class="n">— {n_rec} titles the data cannot recover</span></h2>
<p class="lead">These are truncated with no surviving full-title sibling, so
the repair is external knowledge rather than something the collection can
supply — the same kind of call the categorization pass involved. Two rows are
false positives left in deliberately so you can see them, and one is
unrecoverable.</p>
<div class="table-wrap"><table>
<thead><tr><th>Artist</th><th>Current</th><th>Proposed</th><th>Your call</th></tr></thead>
<tbody>{rec_rows}</tbody></table></div>
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
const KEY='music-titles-v1';
const $=s=>document.querySelector(s);
function save(){{
  const d={{}};
  document.querySelectorAll('input[type=radio]:checked').forEach(r=>d[r.name]=r.value);
  document.querySelectorAll('input.other-text').forEach(t=>{{if(t.value)d[t.name]=t.value;}});
  localStorage.setItem(KEY,JSON.stringify(d));
  const cards=document.querySelectorAll('.card[data-decision]').length;
  const done=document.querySelectorAll('.card[data-decision] input[type=radio]:checked').length;
  const rows=[...document.querySelectorAll('tr[data-artist] input[type=radio]:checked')];
  const applying=rows.filter(r=>r.value==='apply').length;
  $('#status').textContent=`rules ${{done}}/${{cards}} · ${{applying}} of ${{rows.length}} titles to repair`;
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
  const L=['# Album title repair — decisions',''];
  L.push('## Rules');
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
  L.push('','## Reconstructions');
  document.querySelectorAll('tr[data-artist]').forEach(tr=>{{
    const s=tr.querySelector('input[type=radio]:checked'); if(!s)return;
    const a=tr.dataset.artist, cur=tr.dataset.cur, prop=tr.dataset.prop;
    if(s.value==='apply') L.push(`- ${{a}} | ${{cur}}  →  ${{prop}}`);
    else if(s.value==='leave') L.push(`- ${{a}} | ${{cur}}  →  LEAVE`);
    else if(s.value==='drop') L.push(`- ${{a}} | ${{cur}}  →  DROP`);
    else if(s.value==='other'){{
      const t=tr.querySelector('.row-other');
      L.push(`- ${{a}} | ${{cur}}  →  ${{(t&&t.value)||'(blank)'}}`);
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
