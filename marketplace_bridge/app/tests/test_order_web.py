import re
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.order_web import mount_orders
from app.security import SecretBox

@pytest.mark.asyncio
async def test_desktop_check_requires_a_real_rfb_banner():
    import asyncio
    from app.order_web import desktop_ready
    async def rfb(reader,writer):
        writer.write(b'RFB 003.008\n'); await writer.drain()
        writer.close(); await writer.wait_closed()
    async with await asyncio.start_server(rfb,'127.0.0.1',0) as server:
        assert await desktop_ready(server.sockets[0].getsockname()[1])
    assert not await desktop_ready(server.sockets[0].getsockname()[1] if server.sockets else 1)

@pytest.fixture
def workspace(tmp_path,monkeypatch):
    monkeypatch.delenv('BRIDGE_DEVELOPMENT',raising=False)
    core=SimpleNamespace(settings=SimpleNamespace(data_dir=tmp_path),secrets=SecretBox.from_file(tmp_path/'key'),
                         get_credentials=lambda _:dict(shop_domain='test.myshopify.com'))
    app=FastAPI(); store=mount_orders(app,core,lambda _:None)
    return app,store

def test_direct_access_and_forged_forwarding_headers_rejected(workspace):
    app,_=workspace
    with TestClient(app) as client:
        assert client.get('/orders',headers={'x-forwarded-for':'172.30.32.2','x-ingress-path':'/api/hassio_ingress/fake'}).status_code==403

def test_ingress_csrf_and_default_off(workspace,monkeypatch):
    monkeypatch.setenv('BRIDGE_DEVELOPMENT','1')
    app,store=workspace
    with TestClient(app) as client:
        page=client.get('/orders')
        assert page.status_code==200
        assert 'test.myshopify.com' in page.text
        assert client.post('/orders/scan').status_code==403
        csrf=re.search(r'"csrf": "([^"]+)"',page.text)[1]
        data=dict(shop_id='7496165985360775303',shop_name='Example shop',target_shop='test.myshopify.com',weights={'123456789':200},carriers={},enabled=False)
        assert client.post('/orders/settings',json=data,headers={'x-order-csrf':csrf}).status_code==200
        assert not store.settings()['enabled']
        data['shop_id']='9999999999999999999'
        assert client.post('/orders/settings',json=data,headers={'x-order-csrf':csrf}).status_code==400

def test_browser_socket_rejects_missing_token(workspace,monkeypatch):
    from starlette.websockets import WebSocketDisconnect
    monkeypatch.setenv('BRIDGE_DEVELOPMENT','1')
    app,_=workspace
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/orders/desktop/websockify'): pass

def test_manual_import_works_with_timer_off_and_does_not_repeat(tmp_path,monkeypatch):
    import threading
    import app.order_web as web
    from app.tests.test_orders import sample
    monkeypatch.setenv('BRIDGE_DEVELOPMENT','1')
    finished=threading.Event(); created=[]
    class Browser:
        def __init__(self,*args): pass
        def start(self): pass
        def close(self): pass
        def scan_ids(self): return [sample().order_id]
        def detail(self,_): return sample()
    class Shopify:
        def __init__(self,*args): pass
        async def check_scopes(self,**kwargs): pass
        async def find(self,_): return {'id':'gid://shopify/Order/1'} if created else None
        async def create(self,order): created.append(order);return {'id':'gid://shopify/Order/1'}
        async def tracking(self,_): return {'shipments':[]}
    original=web.OrderStore.configure
    def configure(self,**values):
        original(self,**values)
        if values.get('last_message','').startswith('Scan complete:'): finished.set()
    monkeypatch.setattr(web,'TikTokBrowser',Browser);monkeypatch.setattr(web,'OrderShopify',Shopify)
    monkeypatch.setattr(web.OrderStore,'configure',configure)
    core=SimpleNamespace(settings=SimpleNamespace(data_dir=tmp_path),secrets=SecretBox.from_file(tmp_path/'key'),
                         get_credentials=lambda _:dict(shop_domain='test.myshopify.com'))
    app=FastAPI();store=mount_orders(app,core,lambda _:None)
    store.configure(shop_id=sample().shop_id,shop_name='Test',target_shop='test.myshopify.com',preview_verified=True)
    with TestClient(app) as client:
        csrf=re.search(r'"csrf": "([^"]+)"',client.get('/orders').text)[1]
        assert client.post('/orders/import',headers={'x-order-csrf':csrf}).status_code==200
        assert finished.wait(3)
        assert len(created)==1 and not store.settings()['enabled']
        finished.clear()
        assert client.post('/orders/import',headers={'x-order-csrf':csrf}).status_code==200
        assert finished.wait(3)
        assert len(created)==1

def test_import_button_requires_preview(workspace,monkeypatch):
    monkeypatch.setenv('BRIDGE_DEVELOPMENT','1');app,_=workspace
    with TestClient(app) as client:
        csrf=re.search(r'"csrf": "([^"]+)"',client.get('/orders').text)[1]
        assert client.post('/orders/import',headers={'x-order-csrf':csrf}).status_code==400
