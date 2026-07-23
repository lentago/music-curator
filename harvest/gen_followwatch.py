#!/usr/bin/env python3
"""Generate the n8n workflow JSON for the Spotify follow watcher.

The third workflow in the harvest family, and the only one that is latency-
sensitive. The daily producer and monthly consumer both work on aggregates that
can be reconstructed later; this one captures something ephemeral -- what was
playing at the moment a follow happened -- which is gone forever if not caught
close to the event.

Spotify exposes no `followed_at`, so a follow can only be detected by diffing
the follow list against a remembered previous state. Redis holds that state
(`spotify:follows:last`); each run compares, emits an event per change, and
updates the baseline.

Kept as a generator so the embedded Code-node JS stays readable and the emitted
JSON is always valid. Targets n8n 2.27 (node typeVersions valid in 2.x).
"""
import json
import pathlib

JS = r"""// Spotify follow watcher -- music-curator. n8n Code node, "Run Once for All Items".
// Input: the "Read baseline" Redis Get node put the previous follow set into
// $json.prev (a JSON array string written by this workflow's own Set node).
// Action: diff the live follow list against the baseline; for each change,
// capture what is playing right now (plus a short recently-played tail as a
// fallback for a follow made a few minutes ago).
// Output: ONE item carrying the events and the new baseline. The fan-out node
// downstream turns events into individual Redis pushes.
//
// Secrets come from the n8n host env (needs N8N_BLOCK_ENV_ACCESS_IN_NODE=false):
//   SPOTIFY_CLIENT_ID, SPOTIFY_REFRESH_TOKEN   (see harvest/README.md)
// PKCE public-client refresh: no client secret is used anywhere.
const helpers = this.helpers;
const CID = $env.SPOTIFY_CLIENT_ID;
const RT = $env.SPOTIFY_REFRESH_TOKEN;
if (!CID || !RT) {
  throw new Error('Missing SPOTIFY_CLIENT_ID / SPOTIFY_REFRESH_TOKEN in n8n env (set N8N_BLOCK_ENV_ACCESS_IN_NODE=false).');
}

const sleep = (ms) => (typeof setTimeout === 'function' ? new Promise((r) => setTimeout(r, ms)) : Promise.resolve());

// --- baseline ---
// A missing baseline is a hard error, not a bootstrap: treating an empty
// previous set as "everything is new" would emit a false follow event for every
// artist already followed. Seed the key once at deploy time (see README).
const first = $input.first();
const rawPrev = (first && first.json && first.json.prev);
if (rawPrev === undefined || rawPrev === null || rawPrev === '') {
  throw new Error('No baseline at spotify:follows:last -- seed it before activating (see harvest/README.md, follow watcher deploy).');
}
let prevList;
try { prevList = typeof rawPrev === 'string' ? JSON.parse(rawPrev) : rawPrev; }
catch (e) { throw new Error('Baseline at spotify:follows:last is not JSON: ' + String(rawPrev).slice(0, 120)); }
if (!Array.isArray(prevList)) throw new Error('Baseline at spotify:follows:last is not a JSON array.');
const prev = new Set(prevList);

// --- refresh the access token ---
let tokenResp = await helpers.httpRequest({
  method: 'POST',
  url: 'https://accounts.spotify.com/api/token',
  headers: { 'content-type': 'application/x-www-form-urlencoded' },
  // Manual form-encode: the Code-node sandbox has no URLSearchParams.
  body: 'grant_type=refresh_token&refresh_token=' + encodeURIComponent(RT) + '&client_id=' + encodeURIComponent(CID),
});
if (typeof tokenResp === 'string') tokenResp = JSON.parse(tokenResp);
const access = tokenResp.access_token;
if (!access) throw new Error('No access_token from refresh: ' + JSON.stringify(tokenResp));

// --- GET helper with 429 backoff. Returns null on 204 (nothing playing). ---
async function api(url, qs) {
  for (let attempt = 0; attempt < 5; attempt++) {
    try {
      const r = await helpers.httpRequest({ method: 'GET', url, qs, headers: { Authorization: 'Bearer ' + access }, json: true });
      return (r === '' || r === undefined) ? null : r;
    } catch (e) {
      const sc = e.statusCode || e.httpCode || (e.response && e.response.statusCode);
      if (sc === 429) {
        const ra = Number((e.response && e.response.headers && e.response.headers['retry-after']) || 2);
        await sleep((ra + 1) * 1000);
        continue;
      }
      if (sc === 204 || sc === 404) return null;   // nothing playing / no active device
      throw e;
    }
  }
  throw new Error('Too many 429s for ' + url);
}

// --- the live follow set ---
const API = 'https://api.spotify.com/v1';
const followed = [];
let page = await api(API + '/me/following', { type: 'artist', limit: 50 });
while (page && page.artists) {
  followed.push(...(page.artists.items || []).map((a) => ({ id: a.id, name: a.name, genres: a.genres || [] })));
  const next = page.artists.next;
  if (!next || followed.length > 5000) break;
  page = await api(next);
}
if (!followed.length) throw new Error('Follow list came back empty -- refusing to treat that as 64 unfollows.');

const nowNames = followed.map((a) => a.name);
const nowSet = new Set(nowNames);
const added = followed.filter((a) => !prev.has(a.name));
const removed = [...prev].filter((n) => !nowSet.has(n));

// --- capture the moment, only when something actually changed ---
const detected_at = new Date().toISOString();
let nowPlaying = null, recent = [];
if (added.length) {
  const cur = await api(API + '/me/player/currently-playing');
  if (cur && cur.item) {
    nowPlaying = {
      track: cur.item.name,
      artists: (cur.item.artists || []).map((x) => x.name),
      album: cur.item.album && cur.item.album.name,
      uri: cur.item.uri,
      progress_ms: cur.progress_ms,
      is_playing: Boolean(cur.is_playing),
    };
  }
  // Fallback for a follow made a few minutes ago: the tail of recently-played.
  const rp = await api(API + '/me/player/recently-played', { limit: 5 });
  recent = ((rp && rp.items) || []).map((it) => ({
    track: it.track && it.track.name,
    artists: ((it.track && it.track.artists) || []).map((x) => x.name),
    album: it.track && it.track.album && it.track.album.name,
    uri: it.track && it.track.uri,
    played_at: it.played_at,
  }));
}

const events = [];
for (const a of added) {
  // `trigger` is the honest label: what was playing when the follow was
  // DETECTED, within one watcher interval of the follow itself. If the artist
  // appears in now-playing or the recent tail, that is near-certainly the song
  // that caused the follow -- flagged so the consumer needn't re-derive it.
  const byArtist = (t) => (t.artists || []).indexOf(a.name) !== -1;
  const selfMatch = (nowPlaying && byArtist(nowPlaying)) ? 'now_playing'
    : (recent.find(byArtist) ? 'recently_played' : null);
  events.push({
    type: 'follow', artist: a.name, artist_id: a.id, genres: a.genres,
    detected_at, now_playing: nowPlaying,
    recent_tail: recent,
    trigger_confidence: selfMatch ? 'high' : 'low',
    trigger_source: selfMatch,
    trigger_track: selfMatch === 'now_playing' ? nowPlaying
      : (selfMatch === 'recently_played' ? recent.find(byArtist) : null),
  });
}
for (const name of removed) {
  events.push({ type: 'unfollow', artist: name, detected_at });
}

return [{
  json: {
    detected_at,
    changed: events.length > 0,
    added: added.length,
    removed: removed.length,
    followed_total: followed.length,
    events: JSON.stringify(events),
    baseline: JSON.stringify(nowNames.slice().sort()),
  },
}];
"""

# Fan-out: one item per event, so the Redis Push node writes them individually.
# Emitting zero items when nothing changed is deliberate -- it short-circuits
# both downstream nodes, and skipping the baseline write is safe precisely
# because an unchanged follow set means the stored baseline is already correct.
FANOUT_JS = r"""// Fan out the detected events into one item each. No changes -> no items ->
// neither the Redis push nor the baseline write runs this cycle.
const first = $input.first();
const j = (first && first.json) || {};
let events = [];
try { events = JSON.parse(j.events || '[]'); } catch (e) { events = []; }
if (!events.length) return [];
return events.map((e) => ({ json: { event: JSON.stringify(e), baseline: j.baseline } }));
"""

workflow = {
    "id": "spotifyFollowWatch01",
    "name": "Spotify follow watcher → Redis (music-curator)",
    "nodes": [
        {
            "parameters": {
                "rule": {"interval": [{"field": "minutes", "minutesInterval": 15}]}
            },
            "id": "c1000000-0000-4000-8000-000000000001",
            "name": "Every 15 minutes",
            "type": "n8n-nodes-base.scheduleTrigger",
            "typeVersion": 1.2,
            "position": [380, 300],
        },
        {
            # Non-destructive read of the remembered follow set. Written by the
            # "Save baseline" node below; seeded once at deploy time.
            "parameters": {
                "operation": "get",
                "propertyName": "prev",
                "key": "spotify:follows:last",
                "keyType": "automatic",
                "options": {},
            },
            "id": "c1000000-0000-4000-8000-000000000002",
            "name": "Read baseline",
            "type": "n8n-nodes-base.redis",
            "typeVersion": 1,
            # Matches the credential the producer/consumer already use on this
            # box, so an import needs no UI step to become runnable.
            "credentials": {"redis": {"id": "redisLocal01", "name": "Redis (local)"}},
            "position": [600, 300],
        },
        {
            "parameters": {"jsCode": JS},
            "id": "c1000000-0000-4000-8000-000000000003",
            "name": "Detect follow changes",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [820, 300],
        },
        {
            "parameters": {"jsCode": FANOUT_JS},
            "id": "c1000000-0000-4000-8000-000000000004",
            "name": "Fan out events",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [1040, 300],
        },
        {
            # Events are pushed BEFORE the baseline moves. A crash between the
            # two re-detects the same change next cycle (a duplicate event the
            # consumer can dedupe on artist + detected_at); the reverse order
            # would lose the capture permanently, and the whole point of this
            # workflow is that the captured moment is unrecoverable.
            "parameters": {
                "operation": "push",
                "list": "spotify:follow-events",
                "messageData": "={{ $json.event }}",
                "tail": True,
                "options": {},
            },
            "id": "c1000000-0000-4000-8000-000000000005",
            "name": "Publish follow events",
            "type": "n8n-nodes-base.redis",
            "typeVersion": 1,
            # Matches the credential the producer/consumer already use on this
            # box, so an import needs no UI step to become runnable.
            "credentials": {"redis": {"id": "redisLocal01", "name": "Redis (local)"}},
            "position": [1260, 300],
        },
        {
            "parameters": {
                "operation": "set",
                "key": "spotify:follows:last",
                "value": "={{ $json.baseline }}",
                "keyType": "string",
                "options": {},
            },
            "id": "c1000000-0000-4000-8000-000000000006",
            "name": "Save baseline",
            "type": "n8n-nodes-base.redis",
            "typeVersion": 1,
            # Matches the credential the producer/consumer already use on this
            # box, so an import needs no UI step to become runnable.
            "credentials": {"redis": {"id": "redisLocal01", "name": "Redis (local)"}},
            "position": [1480, 300],
        },
    ],
    "connections": {
        "Every 15 minutes": {"main": [[{"node": "Read baseline", "type": "main", "index": 0}]]},
        "Read baseline": {"main": [[{"node": "Detect follow changes", "type": "main", "index": 0}]]},
        "Detect follow changes": {"main": [[{"node": "Fan out events", "type": "main", "index": 0}]]},
        "Fan out events": {"main": [[{"node": "Publish follow events", "type": "main", "index": 0}]]},
        "Publish follow events": {"main": [[{"node": "Save baseline", "type": "main", "index": 0}]]},
    },
    "settings": {"executionOrder": "v1", "saveManualExecutions": True},
    "active": False,
}

out = pathlib.Path(__file__).resolve().parent / "follow-watch.workflow.json"
out.write_text(json.dumps(workflow, indent=2) + "\n")
print("wrote", out, out.stat().st_size, "bytes")
json.loads(out.read_text())
print("valid JSON OK")
