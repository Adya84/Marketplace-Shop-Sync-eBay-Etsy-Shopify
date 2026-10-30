from app.order_feedback import next_scan_seconds, summarize_run


def test_countdown_uses_real_completion_and_stops_when_disabled_or_running():
    assert next_scan_seconds(True, False, 100, 132)==268
    assert next_scan_seconds(False, False, 100, 132) is None
    assert next_scan_seconds(True, True, 100, 132) is None
    assert next_scan_seconds(True, False, None, 132)==0
    assert next_scan_seconds(True, False, 100, 500)==0


def test_preview_never_claims_import_and_review_remains_visible():
    result=summarize_run(['preview','linked','review','uncertain'],False,2)
    assert result==dict(checked=4,imported=0,existing=1,ready=1,review=1,failed=1)
    result=summarize_run(['linked','linked','validation_review'],True,1)
    assert result==dict(checked=3,imported=1,existing=1,ready=0,review=1,failed=0)
