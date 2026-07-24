"""
ChipSutra Google OAuth abstraction.

Modes:
- 'emergent': uses auth.emergentagent.com session-id flow (default when EMERGENT_LLM_KEY is set)
- 'standalone': standard Google OAuth 2.0 auth-code flow. Requires
  GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI env vars.
- 'disabled': neither configured — Google button hides on the frontend.

Public API:
    google_mode() -> "emergent" | "standalone" | "disabled"
    async resolve_emergent_session(session_id) -> {"email","name","picture"}
    build_google_auth_url(state) -> URL string
    async exchange_code(code) -> {"email","name","picture"}
"""
import os
import logging
import requests
import secrets

logger = logging.getLogger("chipsutra.google")

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "")

EMERGENT_AUTH_ENDPOINT = "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


def google_mode() -> str:
    if EMERGENT_LLM_KEY:
        return "emergent"
    if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and GOOGLE_REDIRECT_URI:
        return "standalone"
    return "disabled"


def resolve_emergent_session(session_id: str) -> dict:
    r = requests.get(EMERGENT_AUTH_ENDPOINT, headers={"X-Session-ID": session_id}, timeout=15)
    if r.status_code != 200:
        raise RuntimeError("Invalid Google session")
    payload = r.json()
    return {
        "email": (payload.get("email") or "").lower(),
        "name": payload.get("name"),
        "picture": payload.get("picture"),
    }


def build_google_auth_url(state: str = None) -> str:
    state = state or secrets.token_urlsafe(24)
    from urllib.parse import urlencode
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str) -> dict:
    """Exchange an auth code for user info (sync — called from FastAPI endpoint)."""
    tr = requests.post(GOOGLE_TOKEN_URL, data={
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "grant_type": "authorization_code",
    }, timeout=15)
    if tr.status_code != 200:
        raise RuntimeError(f"Google token exchange failed: {tr.text}")
    access_token = tr.json().get("access_token")
    if not access_token:
        raise RuntimeError("No access_token in Google response")
    ur = requests.get(GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=15)
    ur.raise_for_status()
    p = ur.json()
    return {
        "email": (p.get("email") or "").lower(),
        "name": p.get("name") or (p.get("email") or "").split("@")[0],
        "picture": p.get("picture"),
    }
