"""Minimal Gmail REST client (OAuth 2.0, messages, History API, push watch)."""

import base64
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from email_rag.config import settings
from email_rag.services import secrets

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://gmail.googleapis.com/gmail/v1/users/me"
SCOPES = [
    "openid",
    "email",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def _client_creds() -> dict[str, str]:
    return secrets.get_cached_json(settings().google_client_secret_arn)


def build_auth_url(state: str) -> str:
    params = {
        "client_id": _client_creds()["client_id"],
        "redirect_uri": settings().oauth_redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str) -> dict[str, Any]:
    creds = _client_creds()
    resp = httpx.post(TOKEN_URL, data={
        "code": code,
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
        "redirect_uri": settings().oauth_redirect_uri,
        "grant_type": "authorization_code",
    }, timeout=15)
    resp.raise_for_status()
    tokens = resp.json()
    tokens["expires_at"] = int(time.time()) + int(tokens.get("expires_in", 3600))
    return tokens


class GmailClient:
    """Gmail client bound to one connected account; refreshes and persists tokens as needed."""

    def __init__(self, secret_arn: str):
        self.secret_arn = secret_arn
        self.tokens = secrets.get_json(secret_arn)
        self.http = httpx.Client(base_url=API, timeout=30)

    def _access_token(self) -> str:
        if self.tokens.get("expires_at", 0) - 60 < time.time():
            creds = _client_creds()
            resp = httpx.post(TOKEN_URL, data={
                "client_id": creds["client_id"],
                "client_secret": creds["client_secret"],
                "refresh_token": self.tokens["refresh_token"],
                "grant_type": "refresh_token",
            }, timeout=15)
            resp.raise_for_status()
            fresh = resp.json()
            self.tokens["access_token"] = fresh["access_token"]
            self.tokens["expires_at"] = int(time.time()) + int(fresh.get("expires_in", 3600))
            secrets.update_json(self.secret_arn, self.tokens)
        return self.tokens["access_token"]

    def _get(self, path: str, **params) -> dict[str, Any]:
        for attempt in range(5):
            resp = self.http.get(
                path, params=params, headers={"Authorization": f"Bearer {self._access_token()}"}
            )
            if resp.status_code in (429, 500, 503):  # rate limit / transient: exponential backoff
                time.sleep(2**attempt)
                continue
            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()
        return {}

    def profile(self) -> dict[str, Any]:
        return self._get("/profile")

    def list_message_ids(self, page_token: str | None = None, max_results: int = 100):
        """One page of message ids for backfill. Returns (ids, next_page_token)."""
        params: dict[str, Any] = {"maxResults": max_results}
        if page_token:
            params["pageToken"] = page_token
        data = self._get("/messages", **params)
        return [m["id"] for m in data.get("messages", [])], data.get("nextPageToken")

    def history_since(self, start_history_id: str) -> tuple[list[str], str | None]:
        """New message ids since a history id. Returns (ids, latest_history_id)."""
        ids: list[str] = []
        page_token = None
        latest = None
        while True:
            params: dict[str, Any] = {
                "startHistoryId": start_history_id, "historyTypes": "messageAdded",
            }
            if page_token:
                params["pageToken"] = page_token
            data = self._get("/history", **params)
            latest = data.get("historyId", latest)
            for h in data.get("history", []):
                ids.extend(m["message"]["id"] for m in h.get("messagesAdded", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                return ids, latest

    def get_message(self, message_id: str) -> dict[str, Any]:
        """Raw message: {'id','threadId','labelIds','snippet','internalDate','raw'(bytes)}."""
        msg = self._get(f"/messages/{message_id}", format="raw")
        msg["raw"] = base64.urlsafe_b64decode(msg["raw"])
        return msg

    def watch(self, topic: str) -> dict[str, Any]:
        resp = self.http.post(
            "/watch",
            json={"topicName": topic, "labelIds": ["INBOX"]},
            headers={"Authorization": f"Bearer {self._access_token()}"},
        )
        resp.raise_for_status()
        return resp.json()  # {'historyId', 'expiration'}
