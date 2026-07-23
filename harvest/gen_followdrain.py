#!/usr/bin/env python3
"""Generate the n8n workflow JSON for the Spotify follow-event drain.

The plumbing half of follow ingestion. The watcher (spotifyFollowWatch01)
pushes follow/unfollow events to the Redis list `spotify:follow-events` every 15
minutes; this workflow drains that list once a day, appends the new events to
the durable log `data/harvests/follow-events.jsonl`, and opens a PR with just
that append. It does NOT decide anything about the inventory and it does NOT arm
auto-merge -- the fold (harvest_merge.py) runs in a GitHub Action against the PR
and merges it only when the batch is safe (see .github/workflows/follow-fold.yml).

Why the split: the fold is tested Python that must not be reimplemented in the
n8n Code-node sandbox, and it needs to classify each event (seed / owned /
discarded / unfollow) to decide whether the change may auto-merge. n8n's only
job here is what only n8n can do -- reach the LAN Redis and get the raw events
into git. Everything downstream is the Action's.

Deliberately NOT arming auto-merge is load-bearing: `main` has no required
status checks, so an armed PR would merge instantly -- before the fold runs --
landing the log with no inventory change. The PR must stay open for the Action.

Kept as a generator so the embedded Code-node JS stays readable and the emitted
JSON is always valid. Targets n8n 2.27 (node typeVersions valid in 2.x).
"""
import json
import pathlib

JS = r"""// Spotify follow-event drain -- music-curator. n8n Code node, "Run Once for All Items".
// Input: the "Read events" Redis Get node (keyType=list) put the raw list into
// $json.queue as an array of follow-event JSON strings (as pushed by the watcher).
// Action: append the new events to data/harvests/follow-events.jsonl on a branch
// and open a PR. The fold Action folds + merges it; this node never arms merge.
const helpers = this.helpers;
const TOKEN = $env.GITHUB_TOKEN;
if (!TOKEN) throw new Error('Missing GITHUB_TOKEN in n8n env (fine-grained PAT, Contents + Pull requests write; set N8N_BLOCK_ENV_ACCESS_IN_NODE=false).');
const OWNER = 'lentago', REPO = 'music-curator', BASE = 'main';
const GH = 'https://api.github.com';
const LOG = 'data/harvests/follow-events.jsonl';

const first = $input.first();
const raw = (first && first.json && first.json.queue) || [];
const queue = Array.isArray(raw) ? raw : [raw];
const incoming = [];
for (const entry of queue) {
  try { incoming.push(typeof entry === 'string' ? JSON.parse(entry) : entry); } catch (e) { /* skip */ }
}
if (!incoming.length) return [];

async function gh(method, path, body, accept) {
  return await helpers.httpRequest({
    method, url: GH + path,
    headers: { Authorization: 'Bearer ' + TOKEN, Accept: accept || 'application/vnd.github+json',
               'User-Agent': 'music-curator-n8n', 'X-GitHub-Api-Version': '2022-11-28' },
    body: body ? JSON.stringify(body) : undefined,
    json: accept ? false : true,
  });
}

// --- current log content (raw, so no base64 decode in the sandbox) ---
let existing = '';
try {
  existing = await gh('GET', `/repos/${OWNER}/${REPO}/contents/${LOG}?ref=${BASE}`,
                      null, 'application/vnd.github.raw');
  if (typeof existing !== 'string') existing = String(existing);
} catch (e) {
  const sc = e.statusCode || e.httpCode || (e.response && e.response.statusCode);
  if (sc !== 404) throw e;   // 404 = log not created yet; anything else is real
  existing = '';
}

// --- dedup by the fold's own event id (artist + detected_at) ---
const key = (e) => (e.artist || '') + '\u0000' + (e.detected_at || '');
const seen = new Set();
for (const line of existing.split('\n')) {
  const t = line.trim();
  if (!t) continue;
  try { seen.add(key(JSON.parse(t))); } catch (_) { /* tolerate a bad line */ }
}
const fresh = [];
for (const e of incoming) {
  const k = key(e);
  if (seen.has(k)) continue;
  seen.add(k);
  fresh.push(e);
}
if (!fresh.length) return [];   // everything already logged; nothing to commit

const head = existing && !existing.endsWith('\n') ? existing + '\n' : existing;
const content = head + fresh.map((e) => JSON.stringify(e)).join('\n') + '\n';

const follows = fresh.filter((e) => e.type === 'follow').map((e) => e.artist);
const unfollows = fresh.filter((e) => e.type === 'unfollow').map((e) => e.artist);
const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
const branch = `harvest/follows-${stamp}`;
const summary = [
  follows.length ? `${follows.length} follow(s): ${follows.join(', ')}` : null,
  unfollows.length ? `${unfollows.length} unfollow(s): ${unfollows.join(', ')}` : null,
].filter(Boolean).join('; ');

// --- commit the append (git data API -> utf-8 blob, no base64) ---
const ref = await gh('GET', `/repos/${OWNER}/${REPO}/git/ref/heads/${BASE}`);
const baseSha = ref.object.sha;
const baseCommit = await gh('GET', `/repos/${OWNER}/${REPO}/git/commits/${baseSha}`);
const blob = await gh('POST', `/repos/${OWNER}/${REPO}/git/blobs`, { content, encoding: 'utf-8' });
const tree = await gh('POST', `/repos/${OWNER}/${REPO}/git/trees`,
  { base_tree: baseCommit.tree.sha, tree: [{ path: LOG, mode: '100644', type: 'blob', sha: blob.sha }] });
const commit = await gh('POST', `/repos/${OWNER}/${REPO}/git/commits`,
  { message: `chore(harvest): ${fresh.length} follow event(s)\n\n${summary}`, tree: tree.sha, parents: [baseSha] });
await gh('POST', `/repos/${OWNER}/${REPO}/git/refs`, { ref: `refs/heads/${branch}`, sha: commit.sha });

// --- open the PR, but DO NOT arm auto-merge. The fold Action folds this PR and
//     merges it only when every event is a safe seed/provenance change. ---
const body = [
  `Automated Spotify follow drain. ${summary}.`,
  '',
  'This PR appends the raw events to `data/harvests/follow-events.jsonl`. The',
  '`follow-fold` GitHub Action folds them into the inventory and merges this PR',
  'only if the batch is exclusively new reservoir seeds and provenance; a follow',
  'of a discarded artist or any unfollow holds it open for review.',
].join('\n');
const pr = await gh('POST', `/repos/${OWNER}/${REPO}/pulls`,
  { title: `chore(harvest): ${fresh.length} follow event(s)`, head: branch, base: BASE, body });

return [{ json: { pr: pr.number, branch, added: fresh.length,
                  follows: follows.length, unfollows: unfollows.length } }];
"""

workflow = {
    "id": "spotifyFollowDrain01",
    "name": "Spotify follow drain → GitHub PR (music-curator)",
    "nodes": [
        {
            # Daily 05:00 -- after a full day of 15-min watcher runs, before the
            # 06:00 producer. Follows are rare, so most days drain nothing.
            "parameters": {
                "rule": {"interval": [{"field": "days", "triggerAtHour": 5}]}
            },
            "id": "d1000000-0000-4000-8000-000000000001",
            "name": "Daily 05:00",
            "type": "n8n-nodes-base.scheduleTrigger",
            "typeVersion": 1.2,
            "position": [380, 300],
        },
        {
            # Non-destructive read of the whole list (keyType=list -> LRANGE 0 -1).
            "parameters": {
                "operation": "get",
                "propertyName": "queue",
                "key": "spotify:follow-events",
                "keyType": "list",
                "options": {},
            },
            "id": "d1000000-0000-4000-8000-000000000002",
            "name": "Read events",
            "type": "n8n-nodes-base.redis",
            "typeVersion": 1,
            "position": [600, 300],
            "credentials": {"redis": {"id": "redisLocal01", "name": "Redis (local)"}},
        },
        {
            "parameters": {"jsCode": JS},
            "id": "d1000000-0000-4000-8000-000000000003",
            "name": "Append log + open PR",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [820, 300],
        },
        {
            # Drain the list only after the Code node succeeds. If it throws, the
            # events are preserved for the next run (and the log append dedups, so
            # a partial failure that did commit will not double-log).
            "parameters": {
                "operation": "delete",
                "key": "spotify:follow-events",
                "options": {},
            },
            "id": "d1000000-0000-4000-8000-000000000004",
            "name": "Drain events",
            "type": "n8n-nodes-base.redis",
            "typeVersion": 1,
            "position": [1040, 300],
            "credentials": {"redis": {"id": "redisLocal01", "name": "Redis (local)"}},
        },
    ],
    "connections": {
        "Daily 05:00": {"main": [[{"node": "Read events", "type": "main", "index": 0}]]},
        "Read events": {"main": [[{"node": "Append log + open PR", "type": "main", "index": 0}]]},
        "Append log + open PR": {"main": [[{"node": "Drain events", "type": "main", "index": 0}]]},
    },
    "settings": {"executionOrder": "v1", "saveManualExecutions": True},
    "active": False,
}

out = pathlib.Path(__file__).resolve().parent / "follow-drain.workflow.json"
out.write_text(json.dumps(workflow, indent=2) + "\n")
print("wrote", out, out.stat().st_size, "bytes")
json.loads(out.read_text())
print("valid JSON OK")
