"""CRC response format unit test with a dummy consumer secret."""

from __future__ import annotations

import base64
import hashlib
import hmac
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.crc import crc_response_token, verify_webhook_signature  # noqa: E402


def test_crc_response_format() -> None:
    secret = "dummy_consumer_secret_for_unit_test"
    crc_token = "test_crc_token_123"
    token = crc_response_token(crc_token, secret)
    assert token.startswith("sha256=")
    expected_digest = hmac.new(
        secret.encode("utf-8"),
        crc_token.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    assert token == "sha256=" + base64.b64encode(expected_digest).decode("utf-8")


def test_webhook_signature_roundtrip() -> None:
    secret = "dummy_consumer_secret_for_unit_test"
    body = b'{"data":{"id":"1","text":"hello"}}'
    sig = (
        "sha256="
        + base64.b64encode(
            hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
        ).decode("utf-8")
    )
    assert verify_webhook_signature(body, sig, secret) is True
    assert verify_webhook_signature(body, "sha256=AAAA", secret) is False
    assert verify_webhook_signature(body, None, secret) is False


def test_original_only_rule_fragment() -> None:
    from src.tickers import ORIGINAL_ONLY, build_stream_rules, save_tickers

    save_tickers(["MRNA", "GILD"], source="test")
    rules = build_stream_rules(accounts=["BioStocks", "BioPharmIQ", "BPharmCatalyst"])
    assert rules
    for r in rules:
        assert ORIGINAL_ONLY in r["value"]
        assert "from:BioStocks" in r["value"]
        assert "$MRNA" in r["value"] or "$GILD" in r["value"]


def test_drops_retweet() -> None:
    from src.normalize import extract_events_from_webhook, is_original_tweet

    assert is_original_tweet({"text": "hello", "id": "1"}) is True
    assert is_original_tweet({"text": "RT @foo: hi", "id": "2"}) is False
    assert (
        is_original_tweet(
            {"text": "q", "id": "3", "referenced_tweets": [{"type": "quoted", "id": "9"}]}
        )
        is False
    )
    events = extract_events_from_webhook(
        {
            "data": {
                "id": "10",
                "text": "RT @x: no",
                "author_id": "1",
                "referenced_tweets": [{"type": "retweeted", "id": "9"}],
            },
            "includes": {"users": [{"id": "1", "username": "BioStocks"}]},
        }
    )
    assert events == []


if __name__ == "__main__":
    test_crc_response_format()
    test_webhook_signature_roundtrip()
    test_original_only_rule_fragment()
    test_drops_retweet()
    print("All CRC / filter tests passed.")
