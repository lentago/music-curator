#!/usr/bin/env python3
"""Generate the n8n workflow JSON for the monthly Spotify roll-up (consumer).

Sibling to gen_workflow.py (the daily producer). Kept as a generator so the
embedded Code-node JS stays readable and the emitted JSON is always valid.
Targets n8n 2.27 (node typeVersions valid in 2.x).

Pipeline (see harvest/README.md -> Architecture):

    Schedule (monthly, 1st @ 02:00)
      -> Redis Get (keyType=list, key spotify:harvests)   # LRANGE 0 -1, non-destructive
      -> Code (aggregate per-month roll-up, then commit each month to a branch,
               open a PR, and auto-merge it)
      -> Redis Delete (drain the key)                      # only reached if the Code node succeeds

Why the commit lives in the Code node (not a GitHub node):
  * `main` is protected by a ruleset (PR required, zero bypass actors), so a
    direct commit to main is impossible -- the roll-up must land via a PR.
  * The n8n Code-node sandbox has no Buffer/btoa, so it can't base64-encode a
    file for the Contents API. The low-level git *data* API takes UTF-8 content
    directly (blob encoding "utf-8"), sidestepping base64 entirely.
  * Doing blob -> tree -> commit -> branch ref -> PR -> auto-merge in one Code
    node via `helpers.httpRequest` (the same primitive the producer uses for
    Spotify) avoids fragile multi-node credential/field threading.

Auth: `$env.GITHUB_TOKEN` -- a fine-grained PAT (Contents + Pull requests write
on lentago/music-curator) in /opt/n8n/.env alongside the Spotify secrets. Needs
N8N_BLOCK_ENV_ACCESS_IN_NODE=false (already set).

Timing assumption: the consumer runs at 02:00 on the 1st and the producer at
06:00 daily, so at drain time the queue holds exactly the just-ended month's
snapshots and nothing newer -- delete-key is a safe drain. The n8n Redis node
exposes no LTRIM, so delete-key is the available primitive.
"""
import json
import pathlib

JS = r"""// Spotify monthly roll-up -- music-curator. n8n Code node, "Run Once for All Items".
// Input: the "Read queue" Redis Get node (keyType=list) put the raw list into
// $json.queue as an array of snapshot JSON strings (each one daily snapshot,
// schema v1, as pushed by the producer).
// Action: aggregate a per-artist roll-up per calendar month, then for each month
// commit data/harvests/YYYY-MM.json to a branch, open a PR, and auto-merge it.
// Output: one status item per month committed.

const helpers = this.helpers;
const TOKEN = $env.GITHUB_TOKEN;
if (!TOKEN) throw new Error('Missing GITHUB_TOKEN in n8n env (fine-grained PAT, Contents + Pull requests write; set N8N_BLOCK_ENV_ACCESS_IN_NODE=false).');
const OWNER = 'lentago', REPO = 'music-curator', BASE = 'main';
const GH = 'https://api.github.com';

const first = $input.first();
const rawQueue = (first && first.json && first.json.queue) || [];
const queue = Array.isArray(rawQueue) ? rawQueue : [rawQueue];
if (!queue.length) return [];

// --- parse snapshots, tolerate the odd malformed string ---
const snapshots = [];
for (const entry of queue) {
  try { snapshots.push(typeof entry === 'string' ? JSON.parse(entry) : entry); } catch (e) { /* skip */ }
}
if (!snapshots.length) return [];

// --- aggregate ---
const dayOf = (iso) => (iso || '').slice(0, 10);
const monthOf = (iso) => (iso || '').slice(0, 7);
const RANGES = ['short_term', 'medium_term', 'long_term'];
const months = new Map();
function bucket(m) {
  if (!months.has(m)) months.set(m, { days: new Set(), profile: null, playlistsCount: 0, artists: new Map() });
  return months.get(m);
}
function artistRec(b, name) {
  if (!b.artists.has(name)) b.artists.set(name, {
    name, days: new Set(), top_ranges: new Set(), in_top_artists_days: new Set(),
    in_top_tracks_days: new Set(), followed: false, saved_tracks_max: 0, plays: new Set(), genres: new Set(),
  });
  return b.artists.get(name);
}
for (const snap of snapshots) {
  const month = monthOf(snap.harvested_at), day = dayOf(snap.harvested_at);
  if (!month) continue;
  const b = bucket(month);
  b.days.add(day);
  b.profile = snap.profile || b.profile;
  if (snap.playlists) b.playlistsCount = snap.playlists.length;
  const mark = (name, d) => { const r = artistRec(b, name); r.days.add(d); return r; };
  const top = snap.top || {};
  for (const range of RANGES) {
    for (const a of ((top.artists && top.artists[range]) || [])) {
      if (!a || !a.name) continue;
      const r = mark(a.name, day); r.top_ranges.add(range); r.in_top_artists_days.add(day);
      (a.genres || []).forEach((g) => r.genres.add(g));
    }
    for (const t of ((top.tracks && top.tracks[range]) || [])) {
      for (const nm of ((t && t.artists) || [])) mark(nm, day).in_top_tracks_days.add(day);
    }
  }
  for (const a of (snap.followed_artists || [])) {
    if (!a || !a.name) continue;
    const r = mark(a.name, day); r.followed = true; (a.genres || []).forEach((g) => r.genres.add(g));
  }
  const savedThisSnap = new Map();
  for (const t of (snap.saved_tracks || [])) for (const nm of ((t && t.artists) || [])) savedThisSnap.set(nm, (savedThisSnap.get(nm) || 0) + 1);
  for (const [nm, n] of savedThisSnap) { const r = mark(nm, day); if (n > r.saved_tracks_max) r.saved_tracks_max = n; }
  for (const t of (snap.recently_played || [])) for (const nm of ((t && t.artists) || [])) if (t.played_at) mark(nm, day).plays.add(t.played_at);
}

// --- build committable payloads per month ---
const now = new Date();
const payloads = [];
for (const [month, b] of months) {
  const artists = {};
  for (const [name, r] of [...b.artists.entries()].sort((a, c) => a[0].localeCompare(c[0]))) {
    const days = [...r.days].sort();
    artists[name] = {
      days_seen: r.days.size, first_seen: days[0], last_seen: days[days.length - 1],
      top_ranges: [...r.top_ranges].sort(), in_top_artists_days: r.in_top_artists_days.size,
      in_top_tracks_days: r.in_top_tracks_days.size, followed: r.followed,
      saved_tracks_max: r.saved_tracks_max, plays: r.plays.size, genres: [...r.genres].sort(),
    };
  }
  const rollup = {
    month, generated_at: now.toISOString(), source: 'spotify-web-api', harvester: 'music-curator/n8n rollup',
    schema: 1, snapshot_days: b.days.size, profile: b.profile, playlists_count: b.playlistsCount,
    artist_count: Object.keys(artists).length, artists,
  };
  payloads.push({
    month, path: `data/harvests/${month}.json`, content: JSON.stringify(rollup, null, 2) + '\n',
    branch: `harvest/rollup-${month}`,
    message: `chore(harvest): roll up ${month} Spotify snapshots (${b.days.size} days, ${rollup.artist_count} artists)`,
    prTitle: `chore(harvest): ${month} Spotify roll-up`,
    prBody: `Automated monthly Spotify roll-up for ${month} (${b.days.size} snapshot days, ${rollup.artist_count} artists).\n\nGenerated by the music-curator n8n consumer from the durable Redis queue. Inputs only -- does not rewrite the curated inventory.`,
  });
}

// --- git helpers (low-level data API -> no base64 needed) ---
async function gh(method, path, body) {
  return await helpers.httpRequest({
    method, url: GH + path,
    headers: { Authorization: 'Bearer ' + TOKEN, Accept: 'application/vnd.github+json', 'User-Agent': 'music-curator-n8n', 'X-GitHub-Api-Version': '2022-11-28' },
    body: body ? JSON.stringify(body) : undefined, json: true,
  });
}

const results = [];
for (const p of payloads) {
  // 1. base commit + its tree
  const ref = await gh('GET', `/repos/${OWNER}/${REPO}/git/ref/heads/${BASE}`);
  const baseSha = ref.object.sha;
  const baseCommit = await gh('GET', `/repos/${OWNER}/${REPO}/git/commits/${baseSha}`);
  // 2. blob (utf-8), tree, commit
  const blob = await gh('POST', `/repos/${OWNER}/${REPO}/git/blobs`, { content: p.content, encoding: 'utf-8' });
  const tree = await gh('POST', `/repos/${OWNER}/${REPO}/git/trees`, { base_tree: baseCommit.tree.sha, tree: [{ path: p.path, mode: '100644', type: 'blob', sha: blob.sha }] });
  const commit = await gh('POST', `/repos/${OWNER}/${REPO}/git/commits`, { message: p.message, tree: tree.sha, parents: [baseSha] });
  // 3. branch ref pointing at the new commit
  await gh('POST', `/repos/${OWNER}/${REPO}/git/refs`, { ref: `refs/heads/${p.branch}`, sha: commit.sha });
  // 4. open PR
  const pr = await gh('POST', `/repos/${OWNER}/${REPO}/pulls`, { title: p.prTitle, head: p.branch, base: BASE, body: p.prBody });
  // 5. auto-merge when green (GraphQL). GraphQL logic errors return HTTP 200 with an
  //    `errors` array -- e.g. "Pull request is in clean status" when nothing gates it.
  //    In that case merge directly (squash). If neither works, leave the PR open.
  let outcome = 'auto_merge_armed';
  const gql = await helpers.httpRequest({
    method: 'POST', url: GH + '/graphql',
    headers: { Authorization: 'Bearer ' + TOKEN, 'User-Agent': 'music-curator-n8n' },
    body: JSON.stringify({ query: 'mutation($id:ID!){enablePullRequestAutoMerge(input:{pullRequestId:$id,mergeMethod:SQUASH}){pullRequest{number}}}', variables: { id: pr.node_id } }),
    json: true,
  });
  if (gql && gql.errors && gql.errors.length) {
    try { await gh('PUT', `/repos/${OWNER}/${REPO}/pulls/${pr.number}/merge`, { merge_method: 'squash' }); outcome = 'merged_directly'; }
    catch (e) { outcome = 'pr_open_manual_merge'; }
  }
  results.push({ json: { month: p.month, pr: pr.number, branch: p.branch, outcome } });
}
return results;
"""

workflow = {
    "id": "spotifyRollup01",
    "name": "Spotify monthly roll-up → GitHub PR (music-curator)",
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
            "credentials": {"redis": {"id": "redisLocal01", "name": "Redis (local)"}},
        },
        {
            "parameters": {"jsCode": JS},
            "id": "b1000000-0000-4000-8000-000000000003",
            "name": "Roll up + commit PR",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [820, 300],
        },
        {
            # Drain the queue only after the Code node succeeds. If it throws, this
            # node is never reached and the buffered month is preserved.
            "parameters": {
                "operation": "delete",
                "key": "spotify:harvests",
                "options": {},
            },
            "id": "b1000000-0000-4000-8000-000000000004",
            "name": "Drain queue",
            "type": "n8n-nodes-base.redis",
            "typeVersion": 1,
            "position": [1040, 300],
            "credentials": {"redis": {"id": "redisLocal01", "name": "Redis (local)"}},
        },
    ],
    "connections": {
        "Monthly 1st 02:00": {"main": [[{"node": "Read queue", "type": "main", "index": 0}]]},
        "Read queue": {"main": [[{"node": "Roll up + commit PR", "type": "main", "index": 0}]]},
        "Roll up + commit PR": {"main": [[{"node": "Drain queue", "type": "main", "index": 0}]]},
    },
    "settings": {"executionOrder": "v1", "saveManualExecutions": True},
    "active": False,
}

out = pathlib.Path(__file__).resolve().parent / "rollup.workflow.json"
out.write_text(json.dumps(workflow, indent=2) + "\n")
print("wrote", out, out.stat().st_size, "bytes")
json.loads(out.read_text())
print("valid JSON OK")
