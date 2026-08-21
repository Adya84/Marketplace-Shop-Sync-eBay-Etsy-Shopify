import base64
import json

import pytest

from app.ebay_broker import parse_authorization_result


def _encode(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def test_parse_authorization_result_accepts_signed_callback_shape():
    value = _encode({"code": "v^1.1#abc", "state": "state-123", "iat": 1}) + ".signature"
    result = parse_authorization_result(value)
    assert result["code"] == "v^1.1#abc"
    assert result["state"] == "state-123"
    assert result["authorization_result"] == value


def test_parse_authorization_result_accepts_full_url_for_legacy_testing():
    result = parse_authorization_result("https://example.test/callback?code=abc&state=xyz")
    assert result["code"] == "abc"
    assert result["state"] == "xyz"


def test_parse_authorization_result_rejects_invalid_value():
    with pytest.raises(ValueError, match="Invalid eBay authorization result"):
        parse_authorization_result("not-a-result")
