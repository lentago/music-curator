#!/usr/bin/env python3
"""Generate the n8n workflow JSON for the Spotify daily harvest.

Kept as a generator so the embedded Code-node JS stays readable and the emitted
JSON is always valid. Targets n8n 2.27 (node typeVersions valid in 2.x).
"""
import json
import pathlib

JS = r"""// Spotify daily harvest — music-curator. n8n Code node, "Run Once for All Items".
// Secrets come from the n8n host env (needs N8N_BLOCK_ENV_ACCESS_IN_NODE=false):
//   SPOTIFY_CLIENT_ID, SPOTIFY_REFRESH_TOKEN   (see harvest/README.md)
// PKCE public-client refresh: no client secret is used anywhere.
const helpers = this.helpers;
const CID = $env.SPOTIFY_CLIENT_ID;
const RT = $env.SPOTIFY_REFRESH_TOKEN;
if (!CID || !RT) {
  throw new Error('Missing SPOTIFY_CLIENT_ID / SPOTIFY_REFRESH_TOKEN in n8n env (set N8N_BLOCK_ENV_ACCESS_IN_NODE=false).');
}

// setTimeout may be absent in some sandboxes — degrade to no-op sleep.
const sleep = (ms) => (typeof setTimeout === 'function' ? new Promise((r) => setTimeout(r, ms)) : Promise.resolve());

// --- refresh the access token ---
let tokenResp = await helpers.httpRequest({
  method: 'POST',
  url: 'https://accounts.spotify.com/api/token',
  headers: { 'content-type': 'application/x-www-form-urlencoded' },
  body: new URLSearchParams({ grant_type: 'refresh_token', refresh_token: RT, client_id: CID }).toString(),
});
if (typeof tokenResp === 'string') tokenResp = JSON.parse(tokenResp);
const access = tokenResp.access_token;
if (!access) throw new Error('No access_token from refresh: ' + JSON.stringify(tokenResp));

// --- GET helper with 429 backoff ---
async function api(url, qs) {
  for (let attempt = 0; attempt < 5; attempt++) {
    try {
      return await helpers.httpRequest({ method: 'GET', url, qs, headers: { Authorization: 'Bearer ' + access }, json: true });
    } catch (e) {
      const sc = e.statusCode || e.httpCode || (e.response && e.response.statusCode);
      if (sc === 429) {
        const ra = Number((e.response && e.response.headers && e.response.headers['retry-after']) || 2);
        await sleep((ra + 1) * 1000);
        continue;
      }
      throw e;
    }
  }
  throw new Error('Too many 429s for ' + url);
}

// --- follow offset-paginated `next` links ---
async function pageAll(url, qs, cap = 10000) {
  const out = [];
  let page = await api(url, qs);
  while (page && page.items) {
    out.push(...page.items);
    if (!page.next || out.length >= cap) break;
    page = await api(page.next);
    await sleep(120);
  }
  return out;
}

// --- trimmers (popularity was removed from the API in Feb 2026, so it's absent by design) ---
const trimArtist = (a) => ({ id: a.id, name: a.name, genres: a.genres || [] });
const trimTrack = (t) => t && {
  id: t.id, name: t.name, uri: t.uri,
  artists: (t.artists || []).map((x) => x.name),
  album: t.album && t.album.name,
  duration_ms: t.duration_ms,
};

const API = 'https://api.spotify.com/v1';
const ranges = ['short_term', 'medium_term', 'long_term'];

const me = await api(API + '/me');

const top = { artists: {}, tracks: {} };
for (const r of ranges) {
  const ta = await api(API + '/me/top/artists', { time_range: r, limit: 50 });
  top.artists[r] = (ta.items || []).map(trimArtist);
  const tt = await api(API + '/me/top/tracks', { time_range: r, limit: 50 });
  top.tracks[r] = (tt.items || []).map(trimTrack);
}

const savedRaw = await pageAll(API + '/me/tracks', { limit: 50 });
const saved_tracks = savedRaw.map((it) => ({ added_at: it.added_at, ...trimTrack(it.track) }));

const followed_artists = [];
{
  let page = await api(API + '/me/following', { type: 'artist', limit: 50 });
  while (page && page.artists) {
    followed_artists.push(...(page.artists.items || []).map(trimArtist));
    if (!page.artists.next) break;
    page = await api(page.artists.next);
    await sleep(120);
  }
}

const playlistsRaw = await pageAll(API + '/me/playlists', { limit: 50 });
const playlists = playlistsRaw.map((p) => ({
  id: p.id, name: p.name, owner: p.owner && p.owner.id,
  tracks_total: p.tracks && p.tracks.total, public: p.public, collaborative: p.collaborative,
}));

const rp = await api(API + '/me/player/recently-played', { limit: 50 });
const recently_played = (rp.items || []).map((it) => ({ played_at: it.played_at, ...trimTrack(it.track) }));

const now = new Date();
const dateStr = now.toISOString().slice(0, 10);
const snapshot = {
  harvested_at: now.toISOString(),
  source: 'spotify-web-api',
  harvester: 'music-curator/n8n',
  schema: 1,
  profile: { id: me.id, display_name: me.display_name, country: me.country, product: me.product, followers: me.followers && me.followers.total },
  top,
  saved_tracks,
  followed_artists,
  playlists,
  recently_played,
  counts: { saved_tracks: saved_tracks.length, followed_artists: followed_artists.length, playlists: playlists.length, recently_played: recently_played.length },
};

// Emit the snapshot as a JSON string for the Redis Push node (durable queue).
return [{ json: { harvested_at: snapshot.harvested_at, counts: snapshot.counts, snapshot: JSON.stringify(snapshot) } }];
"""

workflow = {
    "name": "Spotify daily harvest → Redis (music-curator)",
    "nodes": [
        {
            "parameters": {
                "rule": {"interval": [{"field": "days", "triggerAtHour": 6}]}
            },
            "id": "a1000000-0000-4000-8000-000000000001",
            "name": "Daily 06:00",
            "type": "n8n-nodes-base.scheduleTrigger",
            "typeVersion": 1.2,
            "position": [380, 300],
        },
        {
            "parameters": {"jsCode": JS},
            "id": "a1000000-0000-4000-8000-000000000002",
            "name": "Harvest Spotify",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [620, 300],
        },
        {
            # Push the snapshot JSON onto a durable Redis list (the queue); the
            # monthly roll-up workflow drains it. Assign the Redis credential in
            # the n8n UI after import (host `redis`, port 6379, same compose net).
            "parameters": {
                "operation": "push",
                "list": "spotify:harvests",
                "messageData": "={{ $json.snapshot }}",
                "tail": True,
                "options": {},
            },
            "id": "a1000000-0000-4000-8000-000000000003",
            "name": "Publish to Redis queue",
            "type": "n8n-nodes-base.redis",
            "typeVersion": 1,
            "position": [860, 300],
        },
    ],
    "connections": {
        "Daily 06:00": {"main": [[{"node": "Harvest Spotify", "type": "main", "index": 0}]]},
        "Harvest Spotify": {"main": [[{"node": "Publish to Redis queue", "type": "main", "index": 0}]]},
    },
    "settings": {"executionOrder": "v1", "saveManualExecutions": True},
    "active": False,
}

out = pathlib.Path(__file__).resolve().parent / "spotify-harvest.workflow.json"
out.write_text(json.dumps(workflow, indent=2) + "\n")
print("wrote", out, out.stat().st_size, "bytes")
# sanity: reparse
json.loads(out.read_text())
print("valid JSON OK")
