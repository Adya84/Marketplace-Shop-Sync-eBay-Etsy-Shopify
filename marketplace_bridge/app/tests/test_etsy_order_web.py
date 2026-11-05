import re
import threading
from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.order_web import mount_orders
from app.etsy_order_web import mount_etsy_orders
from app.security import SecretBox
from app.tests.test_etsy_orders import receipt


def test_etsy_preview_import_reconcile_and_separate_ledger(tmp_path,monkeypatch):
    import app.etsy_order_web as web
    monkeypatch.setenv('BRIDGE_DEVELOPMENT','1')
    finished=threading.Event();created=[];orders={};saved=[]
    credentials={'etsy':dict(shop_id='12345',oauth_mode='publisher_broker'),'shopify':dict(shop_domain='test.myshopify.com')}
    core=SimpleNamespace(settings=SimpleNamespace(data_dir=tmp_path),secrets=SecretBox.from_file(tmp_path/'key'),
        get_credentials=lambda provider:credentials[provider],save_credentials=lambda provider,value:saved.append(provider))
    class Etsy:
        def __init__(self,**kwargs):self.shop_id=kwargs['shop_id']
        async def _get(self,path,params=None):
            return {'results':[receipt()],'count':1} if params else receipt()
        def credential_payload(self):return credentials['etsy']
    class Shopify:
        def __init__(self,*args):pass
        async def check_scopes(self,**kwargs):pass
        async def find(self,identity):return orders.get(identity)
        async def create(self,order):
            created.append(order.order_id)
            address=dict(order.address,countryCodeV2='GB')
            orders[order.order_id]=dict(id='gid://shopify/Order/123',shippingAddress=address)
            return orders[order.order_id]
    original=web.OrderStore.configure
    def configure(self,**values):
        original(self,**values)
        if values.get('latest_run',{}).get('state') in {'failed','completed'}:finished.set()
    monkeypatch.setattr(web,'BrokerEtsyClient',Etsy);monkeypatch.setattr(web,'OrderShopify',Shopify)
    monkeypatch.setattr(web.OrderStore,'configure',configure)
    app=FastAPI();tiktok=mount_orders(app,core,lambda _:None);etsy=mount_etsy_orders(app,core,lambda _:None)
    with TestClient(app) as client:
        assert client.get('/orders/etsy').status_code==200
        csrf=re.search(r'"csrf": "([^"]+)"',client.get('/orders').text)[1];headers={'x-order-csrf':csrf}
        assert client.post('/orders/etsy/scan').status_code==403
        assert client.post('/orders/etsy/import',headers=headers).status_code==400
        settings=dict(enabled=False,weights={'123:456':700},target_shop='test.myshopify.com')
        assert client.post('/orders/etsy/settings',json=settings,headers=headers).status_code==200
        assert client.post('/orders/etsy/scan',headers=headers).status_code==200
        assert finished.wait(3);finished.clear()
        assert created==[]
        assert etsy.settings()['preview_verified'] is True
        assert client.get('/orders/etsy/status').json()['latest_run']['counts']['ready']==1
        assert client.post('/orders/etsy/import',headers=headers).status_code==200
        assert finished.wait(3);finished.clear()
        assert created==['1234567890']
        assert client.post('/orders/etsy/import',headers=headers).status_code==200
        assert finished.wait(3)
        assert created==['1234567890']
        assert tiktok.list_orders()==[] and tiktok.settings()['enabled'] is False
        assert etsy.list_orders()[0]['shopify_id']=='gid://shopify/Order/123'
        etsy.configure(source_reviews={'1234567890':'Refund requires review'})
        rows=client.get('/orders/etsy/status').json()['rows']
        assert len(rows)==1 and rows[0]['state']=='review'
        assert rows[0]['message']=='Refund requires review'
        finished.clear()
        def save_failure(*args):raise OSError('private filesystem error')
        core.save_credentials=save_failure
        assert client.post('/orders/etsy/scan',headers=headers).status_code==200
        assert finished.wait(3)
        result=client.get('/orders/etsy/status').json()
        assert result['latest_run']['state']=='failed'
        assert 'Reconnect Etsy' in result['latest_run']['message']
        assert 'private' not in str(result) and result['automatic'] is False
    assert saved
