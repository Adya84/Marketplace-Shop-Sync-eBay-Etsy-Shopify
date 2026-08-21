from urllib.parse import parse_qs, urlparse

import pytest

from app.ebay_oauth import EBAY_SCOPES, authorization_url, parse_callback_result


def test_authorization_url_uses_runame_and_required_scopes():
    url = authorization_url("client-id", "my-runame", "state-123")
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.netloc == "auth.ebay.com"
    assert query["client_id"] == ["client-id"]
    assert query["redirect_uri"] == ["my-runame"]
    assert query["state"] == ["state-123"]
    assert query["scope"] == [" ".join(EBAY_SCOPES)]


def test_parse_callback_result_reads_code_and_state():
    result = parse_callback_result(
        "https://example.test/api/ebay/oauth/callback?code=v%5E1.1%23abc%3D%3D&state=state-123"
    )
    assert result["code"] == "v^1.1#abc=="
    assert result["state"] == "state-123"


def test_parse_callback_result_rejects_denial():
    with pytest.raises(ValueError, match="declined"):
        parse_callback_result(
            "https://example.test/api/ebay/oauth/callback?error=access_denied&error_description=User+declined&state=x"
        )
