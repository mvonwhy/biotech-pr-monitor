"""Press-release URL extraction + redirect resolution. Heuristics only — no LLM."""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("x_pr_monitor.pr_resolve")

# Domains commonly used for biotech/company press releases
PR_DOMAIN_ALLOWLIST = {
    "businesswire.com",
    "www.businesswire.com",
    "globenewswire.com",
    "www.globenewswire.com",
    "prnewswire.com",
    "www.prnewswire.com",
    "accesswire.com",
    "www.accesswire.com",
    "newsfilecorp.com",
    "www.newsfilecorp.com",
}

# Path patterns that often indicate IR / news-release pages
PR_PATH_PATTERNS = (
    re.compile(r"/news[-_]?releases?", re.I),
    re.compile(r"/press[-_]?releases?", re.I),
    re.compile(r"/newsroom", re.I),
    re.compile(r"/investors?/news", re.I),
    re.compile(r"/investor[-_]?relations", re.I),
    re.compile(r"/bwnews", re.I),
    re.compile(r"/news-release", re.I),
)

TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
TCO_HOSTS = {"t.co", "bit.ly", "tinyurl.com", "ow.ly", "buff.ly", "lnkd.in"}


def extract_urls_from_tweet(tweet_or_alert: dict[str, Any]) -> list[str]:
    """Collect candidate URLs from entities / text. Prefer expanded/unwound."""
    urls: list[str] = []
    seen: set[str] = set()

    def add(u: str | None) -> None:
        if not u:
            return
        u = u.strip()
        if not u or u in seen:
            return
        seen.add(u)
        urls.append(u)

    # v2 entities on tweet object (may live under alert["entities"] or raw)
    entities = tweet_or_alert.get("entities") or {}
    for item in entities.get("urls") or []:
        if not isinstance(item, dict):
            continue
        add(item.get("unwound_url"))
        add(item.get("expanded_url"))
        add(item.get("url"))

    # Sometimes nested under raw_tweet
    raw = tweet_or_alert.get("raw_tweet") or {}
    if isinstance(raw, dict):
        for item in (raw.get("entities") or {}).get("urls") or []:
            if isinstance(item, dict):
                add(item.get("unwound_url"))
                add(item.get("expanded_url"))
                add(item.get("url"))

    # Fallback: scrape http(s) from text
    text = tweet_or_alert.get("text") or ""
    for m in re.finditer(r"https?://[^\s<>\"')\]]+", text):
        add(m.group(0).rstrip(".,;:"))

    return urls


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def looks_like_press_release(url: str) -> bool:
    host = _host(url)
    if host in PR_DOMAIN_ALLOWLIST:
        return True
    # subdomain match e.g. app.businesswire.com
    if any(host.endswith("." + d) or host == d for d in (
        "businesswire.com",
        "globenewswire.com",
        "prnewswire.com",
        "accesswire.com",
        "newsfilecorp.com",
    )):
        return True
    path = urlparse(url).path or ""
    return any(p.search(path) for p in PR_PATH_PATTERNS)


def follow_redirects(
    url: str,
    *,
    timeout: float = 8.0,
    max_redirects: int = 8,
) -> tuple[str, str | None]:
    """Follow redirects; return (final_url, html_or_none for title sniff)."""
    headers = {"User-Agent": "x-pr-monitor/0.1 (+biotech-pr-monitor; heuristic-link-resolver)"}
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            max_redirects=max_redirects,
            headers=headers,
        ) as client:
            # Prefer HEAD then GET if needed for title
            try:
                r = client.head(url)
                final = str(r.url)
            except Exception:
                r = client.get(url)
                final = str(r.url)
                body = r.text[:50_000] if r.headers.get("content-type", "").startswith("text/html") else None
                return final, body

            # If we only HEADed, optionally GET HTML for title when it looks like PR
            if looks_like_press_release(final) or _host(final) in TCO_HOSTS or _host(url) in TCO_HOSTS:
                try:
                    g = client.get(final)
                    final = str(g.url)
                    body = g.text[:50_000] if "text/html" in g.headers.get("content-type", "") else None
                    return final, body
                except Exception:
                    return final, None
            return final, None
    except Exception as e:
        logger.info("redirect follow failed for %s: %s", url, e)
        return url, None


def extract_title(html: str | None) -> str | None:
    if not html:
        return None
    m = TITLE_RE.search(html)
    if not m:
        return None
    title = re.sub(r"\s+", " ", m.group(1)).strip()
    return title[:300] or None


def resolve_press_release(alert: dict[str, Any]) -> dict[str, Any]:
    """Attach press_release_url / title / pr_link_status. Mutates and returns alert."""
    candidates = extract_urls_from_tweet(alert)
    if not candidates:
        alert["press_release_url"] = None
        alert["press_release_title"] = None
        alert["pr_link_status"] = "no_urls_in_tweet"
        return alert

    resolved: list[str] = []
    titles: dict[str, str | None] = {}
    for u in candidates:
        final, html = follow_redirects(u)
        resolved.append(final)
        titles[final] = extract_title(html)

    # Prefer allowlisted / path-matching PR URLs
    for u in resolved:
        if looks_like_press_release(u):
            alert["press_release_url"] = u
            alert["press_release_title"] = titles.get(u)
            alert["pr_link_status"] = "resolved"
            alert["candidate_urls"] = resolved
            return alert

    # Fallback: first non-twitter/x media link
    for u in resolved:
        host = _host(u)
        if host.endswith("twitter.com") or host.endswith("x.com") or host.endswith("t.co"):
            continue
        if host.endswith("pic.twitter.com"):
            continue
        alert["press_release_url"] = None
        alert["press_release_title"] = None
        alert["pr_link_status"] = "urls_but_no_pr_match"
        alert["candidate_urls"] = resolved
        return alert

    alert["press_release_url"] = None
    alert["press_release_title"] = None
    alert["pr_link_status"] = "urls_but_no_pr_match"
    alert["candidate_urls"] = resolved
    return alert
