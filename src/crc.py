"""X Account Activity / Filtered Stream Webhook CRC + signature helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac


def crc_response_token(crc_token: str, consumer_secret: str) -> str:
    """Build the CRC response_token for GET webhook challenges.

    response_token = "sha256=" + base64(HMAC-SHA256(crc_token, consumer_secret))
    """
    digest = hmac.new(
        consumer_secret.encode("utf-8"),
        crc_token.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return "sha256=" + base64.b64encode(digest).decode("utf-8")


def verify_webhook_signature(
    body: bytes,
    signature_header: str | None,
    consumer_secret: str,
) -> bool:
    """Verify x-twitter-webhooks-signature header on POST events.

    Header format: sha256=<base64(HMAC-SHA256(raw_body, consumer_secret))>
    """
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = (
        "sha256="
        + base64.b64encode(
            hmac.new(consumer_secret.encode("utf-8"), body, hashlib.sha256).digest()
        ).decode("utf-8")
    )
    return hmac.compare_digest(expected, signature_header)
