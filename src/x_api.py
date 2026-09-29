"""Thin X API v2 helpers (Bearer auth) for Filtered Stream rules + webhooks.

Rules sync for GET /2/tweets/search/stream (Pay Per Use active path).
Webhook registration/link is Enterprise-only and may 403.
Streaming itself lives in src/stream_client.py (not tweet search polling).
"""

from __future__ import annotations

from typing import Any

import httpx

BASE = "https://api.x.com/2"


class XApiError(RuntimeError):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"X API {status}: {body[:500]}")
        self.status = status
        self.body = body


class XClient:
    def __init__(self, bearer_token: str, timeout: float = 30.0) -> None:
        self._headers = {
            "Authorization": f"Bearer {bearer_token}",
            "Content-Type": "application/json",
        }
        self._timeout = timeout

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = path if path.startswith("http") else f"{BASE}{path}"
        with httpx.Client(timeout=self._timeout, headers=self._headers) as client:
            r = client.request(method, url, **kwargs)
        if r.status_code >= 400:
            raise XApiError(r.status_code, r.text)
        if r.status_code == 204 or not r.content:
            return None
        return r.json()

    def get_rules(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/tweets/search/stream/rules")
        return list((data or {}).get("data") or [])

    def delete_rules(self, ids: list[str]) -> Any:
        if not ids:
            return None
        return self._request(
            "POST",
            "/tweets/search/stream/rules",
            json={"delete": {"ids": ids}},
        )

    def add_rules(self, rules: list[dict[str, str]]) -> Any:
        if not rules:
            return None
        return self._request(
            "POST",
            "/tweets/search/stream/rules",
            json={"add": rules},
        )

    def sync_rules(self, desired: list[dict[str, str]]) -> dict[str, Any]:
        """Replace all existing rules with the desired set."""
        existing = self.get_rules()
        deleted: list[str] = []
        if existing:
            ids = [r["id"] for r in existing if "id" in r]
            self.delete_rules(ids)
            deleted = ids
        added = self.add_rules(desired) if desired else None
        return {"deleted_ids": deleted, "add_response": added, "desired_count": len(desired)}

    def list_webhooks(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/webhooks")
        return list((data or {}).get("data") or [])

    def create_webhook(self, url: str) -> Any:
        """POST /2/webhooks — register public HTTPS URL (no port in URL)."""
        return self._request("POST", "/webhooks", json={"url": url})

    def delete_webhook(self, webhook_id: str) -> Any:
        return self._request("DELETE", f"/webhooks/{webhook_id}")

    def link_filtered_stream_webhook(self, webhook_id: str) -> Any:
        """POST /2/tweets/search/webhooks/:id — attach Filtered Stream delivery to webhook."""
        return self._request("POST", f"/tweets/search/webhooks/{webhook_id}")
