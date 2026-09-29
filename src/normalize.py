"""Normalize X webhook payloads into alert records. No inference / LLM calls."""

from __future__ import annotations

from typing import Any


def tweet_url(username: str | None, tweet_id: str) -> str:
    handle = (username or "i").lstrip("@")
    return f"https://x.com/{handle}/status/{tweet_id}"


def is_original_tweet(tweet: dict[str, Any]) -> bool:
    """Return False if tweet is clearly a reply, retweet, or quote.

    Hardening layer in case stream operators miss something.
    """
    # v2 referenced_tweets
    refs = tweet.get("referenced_tweets") or []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        rtype = (ref.get("type") or "").lower()
        if rtype in ("replied_to", "retweeted", "quoted"):
            return False

    # v2 reply fields
    if tweet.get("in_reply_to_user_id"):
        return False

    text = tweet.get("text") or tweet.get("full_text") or ""
    if text.startswith("RT @"):
        return False

    # AAAPI / v1.1
    if tweet.get("in_reply_to_status_id") or tweet.get("in_reply_to_status_id_str"):
        return False
    if tweet.get("in_reply_to_user_id") or tweet.get("in_reply_to_user_id_str"):
        return False
    if tweet.get("retweeted_status") or tweet.get("retweeted_status_id"):
        return False
    if tweet.get("is_quote_status") is True and tweet.get("quoted_status_id"):
        return False
    if tweet.get("quoted_status") or tweet.get("quoted_status_id_str"):
        return False

    return True


def extract_entities_urls(tweet: dict[str, Any]) -> dict[str, Any]:
    return tweet.get("entities") or {}


def normalize_tweet(tweet: dict[str, Any], includes: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Normalize a Tweet object (v2). Returns None if not an original tweet."""
    if not is_original_tweet(tweet):
        return None

    includes = includes or {}
    users_by_id = {u["id"]: u for u in includes.get("users", []) if "id" in u}
    author_id = tweet.get("author_id")
    user = users_by_id.get(author_id, {}) if author_id else {}
    handle = user.get("username") or tweet.get("username") or "unknown"
    tweet_id = str(tweet.get("id", ""))
    return {
        "type": "tweet",
        "source_handle": handle,
        "tweet_id": tweet_id,
        "text": tweet.get("text", ""),
        "created_at": tweet.get("created_at"),
        "url": tweet_url(handle, tweet_id) if tweet_id else None,
        "referenced_tweets": tweet.get("referenced_tweets"),
        "author_id": author_id,
        "matching_rules": tweet.get("matching_rules"),
        "entities": extract_entities_urls(tweet),
        "raw_tweet": {
            "entities": tweet.get("entities"),
            "referenced_tweets": tweet.get("referenced_tweets"),
        },
    }


def extract_events_from_webhook(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull normalized ORIGINAL-tweet alerts from webhook payloads.

    Matching is already done by X stream rules; this only reshapes JSON and
    drops replies / RTs / quotes that slip through.
    """
    events: list[dict[str, Any]] = []

    if "alert" in payload and isinstance(payload["alert"], dict):
        # Internal — trust caller but still discard if marked non-original
        a = payload["alert"]
        if a.get("referenced_tweets") and not is_original_tweet(a):
            return []
        events.append(a)
        return events
    if "alerts" in payload and isinstance(payload["alerts"], list):
        return [a for a in payload["alerts"] if isinstance(a, dict)]

    includes = payload.get("includes") or {}

    data = payload.get("data")
    if isinstance(data, dict) and data.get("id"):
        tw = dict(data)
        if "matching_rules" in payload:
            tw["matching_rules"] = payload["matching_rules"]
        norm = normalize_tweet(tw, includes)
        if norm:
            events.append(norm)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item.get("id"):
                norm = normalize_tweet(item, includes)
                if norm:
                    events.append(norm)

    for key in ("tweet_create_events", "tweet_create_event"):
        raw = payload.get(key)
        if isinstance(raw, dict):
            raw = [raw]
        if isinstance(raw, list):
            for tw in raw:
                if not isinstance(tw, dict):
                    continue
                if not is_original_tweet(tw):
                    continue
                handle = (tw.get("user") or {}).get("screen_name") or "unknown"
                tid = str(tw.get("id_str") or tw.get("id") or "")
                events.append(
                    {
                        "type": "tweet",
                        "source_handle": handle,
                        "tweet_id": tid,
                        "text": tw.get("text") or tw.get("full_text") or "",
                        "created_at": tw.get("created_at"),
                        "url": tweet_url(handle, tid) if tid else None,
                        "referenced_tweets": None,
                        "entities": tw.get("entities") or {},
                        "raw_tweet": {"entities": tw.get("entities")},
                    }
                )

    return events
