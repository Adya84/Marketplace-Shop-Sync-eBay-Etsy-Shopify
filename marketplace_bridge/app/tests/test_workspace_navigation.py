import pytest
from app.workspace_navigation import workspace_navigation
from app.tests.test_listing_web import client_for


def test_navigation_links_stay_inside_home_assistant_ingress():
    nav=workspace_navigation('listings','/api/hassio_ingress/example-token')
    assert 'href="/api/hassio_ingress/example-token/listings" aria-current="page"' in nav
    assert 'href="/api/hassio_ingress/example-token/orders"' in nav
    assert 'href="/api/hassio_ingress/example-token/"' in nav
    assert 'target="_blank"' not in nav
    with pytest.raises(ValueError): workspace_navigation('listings','https://example.com')


def test_listings_is_its_own_page_with_internal_navigation(tmp_path,monkeypatch):
    client,headers,store=client_for(tmp_path,monkeypatch)
    page=client.get('/listings',headers={'x-ingress-path':'/api/hassio_ingress/demo'}).text
    assert 'aria-label="Shop Sync pages"' in page
    assert 'href="/api/hassio_ingress/demo/orders"' in page
    assert 'href="/api/hassio_ingress/demo/listings" aria-current="page"' in page
    assert 'Publish to all' in page and 'One listing, every shop.' in page
    assert 'Import TikTok orders now' not in page
