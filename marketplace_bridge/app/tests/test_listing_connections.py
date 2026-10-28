import asyncio
from app.listing_connections import ListingEtsyClient, Connections
from app.etsy_broker import BrokerEtsyClient
from app.listing_publishers import EtsyPublisher
from app.tests.test_master_listings import sample
from app.listings import effective_listing
from types import SimpleNamespace
import pytest


def test_refreshed_etsy_credentials_are_saved_for_the_next_publish(monkeypatch):
    persisted=[]
    client=ListingEtsyClient(shop_id='123',access_token='old',broker_key='key',
        refresh_token='refresh',refresh_key='refresh-key',persist=persisted.append)
    async def refresh(self):
        self.access_token='new'; self.broker_key='new-key'; self.refresh_token='new-refresh'
    monkeypatch.setattr(BrokerEtsyClient,'_refresh',refresh)
    asyncio.run(client._refresh())
    assert persisted[0]['access_token']=='new'
    assert persisted[0]['refresh_token']=='new-refresh'


def test_etsy_checks_photo_transport_before_creating_any_listing(tmp_path):
    calls=[]
    class Client:
        shop_id='123'
        async def supports_image_upload(self): return False
        async def request(self,method,path,**kwargs):
            calls.append(method)
            return {'currency_code':'GBP'}
    writer=EtsyPublisher(Client(),tmp_path)
    settings={k:'1' for k in ('taxonomy_id','shipping_profile_id','readiness_state_id','return_policy_id')}
    issues=asyncio.run(writer.validate(effective_listing(sample(),'etsy',{}),settings))
    assert any('photo-upload service' in issue for issue in issues)
    assert not any(method in ('POST','PUT','PATCH') for method in calls)


def test_tiktok_listing_uses_browser_publisher_without_reading_api_credentials(tmp_path):
    def credential(provider): raise AssertionError('TikTok API credentials must not be used')
    browser_writer=object()
    connection=Connections(SimpleNamespace(get_credentials=credential),None,tmp_path,
        tiktok_browser_publisher=browser_writer)
    assert connection.writer('tiktok') is browser_writer


def test_missing_tiktok_browser_never_falls_back_to_the_api(tmp_path):
    def credential(provider): raise AssertionError('No TikTok API fallback is allowed')
    connection=Connections(SimpleNamespace(get_credentials=credential),None,tmp_path)
    with pytest.raises(ValueError,match='browser'): connection.writer('tiktok')
