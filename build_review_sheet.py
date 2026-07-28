#!/usr/bin/env python3
"""Render the categorization-review worksheet for pub.lan.

Reads data/music-inventory.json for the current state and owned-album evidence,
merges it with the reviewer's decision list below, and writes a self-contained
HTML page. Decisions are recorded client-side and exported as a compact text
block to paste back into the curation session.

    python build_review_sheet.py [--out /mnt/lentago/web/music-categories/index.html]
"""
import argparse
import html
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
INVENTORY = os.path.join(HERE, 'data', 'music-inventory.json')
DEFAULT_OUT = '/mnt/lentago/web/music-categories/index.html'

# ---------------------------------------------------------------------------
# Already applied — Tier A, factual corrections with a verifiable answer.
# ---------------------------------------------------------------------------
APPLIED = [
    ('Wrecking Crew', 'Pop', 'Rock › Punk & Hardcore',
     'Misidentified band. The owned tracklist (Guts and Glory, My Mind\'s '
     'Diseased, 14 short tracks) is the Boston hardcore band\'s Balance of '
     'Terror (1988), not the LA session collective. Era corrected to 1980s.'),
    ('New Grass Revival', 'C&A › Bluegrass', 'C&A › Newgrass',
     'They are the namesake of the Newgrass subcategory.'),
    ('Muddy Waters_Dizzy Gillespie', 'Jazz', 'Blues',
     'Album is "Muddy Waters Blues Band Featuring Dizzy Gillespie"; the '
     'Muddy Waters solo entry is already Blues.'),
    ('Mark Knopfler And Emmylou Harris', 'Blues', 'Country & Americana',
     'All the Roadrunning is a country duet record; both principals are '
     'filed Country & Americana.'),
    ('William S. Burroughs', 'Pop › Art-Pop & New Wave',
     'Avant-Garde & Experimental', 'Spoken-word / beat literature.'),
    ('Bonobo', 'Hip-Hop › Turntablism & Beats', 'Electronic › Trip-Hop & Downtempo',
     'Downtempo producer, not a turntablist.'),
    ('Emancipator', 'Hip-Hop › Turntablism & Beats', 'Electronic › Trip-Hop & Downtempo',
     'Downtempo producer, not a turntablist.'),
    ('Tor', 'Hip-Hop › Turntablism & Beats', 'Electronic › Trip-Hop & Downtempo',
     'Downtempo producer, not a turntablist.'),
    ('Eskmo', 'Hip-Hop › Turntablism & Beats', 'Electronic',
     'Experimental bass/electronic producer. Left without a subcategory — '
     'confirm whether Trip-Hop & Downtempo fits.'),
    ('dangerdoom', 'Hip-Hop › Turntablism & Beats', 'Hip-Hop › Underground',
     'MC-fronted rap album (DOOM over Danger Mouse), not turntablism.'),
    ('Madvillain', 'Hip-Hop › Turntablism & Beats', 'Hip-Hop › Underground',
     'MC-fronted rap album. Madlib\'s own entry stays in Beats as a producer.'),
    ('Quasimoto', 'Hip-Hop › Turntablism & Beats', 'Hip-Hop › Underground',
     'Lord Quas is an MC persona; the record is a rap album.'),
    ('The String Cheese Incident', 'C&A › Bluegrass', 'Rock › Jam',
     'Both owned records are jam live albums; every peer (Phish, moe., '
     'Leftover Salmon) is already in Jam.'),
]

# ---------------------------------------------------------------------------
# Taxonomy decisions — these change the answers available downstream, so they
# are presented first.
# ---------------------------------------------------------------------------
TAXONOMY = [
    dict(
        id='T1',
        title='"Underground" has become the Hip-Hop catch-all',
        body='58 of 89 Hip-Hop artists sit in Underground, including '
             'foundational mainstream acts. The subcategory currently means '
             '"hip-hop that isn\'t turntablism," which tells you nothing.',
        options=[
            ('Add "Golden Age" as a sibling',
             'New subcategory for the 1986–1997 canon; Underground keeps the '
             'indie/abstract acts it was meant for.'),
            ('Add "Golden Age" and "Mainstream"',
             'Three-way split: Golden Age (canon), Underground (indie), '
             'Mainstream (DMX, Eminem, OutKast, Xzibit, the bare-subcategory '
             'group).'),
            ('Leave it — Underground is fine as a broad bucket',
             'Accept that it reads as "hip-hop, non-turntablist."'),
        ],
        recommended=0,
        affects=['A Tribe Called Quest', 'De La Soul', 'Eric B & Rakim',
                 'Run-D.M.C', 'The Pharcyde', 'Common', 'Fu-Schnickens',
                 'Tha Liks', 'Xzibit', 'Bahamadia', 'Jurassic 5',
                 'Hieroglyphics'],
        affects_label='Candidates to move out of Underground '
                      '(per-artist confirmation in the artist table below)',
    ),
    dict(
        id='T2',
        title='Standards & Vocal sits under Pop, but the jazz vocalists sit under Jazz',
        body='Tony Bennett, Louis Prima, Al Martino and Edith Piaf are in '
             'Pop › Standards & Vocal. Nat King Cole, Ella Fitzgerald, Louis '
             'Armstrong, Sidney Bechet, Diana Krall and Norah Jones are in '
             'Jazz. Same repertoire, split by an invisible rule.',
        options=[
            ('Move Standards & Vocal under Jazz',
             'One home for the songbook. Pop loses a subcategory; Jazz gains '
             'the crooners. Nat King Cole and Ella would move into it.'),
            ('Keep both, and write the rule down',
             'e.g. "instrumentalist-led or improvisation-forward → Jazz; '
             'singer-led interpretation of the songbook → Pop." Then apply it '
             'consistently in both directions.'),
            ('Leave as-is',
             'Accept the split; note it as known drift.'),
        ],
        recommended=1,
        affects=['Tony Bennett', 'Louis Prima', 'Al Martino', 'Edith Piaf',
                 'Nat King Cole', 'Ella Fitzgerald', 'Louis Armstrong',
                 'Diana Krall', 'Norah Jones', 'Curtis Stigers', 'Nellie McKay'],
        affects_label='Artists on either side of the line',
    ),
    dict(
        id='T3',
        title='Eight of thirteen categories have no subcategories at all',
        body='Jazz (38 of 41 bare), Folk & Singer-Songwriter (35), '
             'Soul/Funk/R&B (32), Avant-Garde (20), Blues (14), Latin (13), '
             'World (13), Classical (5). Several already have critical mass '
             'for a subcategory.',
        options=[
            ('Add the four that clearly have mass',
             'Jazz › Gypsy Jazz (Django, Biréli Lagrène, Hot Club of San '
             'Francisco, Quartet Coco Briaval), Jazz › Fusion (Weather '
             'Report, Jaco, Head Hunters-era Herbie, Larry Coryell), '
             'Soul › Gospel (The Soul Stirrers, Sam Cooke & the Soul '
             'Stirrers), Soul › New Orleans Funk (The Neville Brothers, The '
             'Hoodoo Kings, Mofro).'),
            ('Add Gypsy Jazz only',
             'The single most clear-cut cluster; leave the rest flat until '
             'the reservoir grows them.'),
            ('Leave all eight flat',
             'Subcategories earn their way in; none of these has enough yet.'),
        ],
        recommended=0,
        affects=[],
    ),
    dict(
        id='T4',
        title='There is no home for reggae',
        body='Jimmy Cliff is filed World; Jaya the Cat (reggae-punk) is filed '
             'Rock › Punk & Hardcore. The follow reservoir will keep '
             'producing reggae with nowhere to put it.',
        options=[
            ('Add World › Reggae & Dub',
             'Keeps the 13 top-level categories intact; gives reggae a real '
             'home one tier down.'),
            ('Add Reggae as a 14th top-level category',
             'Reggae is a canonical genre family in AllMusic/Discogs terms, '
             'which is the stated basis for the top tier.'),
            ('Leave it — not enough reggae in the collection',
             'Revisit if the reservoir produces more.'),
        ],
        recommended=0,
        affects=['Jimmy Cliff', 'Jaya the Cat'],
    ),
    dict(
        id='T5',
        title='The klezmer / Balkan cluster is split three ways',
        body='Beirut → Folk. The Klezmatics → Avant-Garde. Gipsy Kings and '
             'Zap Mama → World. Beirut and The Klezmatics carry the '
             '<em>identical</em> note: <code>lane confirmed by Chris '
             '("Balkan and klezmer")</code>. The Zorn-orbit klezmer acts '
             '(Cracow Klezmer Band, Bar Kokhba Sextet, Daniel Kahn) are in '
             'Avant-Garde effectively because of the Tzadik label — which '
             'the repo rules explicitly forbid as a basis for categorization.',
        options=[
            ('Split on intent, not label',
             'Traditional/revival klezmer → World; Zorn\'s Radical Jewish '
             'Culture project pieces (Bar Kokhba, Masada ensembles) stay '
             'Avant-Garde because the composition, not the label, is the '
             'reason.'),
            ('All klezmer to World',
             'One home regardless of orbit; Avant-Garde keeps only the '
             'non-klezmer Downtown material.'),
            ('Leave as-is',
             'The current split reflects how you actually hear them.'),
        ],
        recommended=0,
        affects=['The Klezmatics', 'Cracow Klezmer Band',
                 'Daniel Kahn & the Painted Bird', 'Bar Kokhba Sextet',
                 'Beirut'],
    ),
    dict(
        id='T6',
        title='Collaboration entries drift from their principals',
        body='~30 combo acts, several landing in a category none of their '
             'members occupy. Two of the Tier A fixes were this exact bug. '
             'There is no stated rule.',
        options=[
            ('Inherit unless the record contradicts it',
             'A collab takes its principals\' shared category by default; it '
             'only diverges when the actual record is in a different genre '
             '(e.g. Vishwa Mohan Bhatt collabs → World is correct even '
             'though Béla Fleck is Newgrass).'),
            ('Always judge the record on its own',
             'Ignore the principals entirely; categorize from the music.'),
            ('Always inherit from the principals',
             'Mechanical and consistent, but wrong for genuine cross-genre '
             'collaborations.'),
        ],
        recommended=0,
        affects=[],
    ),
    dict(
        id='T7',
        title='The one-category constraint strains on the anchors',
        body='Tom Waits\'s own anchor note reads "art-rock/Americana/'
             'outsider" while he is filed Country & Americana. John Zorn '
             'has the same tension between Avant-Garde and Jazz. The rule '
             'is one category per artist.',
        options=[
            ('Keep one category — it is what makes the graph readable',
             'Accept that anchors get their nuance from the anchor_note and '
             'from personnel edges, not from multi-category membership.'),
            ('Allow a secondary category on anchors only',
             'A small schema change; anchors get two colors in the graph. '
             'Bounded to the four anchor artists.'),
            ('Allow secondary categories generally',
             'Larger change; the graph stops being 13 clean trees.'),
        ],
        recommended=0,
        affects=['Tom Waits', 'John Zorn', 'David Byrne & Brian Eno',
                 'Johnny Cash'],
        affects_label='Current anchors',
    ),
]

# ---------------------------------------------------------------------------
# Artist decisions. current cat/sub and album evidence are pulled from the
# inventory at render time.
#   (artist, proposed_cat, proposed_sub, alternates[], rationale, confidence)
# ---------------------------------------------------------------------------
GROUPS = [
    ('Classic Rock is being used as a chronological bucket',
     'The Beatles / Zeppelin / Floyd / Stones / Genesis / Rush / AC-DC set the '
     'pattern: pre-1985 canonical rock. These entries break it.',
     [
        ('Tori Amos', 'Folk & Singer-Songwriter', None,
         [('Pop', 'Art-Pop & New Wave')],
         'Little Earthquakes (1992) is a singer-songwriter record. Classic '
         'Rock is wrong under any reading.', 'high'),
        ('Muse', 'Rock', 'Indie & Alternative', [],
         '2000s alt-rock.', 'high'),
        ('Kings Of Leon', 'Rock', 'Indie & Alternative', [],
         '2000s southern/indie rock.', 'high'),
        ('My Morning Jacket', 'Rock', 'Indie & Alternative', [],
         '2000s indie rock.', 'high'),
        ('They Might Be Giants', 'Rock', 'Indie & Alternative',
         [('Pop', 'Art-Pop & New Wave')],
         'Alt/geek rock, 1986 onward. Art-Pop is arguably the better fit for '
         'Flood.', 'medium'),
        ('Tenacious D', 'Rock', 'Indie & Alternative', [('Rock', None)],
         'Comedy rock, 2001. Not the classic canon.', 'medium'),
        ('Red Hot Chili Peppers', 'Rock', 'Indie & Alternative', [],
         'Funk-rock, 80s–90s alternative. Applies to both the "Red Hot Chili '
         'Peppers" and "The Red Hot Chili Peppers" entries.', 'medium'),
     ]),

    ('Cross-category misfiles',
     'Artists sitting in a category that does not match the music on the '
     'records you own.',
     [
        ('Radiohead', 'Rock', 'Indie & Alternative',
         [('Pop', 'Art-Pop & New Wave')],
         'Eight albums including OK Computer, Kid A, The Bends. The '
         'highest-degree node currently in the wrong tree. Art-Pop is a real '
         'argument for the Kid A side, but the catalog as owned is alt-rock.',
         'high'),
        ('Nick Cave & the Bad Seeds', 'Country & Americana', 'Gothic Americana',
         [('Rock', 'Indie & Alternative')],
         'Post-punk by origin, but Murder Ballads sits naturally beside 16 '
         'Horsepower / Wovenhand / The Handsome Family, who are already in '
         'Gothic Americana.', 'medium'),
        ('TV On The Radio', 'Rock', 'Indie & Alternative', [],
         'Indie rock, not art-pop.', 'high'),
        ('The Smithereens', 'Rock', 'Indie & Alternative', [],
         'Guitar power-pop band; there is no synth in it. Currently in '
         'Pop › Indie & Synth-Pop.', 'high'),
        ('Steely Dan', 'Rock', 'Classic Rock', [('Jazz', None)],
         'Jazz-inflected rock, not jazz. Filed under Jazz today.', 'medium'),
        ('Jeff Beck', 'Rock', 'Classic Rock', [('Jazz', None)],
         'A rock guitarist; Blow by Blow is his fusion record. Genuine '
         'coin-flip — the owned album argues for Jazz, the artist for Rock.',
         'low'),
        ('Jamiroquai', 'Soul, Funk & R&B', None, [('Pop', None)],
         'Acid-jazz / funk-pop. Currently Jazz.', 'high'),
        ('Al Jarreau & Lou Rawls', 'Soul, Funk & R&B', None, [],
         'The album is literally titled Soul Men. Currently Jazz.', 'high'),
        ('Jack White', 'Rock', 'Indie & Alternative', [('Blues', None)],
         'Blunderbuss is garage/alt rock with blues inflection. Currently '
         'Blues.', 'medium'),
        ('The Raconteurs', 'Rock', 'Indie & Alternative', [('Blues', None)],
         'Garage rock band. Currently Blues.', 'medium'),
        ('Jimi Hendrix', 'Rock', 'Classic Rock', [('Blues', None)],
         'Conventionally classic rock, though the blues lineage is real and '
         'Band of Gypsys leans that way. Flagging, not asserting.', 'low'),
        ('Dire Straits & Mark Knopfler', 'Rock', 'Classic Rock', [],
         'Dire Straits is a rock band. The Knopfler solo entry staying in '
         'Country & Americana is defensible for the late albums.', 'high'),
        ('Creedence Clearwater Revival', 'Rock', 'Classic Rock',
         [('Country & Americana', None)],
         'Chronicle is a classic-rock hits comp. CCR as an Americana '
         'ancestor is a fair counter-argument.', 'medium'),
        ('The Byrds', 'Rock', 'Classic Rock',
         [('Country & Americana', None)],
         'A folk-rock band. Sweetheart of the Rodeo is their country album, '
         'and it is the one you own — so the current filing is defensible.',
         'low'),
        ('White Zombie', 'Rock', 'Metal', [('Electronic', 'Industrial & EBM')],
         'Groove metal. Currently Electronic › Industrial & EBM with a '
         '"(lane confirmed by Chris)" note — but those notes read as '
         'discard-triage confirmations ("keep this artist"), not genre '
         'ratifications. Worth re-confirming which it was.', 'medium'),
        ('Santana', 'Rock', 'Classic Rock', [('Latin', None)],
         'Latin rock — the category depends on which half you weight. '
         'Caravanserai is a rock record.', 'low'),
        ('Little Feat', 'Rock', 'Classic Rock',
         [('Country & Americana', None)],
         'Southern/roots rock. Currently Country & Americana.', 'low'),
        ('Wilco', 'Rock', 'Indie & Alternative',
         [('Country & Americana', None)],
         'The owned catalog is Summerteeth → YHF → A Ghost Is Born — indie '
         'rock, not alt-country. The Uncle Tupelo lineage argues the other '
         'way.', 'medium'),
     ]),

    ('The Bluegrass / Newgrass boundary is applied inconsistently',
     'The same musicians land on different sides depending on which entry '
     'you look at.',
     [
        ('Peter Rowan & Jerry Douglas', 'Country & Americana', 'Newgrass', [],
         'Jerry Douglas solo is Newgrass; this collab is Bluegrass.', 'medium'),
        ('Russ Barenberg', 'Country & Americana', 'Newgrass', [],
         'Barenberg solo is Bluegrass, but the Douglas/Barenberg/Meyer trio '
         'is Newgrass.', 'medium'),
        ('Tarbox Ramblers', 'Blues', None,
         [('Country & Americana', None)],
         'Raw blues-roots band, not bluegrass.', 'high'),
        ('Gillian Welch', 'Country & Americana', None,
         [('Country & Americana', 'Gothic Americana')],
         'Old-time / Americana. Not bluegrass instrumentation.', 'medium'),
        ('Leo Kottke & Mike Gordon', 'Folk & Singer-Songwriter', None,
         [('Rock', 'Jam')],
         'Acoustic folk duo. Not bluegrass. Jam is a fair alternative given '
         'Gordon.', 'medium'),
        ("Yo-Yo Ma-Edgar Meyer-Mark O'Connor", 'Country & Americana', 'Newgrass',
         [('Classical', None)],
         'Appalachian Journey is a classical-crossover record. Currently '
         'Bluegrass, which fits least well of the three.', 'low'),
     ]),

    ('Bruce Springsteen is inverted',
     'The two entries have their albums the wrong way round.',
     [
        ('Bruce Springsteen', 'Country & Americana', None,
         [('Rock', 'Classic Rock')],
         'Filed Rock › Classic Rock, but the only owned album under this '
         'entry is We Shall Overcome: The Seeger Sessions — the folk record. '
         'Either the category follows the album, or the albums should be '
         'merged with the Sessions Band entry.', 'medium'),
        ('Bruce Springsteen with the Sessions Band', 'Country & Americana', None,
         [],
         'Live in Dublin, the same project. Already Country & Americana — '
         'listed here so the pair can be decided together.', 'high'),
     ]),

    ('Subcategory placement within the right category',
     'Category is right; the shelf underneath it is not.',
     [
        ('DJ Spooky', 'Hip-Hop', 'Turntablism & Beats',
         [('Avant-Garde & Experimental', None)],
         'An experimental turntablist filed under Underground.', 'medium'),
        ('Odd Nosdam', 'Hip-Hop', 'Turntablism & Beats',
         [('Electronic', 'Trip-Hop & Downtempo')],
         'Anticon instrumental hip-hop, currently in Electronic — the mirror '
         'image of the Bonobo/Emancipator error already fixed.', 'medium'),
        ('Boom Bip', 'Hip-Hop', 'Turntablism & Beats',
         [('Electronic', 'Trip-Hop & Downtempo')],
         'Abstract hip-hop producer; same Anticon orbit as Odd Nosdam.',
         'low'),
        ('Múm', 'Electronic', None, [('Rock', 'Post-Rock')],
         'Icelandic electronica rather than post-rock proper.', 'low'),
        ('Ratatat', 'Electronic', None, [('Pop', 'Indie & Synth-Pop')],
         'Instrumental electronic rock.', 'low'),
        ('Mr. Bungle', 'Avant-Garde & Experimental', None, [('Rock', 'Metal')],
         'Sits with the rest of the Patton/Zorn cluster, which is already '
         'Avant-Garde. Fantômas and Tomahawk raise the same question.',
         'low'),
        ('Medeski, Martin & Wood', 'Jazz', None,
         [('Rock', 'Jam'), ('Avant-Garde & Experimental', None)],
         'A jazz trio with a jam-circuit audience; currently Avant-Garde on '
         'the strength of the Zorn Book of Angels record.', 'medium'),
        ('Marc Ribot Y los Cubanos Postizos', 'Latin', None,
         [('Avant-Garde & Experimental', None)],
         'Ribot\'s Cuban project. Currently Avant-Garde with the rest of his '
         'work.', 'low'),
     ]),

    ('Folk & Singer-Songwriter is absorbing indie rock',
     'Low-confidence flags. Skip the whole group if the current filing '
     'matches how you hear them.',
     [
        ('Neutral Milk Hotel', 'Rock', 'Indie & Alternative', [],
         'Lo-fi indie rock with folk instrumentation.', 'low'),
        ('The Microphones', 'Rock', 'Indie & Alternative', [],
         'Lo-fi experimental indie. Applies to the "Microphones" entry too.',
         'low'),
        ('Feist', 'Pop', 'Indie & Synth-Pop', [],
         'Indie pop rather than singer-songwriter.', 'low'),
        ('Sarah McLachlan', 'Pop', None, [],
         'Adult alternative pop; the owned record is a remix album.', 'low'),
     ]),

    ('Hip-Hop entries with no subcategory',
     'Ten artists sit at the bare Hip-Hop level. These need a shelf once T1 '
     'is decided.',
     [
        ('OutKast', 'Hip-Hop', 'Underground', [],
         'Placeholder pending T1 — Mainstream/Golden Age would fit better if '
         'either is created.', 'low'),
        ('Eminem', 'Hip-Hop', 'Underground', [],
         'Placeholder pending T1.', 'low'),
        ('The Streets', 'Hip-Hop', 'Underground', [],
         'UK garage-rap; Underground is a reasonable fit.', 'medium'),
        ('Urban Dance Squad', 'Rock', 'Indie & Alternative',
         [('Hip-Hop', None)],
         'Rap-rock crossover band, not a hip-hop act.', 'medium'),
     ]),
]

# ---------------------------------------------------------------------------


def load_inventory():
    with open(INVENTORY) as f:
        return json.load(f)


def cat_str(cat, sub):
    if not cat:
        return '—'
    return f'{cat} › {sub}' if sub else cat


def esc(s):
    return html.escape(str(s), quote=True)


def render_albums(rec, limit=4):
    albums = rec.get('albums') or []
    if not albums:
        note = rec.get('note') or ''
        if 'Person node' in note:
            return '<em class="muted">person node — no owned albums</em>'
        return '<em class="muted">no owned albums</em>'
    shown = [esc(a) for a in albums[:limit]]
    out = '<br>'.join(shown)
    if len(albums) > limit:
        out += f'<br><span class="muted">+{len(albums) - limit} more</span>'
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=DEFAULT_OUT)
    args = ap.parse_args()

    inv = load_inventory()
    artists = inv['artists']

    total_decisions = sum(len(items) for _, _, items in GROUPS)

    # ---- taxonomy cards ----
    tax_html = []
    for t in TAXONOMY:
        opts = []
        for i, (label, detail) in enumerate(t['options']):
            rec_badge = ' <span class="badge rec">recommended</span>' if i == t['recommended'] else ''
            opts.append(
                f'<label class="opt">'
                f'<input type="radio" name="{t["id"]}" value="{i}">'
                f'<span class="opt-body"><span class="opt-label">{esc(label)}{rec_badge}</span>'
                f'<span class="opt-detail">{esc(detail)}</span></span></label>')
        affects = ''
        if t.get('affects'):
            chips = ' '.join(f'<span class="chip">{esc(a)}</span>' for a in t['affects'])
            label = t.get('affects_label', 'Affects')
            affects = f'<div class="affects"><span class="affects-label">{esc(label)}</span>{chips}</div>'
        tax_html.append(f'''
    <article class="card" data-decision="{t['id']}">
      <div class="card-head">
        <span class="tag">{t['id']}</span>
        <h3>{esc(t['title'])}</h3>
      </div>
      <p class="card-body">{t['body']}</p>
      <div class="opts">{''.join(opts)}
        <label class="opt"><input type="radio" name="{t['id']}" value="other">
          <span class="opt-body"><span class="opt-label">Something else</span>
          <input type="text" class="other-text" name="{t['id']}__other"
                 placeholder="your call…"></span></label>
      </div>
      {affects}
    </article>''')

    # ---- artist tables ----
    grp_html = []
    for gi, (title, blurb, items) in enumerate(GROUPS):
        rows = []
        for artist, pcat, psub, alts, why, conf in items:
            rec = artists.get(artist)
            if rec is None:
                rows.append(f'<tr><td colspan="5" class="missing">MISSING FROM '
                            f'INVENTORY: {esc(artist)}</td></tr>')
                continue
            cur = cat_str(rec.get('category'), rec.get('subcategory'))
            prop = cat_str(pcat, psub)
            rid = f'A{gi}_{esc(artist).replace(" ", "_")[:40]}'
            alt_opts = ''.join(
                f'<label class="opt sm"><input type="radio" name="{rid}" '
                f'value="alt:{esc(cat_str(ac, asub))}">'
                f'<span class="opt-label">{esc(cat_str(ac, asub))}</span></label>'
                for ac, asub in alts)
            rows.append(f'''
        <tr data-artist="{esc(artist)}" data-conf="{conf}">
          <td class="c-artist"><strong>{esc(artist)}</strong>
            <span class="conf conf-{conf}">{conf}</span></td>
          <td class="c-albums">{render_albums(rec)}</td>
          <td class="c-move"><span class="from">{esc(cur)}</span>
            <span class="arrow">→</span>
            <span class="to">{esc(prop)}</span>
            <p class="why">{esc(why)}</p></td>
          <td class="c-choice">
            <label class="opt sm"><input type="radio" name="{rid}" value="accept" checked>
              <span class="opt-label">Accept</span></label>
            <label class="opt sm"><input type="radio" name="{rid}" value="keep">
              <span class="opt-label">Keep current</span></label>
            {alt_opts}
            <label class="opt sm"><input type="radio" name="{rid}" value="other">
              <span class="opt-label">Other</span></label>
            <input type="text" class="other-text row-other" name="{rid}__other"
                   placeholder="category › subcategory">
          </td>
        </tr>''')
        grp_html.append(f'''
    <section class="group">
      <h3>{esc(title)}</h3>
      <p class="blurb">{esc(blurb)}</p>
      <div class="table-wrap">
      <table>
        <thead><tr>
          <th>Artist</th><th>Owned albums</th>
          <th>Current → proposed</th><th>Your call</th>
        </tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
      </div>
    </section>''')

    applied_rows = ''.join(
        f'<tr><td><strong>{esc(a)}</strong></td>'
        f'<td class="from">{esc(b)}</td><td class="to">{esc(c)}</td>'
        f'<td class="why-cell">{esc(w)}</td></tr>'
        for a, b, c, w in APPLIED)

    page = TEMPLATE.format(
        total_decisions=total_decisions,
        n_taxonomy=len(TAXONOMY),
        n_applied=len(APPLIED),
        n_categorized=sum(1 for r in artists.values()
                          if not r.get('discard') and r.get('category')),
        taxonomy=''.join(tax_html),
        groups=''.join(grp_html),
        applied_rows=applied_rows,
    )

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, 'w') as f:
        f.write(page)
    print(f'wrote {args.out}')
    print(f'  taxonomy decisions: {len(TAXONOMY)}')
    print(f'  artist decisions:   {total_decisions}')
    print(f'  already applied:    {len(APPLIED)}')


TEMPLATE = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Music collection — categorization review</title>
<style>
  :root {{
    --bg: #faf9f7; --panel: #fff; --ink: #1a1a1a; --muted: #6b6b6b;
    --line: #e2ded8; --accent: #7c4a2d; --accent-soft: #f3ece6;
    --from: #a3453a; --to: #2f6b4f; --warn: #b8860b;
    --rad: 10px;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #17161a; --panel: #1f1e23; --ink: #ece9e4; --muted: #9a958d;
      --line: #33313a; --accent: #d29b6e; --accent-soft: #2a2630;
      --from: #e08b7f; --to: #7fc4a0; --warn: #d9b45c;
    }}
  }}
  :root[data-theme="dark"] {{
    --bg: #17161a; --panel: #1f1e23; --ink: #ece9e4; --muted: #9a958d;
    --line: #33313a; --accent: #d29b6e; --accent-soft: #2a2630;
    --from: #e08b7f; --to: #7fc4a0; --warn: #d9b45c;
  }}
  :root[data-theme="light"] {{
    --bg: #faf9f7; --panel: #fff; --ink: #1a1a1a; --muted: #6b6b6b;
    --line: #e2ded8; --accent: #7c4a2d; --accent-soft: #f3ece6;
    --from: #a3453a; --to: #2f6b4f; --warn: #b8860b;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--ink);
    font: 15px/1.55 ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif;
    padding-bottom: 5rem;
  }}
  .wrap {{ max-width: 1180px; margin: 0 auto; padding: 2rem 1.25rem; }}
  header h1 {{ font-size: 1.75rem; margin: 0 0 .35rem; letter-spacing: -.02em; }}
  header .sub {{ color: var(--muted); margin: 0 0 1.5rem; max-width: 68ch; }}
  .stats {{ display: flex; flex-wrap: wrap; gap: .6rem; margin-bottom: 2rem; }}
  .stat {{
    background: var(--panel); border: 1px solid var(--line);
    border-radius: var(--rad); padding: .55rem .85rem;
  }}
  .stat b {{ display: block; font-size: 1.35rem; line-height: 1.1; }}
  .stat span {{ color: var(--muted); font-size: .78rem;
    text-transform: uppercase; letter-spacing: .06em; }}
  h2 {{
    font-size: 1.05rem; text-transform: uppercase; letter-spacing: .09em;
    color: var(--accent); margin: 2.75rem 0 .4rem;
    padding-bottom: .4rem; border-bottom: 2px solid var(--accent-soft);
  }}
  h2 .n {{ color: var(--muted); font-weight: 400; letter-spacing: 0;
    text-transform: none; }}
  .lead {{ color: var(--muted); margin: 0 0 1.25rem; max-width: 72ch; }}
  .card {{
    background: var(--panel); border: 1px solid var(--line);
    border-radius: var(--rad); padding: 1.1rem 1.2rem; margin-bottom: .9rem;
  }}
  .card-head {{ display: flex; align-items: baseline; gap: .6rem; }}
  .card-head h3 {{ margin: 0 0 .4rem; font-size: 1.05rem; }}
  .tag {{
    background: var(--accent-soft); color: var(--accent); font-weight: 700;
    font-size: .72rem; padding: .18rem .45rem; border-radius: 5px;
    letter-spacing: .04em;
  }}
  .card-body {{ margin: 0 0 .9rem; color: var(--muted); max-width: 78ch; }}
  .card-body code {{ background: var(--accent-soft); padding: .1rem .3rem;
    border-radius: 4px; font-size: .88em; }}
  .opts {{ display: flex; flex-direction: column; gap: .35rem; }}
  .opt {{ display: flex; gap: .55rem; align-items: flex-start;
    padding: .45rem .55rem; border-radius: 7px; cursor: pointer;
    border: 1px solid transparent; }}
  .opt:hover {{ background: var(--accent-soft); }}
  .opt:has(input:checked) {{ background: var(--accent-soft);
    border-color: var(--accent); }}
  .opt input[type=radio] {{ margin-top: .28rem; accent-color: var(--accent);
    flex-shrink: 0; }}
  .opt-body {{ display: flex; flex-direction: column; gap: .15rem; }}
  .opt-label {{ font-weight: 600; font-size: .92rem; }}
  .opt-detail {{ color: var(--muted); font-size: .86rem; }}
  .opt.sm {{ padding: .2rem .35rem; }}
  .opt.sm .opt-label {{ font-weight: 500; font-size: .85rem; }}
  .badge.rec {{ background: var(--to); color: #fff; font-size: .66rem;
    padding: .1rem .35rem; border-radius: 4px; vertical-align: .1em;
    letter-spacing: .04em; text-transform: uppercase; font-weight: 700; }}
  .other-text {{
    margin-top: .25rem; background: var(--bg); color: var(--ink);
    border: 1px solid var(--line); border-radius: 6px;
    padding: .3rem .45rem; font: inherit; font-size: .85rem; width: 100%;
    max-width: 22rem;
  }}
  .affects {{ margin-top: .85rem; padding-top: .75rem;
    border-top: 1px dashed var(--line); }}
  .affects-label {{ display: block; color: var(--muted); font-size: .78rem;
    text-transform: uppercase; letter-spacing: .06em; margin-bottom: .4rem; }}
  .chip {{ display: inline-block; background: var(--accent-soft);
    border-radius: 20px; padding: .12rem .55rem; font-size: .8rem;
    margin: 0 .25rem .3rem 0; }}
  .group {{ margin-bottom: 2rem; }}
  .group h3 {{ font-size: 1.02rem; margin: 0 0 .3rem; }}
  .blurb {{ color: var(--muted); margin: 0 0 .8rem; max-width: 78ch;
    font-size: .9rem; }}
  .table-wrap {{ overflow-x: auto; border: 1px solid var(--line);
    border-radius: var(--rad); background: var(--panel); }}
  table {{ border-collapse: collapse; width: 100%; min-width: 900px; }}
  th {{ text-align: left; font-size: .74rem; text-transform: uppercase;
    letter-spacing: .07em; color: var(--muted); font-weight: 600;
    padding: .7rem .8rem; border-bottom: 1px solid var(--line);
    background: var(--bg); position: sticky; top: 0; }}
  td {{ padding: .8rem; border-bottom: 1px solid var(--line);
    vertical-align: top; font-size: .9rem; }}
  tr:last-child td {{ border-bottom: 0; }}
  .c-artist {{ width: 17%; }}
  .c-albums {{ width: 22%; font-size: .82rem; color: var(--muted); }}
  .c-move {{ width: 38%; }}
  .c-choice {{ width: 23%; }}
  .from {{ color: var(--from); }}
  .to {{ color: var(--to); font-weight: 600; }}
  .arrow {{ color: var(--muted); margin: 0 .3rem; }}
  .why {{ margin: .4rem 0 0; color: var(--muted); font-size: .84rem; }}
  .why-cell {{ color: var(--muted); font-size: .84rem; }}
  .conf {{ display: inline-block; font-size: .66rem; text-transform: uppercase;
    letter-spacing: .05em; padding: .1rem .35rem; border-radius: 4px;
    margin-left: .3rem; vertical-align: .08em; font-weight: 700; }}
  .conf-high {{ background: rgba(47,107,79,.16); color: var(--to); }}
  .conf-medium {{ background: rgba(184,134,11,.18); color: var(--warn); }}
  .conf-low {{ background: var(--accent-soft); color: var(--muted); }}
  .muted {{ color: var(--muted); }}
  .missing {{ color: var(--from); font-weight: 600; }}
  .applied summary {{ cursor: pointer; font-weight: 600; padding: .5rem 0; }}
  .bar {{
    position: fixed; bottom: 0; left: 0; right: 0; background: var(--panel);
    border-top: 1px solid var(--line); padding: .7rem 1.25rem;
    display: flex; gap: .7rem; align-items: center; flex-wrap: wrap;
    box-shadow: 0 -3px 14px rgba(0,0,0,.07); z-index: 20;
  }}
  button {{
    font: inherit; font-weight: 600; font-size: .88rem; cursor: pointer;
    border-radius: 7px; padding: .5rem .9rem; border: 1px solid var(--line);
    background: var(--panel); color: var(--ink);
  }}
  button.primary {{ background: var(--accent); color: #fff;
    border-color: var(--accent); }}
  button:hover {{ filter: brightness(1.06); }}
  .bar .status {{ color: var(--muted); font-size: .85rem; margin-left: auto; }}
  dialog {{
    border: 1px solid var(--line); border-radius: var(--rad); padding: 0;
    background: var(--panel); color: var(--ink); max-width: 720px; width: 92%;
  }}
  dialog::backdrop {{ background: rgba(0,0,0,.45); }}
  .dlg-head {{ padding: 1rem 1.2rem .4rem; }}
  .dlg-head h3 {{ margin: 0 0 .2rem; }}
  .dlg-head p {{ margin: 0; color: var(--muted); font-size: .88rem; }}
  dialog textarea {{
    width: calc(100% - 2.4rem); margin: .8rem 1.2rem; height: 46vh;
    background: var(--bg); color: var(--ink); border: 1px solid var(--line);
    border-radius: 7px; padding: .7rem; font-family: ui-monospace,
    "SF Mono", Menlo, Consolas, monospace; font-size: .82rem; resize: vertical;
  }}
  .dlg-foot {{ padding: 0 1.2rem 1.1rem; display: flex; gap: .6rem; }}
  @media (max-width: 720px) {{
    .wrap {{ padding: 1.25rem .85rem; }}
    header h1 {{ font-size: 1.4rem; }}
  }}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>Music collection — categorization review</h1>
  <p class="sub">A full pass over the {n_categorized} categorized artists in
  <code>music-curator</code>. Taxonomy questions come first because they change
  the answers available below them. Every artist row is pre-set to the proposed
  change — you only need to touch the ones you disagree with. When you're done,
  hit <strong>Copy decisions</strong> and paste the block back into the
  session.</p>
</header>

<div class="stats">
  <div class="stat"><b>{n_applied}</b><span>already applied</span></div>
  <div class="stat"><b>{n_taxonomy}</b><span>taxonomy calls</span></div>
  <div class="stat"><b>{total_decisions}</b><span>artist calls</span></div>
  <div class="stat"><b>{n_categorized}</b><span>artists in scope</span></div>
</div>

<h2>1 · Taxonomy <span class="n">— decide these first</span></h2>
<p class="lead">These change the shape of the category tree. A new subcategory
or a moved boundary changes what the right answer is for dozens of artists
below, so they are worth settling before the artist-by-artist pass.</p>
{taxonomy}

<h2>2 · Artist decisions <span class="n">— {total_decisions} calls, pre-set to the proposal</span></h2>
<p class="lead">Confidence badges are mine, not yours: <span class="conf conf-high">high</span>
means the current filing is wrong under any reading,
<span class="conf conf-medium">medium</span> means I think it's wrong but the
counter-argument is real, and <span class="conf conf-low">low</span> means
it's a genuine coin-flip I'm surfacing rather than asserting. Skipping every
low-confidence row is a legitimate way to run this.</p>
{groups}

<h2>3 · Already applied <span class="n">— factual corrections</span></h2>
<details class="applied">
  <summary>{n_applied} changes made before this sheet was generated — expand to audit</summary>
  <div class="table-wrap" style="margin-top:.6rem">
  <table>
    <thead><tr><th>Artist</th><th>Was</th><th>Now</th><th>Why</th></tr></thead>
    <tbody>{applied_rows}</tbody>
  </table>
  </div>
</details>
</div>

<div class="bar">
  <button class="primary" id="copy">Copy decisions</button>
  <button id="acceptall">Accept all proposals</button>
  <button id="reset">Reset</button>
  <button id="theme" title="Toggle light/dark">◐</button>
  <span class="status" id="status"></span>
</div>

<dialog id="dlg">
  <div class="dlg-head">
    <h3>Your decisions</h3>
    <p>Copied to the clipboard. If that failed, select and copy manually,
    then paste into the curation session.</p>
  </div>
  <textarea id="out" readonly></textarea>
  <div class="dlg-foot">
    <button class="primary" id="copy2">Copy again</button>
    <button id="close">Close</button>
  </div>
</dialog>

<script>
const KEY = 'music-cat-review-v1';
const $ = s => document.querySelector(s);
const status = $('#status');

function save() {{
  const d = {{}};
  document.querySelectorAll('input[type=radio]:checked').forEach(r => d[r.name] = r.value);
  document.querySelectorAll('input.other-text').forEach(t => {{ if (t.value) d[t.name] = t.value; }});
  localStorage.setItem(KEY, JSON.stringify(d));
  const changed = [...document.querySelectorAll('tr[data-artist] input[type=radio]:checked')]
    .filter(r => r.value !== 'accept').length;
  const tax = document.querySelectorAll('.card[data-decision] input[type=radio]:checked').length;
  const nTax = document.querySelectorAll('.card[data-decision]').length;
  status.textContent = `taxonomy ${{tax}}/${{nTax}} · ` +
    (changed ? changed + ' artist override' + (changed === 1 ? '' : 's') : 'all artist proposals accepted');
}}

function restore() {{
  let d;
  try {{ d = JSON.parse(localStorage.getItem(KEY) || '{{}}'); }} catch (e) {{ return; }}
  for (const [name, val] of Object.entries(d)) {{
    if (name.endsWith('__other')) {{
      const t = document.querySelector(`input[name="${{CSS.escape(name)}}"]`);
      if (t) t.value = val;
    }} else {{
      const r = document.querySelector(`input[name="${{CSS.escape(name)}}"][value="${{CSS.escape(val)}}"]`);
      if (r) r.checked = true;
    }}
  }}
}}

function build() {{
  const lines = ['# Categorization review — decisions', ''];
  lines.push('## Taxonomy');
  document.querySelectorAll('.card[data-decision]').forEach(card => {{
    const id = card.dataset.decision;
    const title = card.querySelector('h3').textContent.trim();
    const sel = card.querySelector('input[type=radio]:checked');
    if (!sel) {{ lines.push(`${{id}}: (no answer) — ${{title}}`); return; }}
    if (sel.value === 'other') {{
      const t = card.querySelector('.other-text');
      lines.push(`${{id}}: OTHER — ${{(t && t.value) || '(blank)'}}   [${{title}}]`);
    }} else {{
      const label = sel.closest('.opt').querySelector('.opt-label')
        .textContent.replace('recommended', '').trim();
      lines.push(`${{id}}: ${{label}}   [${{title}}]`);
    }}
  }});

  lines.push('', '## Artist overrides (rows not listed = proposal accepted)');
  let n = 0;
  document.querySelectorAll('tr[data-artist]').forEach(tr => {{
    const sel = tr.querySelector('input[type=radio]:checked');
    if (!sel || sel.value === 'accept') return;
    const artist = tr.dataset.artist;
    const cur = tr.querySelector('.from').textContent.trim();
    if (sel.value === 'keep') {{
      lines.push(`- ${{artist}}: KEEP ${{cur}}`);
    }} else if (sel.value === 'other') {{
      const t = tr.querySelector('.row-other');
      lines.push(`- ${{artist}}: OTHER → ${{(t && t.value) || '(blank)'}}`);
    }} else if (sel.value.startsWith('alt:')) {{
      lines.push(`- ${{artist}}: ALT → ${{sel.value.slice(4)}}`);
    }}
    n++;
  }});
  if (!n) lines.push('- (none — every proposal accepted)');
  return lines.join('\n');
}}

async function copyOut() {{
  const text = build();
  $('#out').value = text;
  try {{ await navigator.clipboard.writeText(text); }} catch (e) {{ /* manual copy */ }}
  if (!$('#dlg').open) $('#dlg').showModal();
}}

$('#copy').onclick = copyOut;
$('#copy2').onclick = copyOut;
$('#close').onclick = () => $('#dlg').close();
$('#acceptall').onclick = () => {{
  document.querySelectorAll('tr[data-artist] input[value=accept]')
    .forEach(r => r.checked = true);
  save();
}};
$('#reset').onclick = () => {{
  if (!confirm('Clear every recorded decision?')) return;
  localStorage.removeItem(KEY);
  location.reload();
}};
$('#theme').onclick = () => {{
  const cur = document.documentElement.dataset.theme;
  const next = cur === 'dark' ? 'light' : cur === 'light' ? '' : 'dark';
  if (next) document.documentElement.dataset.theme = next;
  else delete document.documentElement.dataset.theme;
  localStorage.setItem(KEY + '-theme', next);
}};

const savedTheme = localStorage.getItem(KEY + '-theme');
if (savedTheme) document.documentElement.dataset.theme = savedTheme;

document.addEventListener('change', save);
document.addEventListener('input', e => {{
  if (e.target.classList.contains('other-text')) {{
    const grp = e.target.closest('.opt, td');
    const other = grp && grp.querySelector('input[value=other]');
    if (other) other.checked = true;
    save();
  }}
}});
restore();
save();
</script>
</body>
</html>
'''

if __name__ == '__main__':
    main()
