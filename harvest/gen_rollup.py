#!/usr/bin/env python3
"""Generate the n8n workflow JSON for the monthly Spotify roll-up (consumer).

Sibling to gen_workflow.py (the daily producer). Kept as a generator so the
embedded Code-node JS stays readable and the emitted JSON is always valid.
Targets n8n 2.27 (node typeVersions valid in 2.x).

Pipeline (see harvest/README.md → Architecture):

    Schedule (monthly, 1st @ 02:00)
      -> Redis Get (keyType=list, key spotify:harvests)   # LRANGE 0 -1, non-destructive
      -> Code (aggregate per-artist roll-up, bucket by month)
      -> GitHub (create data/harvests/YYYY-MM.json)
      -> Redis Delete (drain the key)                      # only reached if commit succeeds

Timing assumption: the consumer runs at 02:00 on the 1st and the producer at
06:00 daily, so at drain time the queue holds exactly the just-ended month's
snapshots and nothing newer -- delete-key is a safe drain. The n8n Redis node
exposes no LTRIM, so delete-key is the available primitive.
"""
import json
import pathlib

JS = r"""// Spotify monthly roll-up -- music-curator. n8n Code node, "Run Once for All Items".
// Input: the "Read queue" Redis Get node (keyType=list) put the raw list into
// $json.queue as an array of snapshot JSON strings (each is one daily snapshot,
// schema v1, as pushed by the producer's Redis node).
// Output: one item per calendar month present in the queue, each carrying the
// committable file { path, content, message } for the GitHub node.

const first = $input.first();
const rawQueue = (first && first.json && first.json.queue) || [];
const queue = Array.isArray(rawQueue) ? rawQueue : [rawQueue];
if (!queue.length) {
  // Nothing buffered -- emit no items so the GitHub/Delete nodes no-op.
  return [];
}

// --- parse snapshots, tolerate the odd malformed string ---
const snapshots = [];
for (const entry of queue) {
  try {
    snapshots.push(typeof entry === 'string' ? JSON.parse(entry) : entry);
  } catch (e) {
    // skip an unparseable queue entry rather than fail the whole roll-up
  }
}
if (!snapshots.length) return [];

// --- helpers ---
const dayOf = (iso) => (iso || '').slice(0, 10);        // YYYY-MM-DD
const monthOf = (iso) => (iso || '').slice(0, 7);       // YYYY-MM
const RANGES = ['short_term', 'medium_term', 'long_term'];

// month -> { snapshotDays:Set, profile, playlistsCount, artists: Map(name -> rec) }
const months = new Map();
function bucket(month) {
  if (!months.has(month)) {
    months.set(month, { days: new Set(), profile: null, playlistsCount: 0, artists: new Map() });
  }
  return months.get(month);
}
function artistRec(b, name) {
  if (!b.artists.has(name)) {
    b.artists.set(name, {
      name,
      days: new Set(),            // distinct snapshot days seen in any signal
      top_ranges: new Set(),      // ranges where in top ARTISTS
      in_top_artists_days: new Set(),
      in_top_tracks_days: new Set(),
      followed: false,
      saved_tracks_max: 0,
      plays: new Set(),           // distinct recently_played `played_at` (de-duped)
      genres: new Set(),
    });
  }
  return b.artists.get(name);
}

for (const snap of snapshots) {
  const when = snap.harvested_at;
  const month = monthOf(when);
  const day = dayOf(when);
  if (!month) continue;
  const b = bucket(month);
  b.days.add(day);
  b.profile = snap.profile || b.profile;         // keep the latest profile seen
  if (snap.playlists) b.playlistsCount = snap.playlists.length;

  const mark = (name, day) => { const r = artistRec(b, name); r.days.add(day); return r; };

  // top artists (the strongest rotation signal): name + range + genres
  const top = snap.top || {};
  for (const range of RANGES) {
    for (const a of ((top.artists && top.artists[range]) || [])) {
      if (!a || !a.name) continue;
      const r = mark(a.name, day);
      r.top_ranges.add(range);
      r.in_top_artists_days.add(day);
      (a.genres || []).forEach((g) => r.genres.add(g));
    }
    // top tracks -> credit each track's artists (weaker signal)
    for (const t of ((top.tracks && top.tracks[range]) || [])) {
      for (const nm of ((t && t.artists) || [])) mark(nm, day).in_top_tracks_days.add(day);
    }
  }

  // followed artists
  for (const a of (snap.followed_artists || [])) {
    if (!a || !a.name) continue;
    const r = mark(a.name, day);
    r.followed = true;
    (a.genres || []).forEach((g) => r.genres.add(g));
  }

  // saved library -- count distinct saved tracks per artist this snapshot, keep the max
  const savedThisSnap = new Map();
  for (const t of (snap.saved_tracks || [])) {
    for (const nm of ((t && t.artists) || [])) savedThisSnap.set(nm, (savedThisSnap.get(nm) || 0) + 1);
  }
  for (const [nm, n] of savedThisSnap) {
    const r = mark(nm, day);
    if (n > r.saved_tracks_max) r.saved_tracks_max = n;
  }

  // recently played -- de-dupe real plays by played_at across the month
  for (const t of (snap.recently_played || [])) {
    for (const nm of ((t && t.artists) || [])) {
      if (t.played_at) mark(nm, day).plays.add(t.played_at);
    }
  }
}

// --- emit one committable item per month ---
const now = new Date();
const out = [];
for (const [month, b] of months) {
  const artists = {};
  for (const [name, r] of [...b.artists.entries()].sort((a, c) => a[0].localeCompare(c[0]))) {
    const days = [...r.days].sort();
    artists[name] = {
      days_seen: r.days.size,
      first_seen: days[0],
      last_seen: days[days.length - 1],
      top_ranges: [...r.top_ranges].sort(),
      in_top_artists_days: r.in_top_artists_days.size,
      in_top_tracks_days: r.in_top_tracks_days.size,
      followed: r.followed,
      saved_tracks_max: r.saved_tracks_max,
      plays: r.plays.size,
      genres: [...r.genres].sort(),
    };
  }
  const rollup = {
    month,
    generated_at: now.toISOString(),
    source: 'spotify-web-api',
    harvester: 'music-curator/n8n rollup',
    schema: 1,
    snapshot_days: b.days.size,
    profile: b.profile,
    playlists_count: b.playlistsCount,
    artist_count: Object.keys(artists).length,
    artists,
  };
  out.push({
    json: {
      path: `data/harvests/${month}.json`,
      content: JSON.stringify(rollup, null, 2) + '\n',
      message: `chore(harvest): roll up ${month} Spotify snapshots (${b.days.size} days, ${rollup.artist_count} artists)`,
    },
  });
}
return out;
"""

OWNER = "lentago"
REPO = "music-curator"

workflow = {
    "id": "spotifyRollup01",
    "name": "Spotify monthly roll-up → GitHub (music-curator)",
    "nodes": [
        {
            # 1st of every month at 02:00 -- before that day's 06:00 producer run,
            # so the queue holds exactly the just-ended month at drain time.
            "parameters": {
                "rule": {"interval": [{"field": "months", "triggerAtDayOfMonth": 1, "triggerAtHour": 2}]}
            },
            "id": "b1000000-0000-4000-8000-000000000001",
            "name": "Monthly 1st 02:00",
            "type": "n8n-nodes-base.scheduleTrigger",
            "typeVersion": 1.2,
            "position": [380, 300],
        },
        {
            # Non-destructive read of the whole list (keyType=list -> LRANGE 0 -1).
            # Assign the Redis credential in the n8n UI after import.
            "parameters": {
                "operation": "get",
                "propertyName": "queue",
                "key": "spotify:harvests",
                "keyType": "list",
                "options": {},
            },
            "id": "b1000000-0000-4000-8000-000000000002",
            "name": "Read queue",
            "type": "n8n-nodes-base.redis",
            "typeVersion": 1,
            "position": [600, 300],
        },
        {
            "parameters": {"jsCode": JS},
            "id": "b1000000-0000-4000-8000-000000000003",
            "name": "Aggregate roll-up",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [820, 300],
        },
        {
            # One file per month item. `create` fails if the file already exists,
            # which is the correct guard for the monthly cadence (each YYYY-MM.json
            # is committed exactly once, the month after). Assign the GitHub API
            # credential (fine-grained PAT, contents:write on lentago/music-curator)
            # in the n8n UI after import.
            "parameters": {
                "resource": "file",
                "operation": "create",
                "owner": {"__rl": True, "value": OWNER, "mode": "name"},
                "repository": {"__rl": True, "value": REPO, "mode": "name"},
                "filePath": "={{ $json.path }}",
                "fileContent": "={{ $json.content }}",
                "commitMessage": "={{ $json.message }}",
                "additionalParameters": {},
            },
            "id": "b1000000-0000-4000-8000-000000000004",
            "name": "Commit roll-up",
            "type": "n8n-nodes-base.github",
            "typeVersion": 1,
            "position": [1040, 300],
        },
        {
            # Drain the queue only after the commit(s) succeed. If the commit
            # throws, this node is never reached and the buffer is preserved.
            "parameters": {
                "operation": "delete",
                "key": "spotify:harvests",
                "options": {},
            },
            "id": "b1000000-0000-4000-8000-000000000005",
            "name": "Drain queue",
            "type": "n8n-nodes-base.redis",
            "typeVersion": 1,
            "position": [1260, 300],
        },
    ],
    "connections": {
        "Monthly 1st 02:00": {"main": [[{"node": "Read queue", "type": "main", "index": 0}]]},
        "Read queue": {"main": [[{"node": "Aggregate roll-up", "type": "main", "index": 0}]]},
        "Aggregate roll-up": {"main": [[{"node": "Commit roll-up", "type": "main", "index": 0}]]},
        "Commit roll-up": {"main": [[{"node": "Drain queue", "type": "main", "index": 0}]]},
    },
    "settings": {"executionOrder": "v1", "saveManualExecutions": True},
    "active": False,
}

out = pathlib.Path(__file__).resolve().parent / "rollup.workflow.json"
out.write_text(json.dumps(workflow, indent=2) + "\n")
print("wrote", out, out.stat().st_size, "bytes")
# sanity: reparse
json.loads(out.read_text())
print("valid JSON OK")
