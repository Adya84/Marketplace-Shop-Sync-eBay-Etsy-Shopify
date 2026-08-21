from app.ebay import is_unavailable_listing_error


def test_removed_listing_message_is_skippable():
    assert is_unavailable_listing_error(
        "This listing was removed because it was reported by the intellectual property rights owner."
    )


def test_normal_ebay_error_is_not_skippable():
    assert not is_unavailable_listing_error("Service temporarily unavailable")
