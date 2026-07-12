#!/usr/bin/env python3
"""
Spotify Web API — one-time OAuth bootstrap (loopback PKCE).

Run this ONCE on a machine with a browser (your workstation) to mint the
long-lived **refresh token** the periodic n8n harvester uses. Nothing here is
committed: the script only prints the token to your terminal, and you paste it
into the n8n host's env file (see harvest/README.md).

Why loopback PKCE and not n8n's built-in Spotify credential?
  Since 2025-04-09 Spotify rejects HTTP redirect URIs except loopback literals
  (http://127.0.0.1:PORT). n8n's callback is http://<lan-ip>:5678/... — plain
  HTTP on a non-loopback IP — so Spotify refuses it. A loopback redirect on the
  workstation is the only zero-infrastructure path that Spotify accepts.
  PKCE means no client secret is needed anywhere (public-client flow).

Prerequisites (see harvest/README.md for the click-path):
  1. A Spotify Developer app (Dashboard → Create app). Post-2026-02 this needs
     a Premium account, sits in Development Mode, and you must add your own
     Spotify account under the app's "User Management" (<=5 users allowed).
  2. The app's Redirect URI set to EXACTLY:  http://127.0.0.1:8888/callback
  3. Your app's Client ID.

Usage:
  python harvest/spotify_auth_bootstrap.py --client-id <CLIENT_ID>
  # a browser opens; approve; the refresh token prints to the terminal.

Stdlib only — no pip install.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import secrets
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser

# Read scopes the harvester needs. Keep in sync with harvest/README.md.
SCOPES = [
    "user-read-private",           # profile: country, product (premium/free)
    "user-read-email",             # profile: email
    "user-top-read",               # top artists + tracks (3 time ranges)
    "user-read-recently-played",   # last 50 plays
    "user-library-read",           # liked/saved tracks + albums
    "user-follow-read",            # followed artists (+ their genres)
    "playlist-read-private",       # private playlists
    "playlist-read-collaborative", # collaborative playlists
]

REDIRECT_PORT = 8888
REDIRECT_URI = f"http://127.0.0.1:{REDIRECT_PORT}/callback"
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"

_result: dict[str, str] = {}


def _pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for PKCE S256."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 (stdlib signature)
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        params = urllib.parse.parse_qs(parsed.query)
        _result["code"] = params.get("code", [""])[0]
        _result["state"] = params.get("state", [""])[0]
        _result["error"] = params.get("error", [""])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        body = (
            "<html><body style='font-family:sans-serif;padding:2rem'>"
            "<h2>Spotify authorization received.</h2>"
            "<p>You can close this tab and return to the terminal.</p>"
            "</body></html>"
        )
        self.wfile.write(body.encode())

    def log_message(self, *_args) -> None:  # silence the default logging
        pass


def _exchange(client_id: str, code: str, verifier: str) -> dict:
    data = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": verifier,
        }
    ).encode()
    req = urllib.request.Request(
        TOKEN_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (fixed host)
        import json

        return json.load(resp)


def main() -> int:
    ap = argparse.ArgumentParser(description="One-time Spotify OAuth bootstrap (loopback PKCE).")
    ap.add_argument("--client-id", required=True, help="Spotify app Client ID")
    args = ap.parse_args()

    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)
    auth_query = urllib.parse.urlencode(
        {
            "client_id": args.client_id,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": " ".join(SCOPES),
            "code_challenge_method": "S256",
            "code_challenge": challenge,
            "state": state,
        }
    )
    auth_url = f"{AUTH_URL}?{auth_query}"

    server = http.server.HTTPServer(("127.0.0.1", REDIRECT_PORT), _CallbackHandler)
    threading.Thread(target=server.handle_request, daemon=True).start()

    print(f"\nOpening browser for Spotify consent (redirect {REDIRECT_URI}).")
    print(f"If it doesn't open, paste this URL:\n\n{auth_url}\n")
    try:
        webbrowser.open(auth_url)
    except Exception:  # noqa: BLE001 — headless box: fall back to manual paste
        pass

    # Block until the callback thread has serviced one request.
    for t in threading.enumerate():
        if t is not threading.main_thread():
            t.join(timeout=300)
    server.server_close()

    if _result.get("error"):
        print(f"\nAuthorization failed: {_result['error']}", file=sys.stderr)
        return 1
    if _result.get("state") != state:
        print("\nState mismatch — aborting (possible CSRF).", file=sys.stderr)
        return 1
    code = _result.get("code")
    if not code:
        print("\nNo authorization code received (timed out?).", file=sys.stderr)
        return 1

    tokens = _exchange(args.client_id, code, verifier)
    refresh = tokens.get("refresh_token")
    if not refresh:
        print(f"\nNo refresh_token in response: {tokens}", file=sys.stderr)
        return 1

    print("\n" + "=" * 68)
    print("SUCCESS. Paste these into the n8n host's /opt/n8n/.env (chmod 600),")
    print("NOT into any git repo:")
    print("=" * 68)
    print(f"SPOTIFY_CLIENT_ID={args.client_id}")
    print(f"SPOTIFY_REFRESH_TOKEN={refresh}")
    print("=" * 68)
    print("Then: cd /opt/n8n && docker compose up -d   (reloads env)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
