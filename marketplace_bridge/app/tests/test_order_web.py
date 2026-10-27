import re
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.order_web import mount_orders
from app.security import SecretBox

@pytest.mark.parametrize('signed_out',[False,True])
def test_empty_queue_verifies_preview_but_signout_pauses_without_writes(tmp_path,monkeypatch,signed_out):
    import threading
    import app.order_web as web
    from app.order_models import SignInRequired
    monkeypatch.setenv('BRIDGE_DEVELOPMENT','1')
    finished=threading.Event()
    class Browser:
        def __init__(self,*_): pass
        def start(self): pass
        def close(self): pass
        def scan_ids(self):
            if signed_out: raise SignInRequired('TikTok sign-in expired; sign in again.')
            return []
    class Shopify:
        def __init__(self,*_): pass
        async def check_scopes(self,**_): pass
    original=web.OrderStore.configure
    def configure(self,**values):
        original(self,**values)
        if values.get('last_message','').startswith(('Scan complete:','TikTok sign-in expired')):
            finished.set()
    monkeypatch.setattr(web,'TikTokBrowser',Browser)
    monkeypatch.setattr(web,'OrderShopify',Shopify)
    monkeypatch.setattr(web.OrderStore,'configure',configure)
    core=SimpleNamespace(settings=SimpleNamespace(data_dir=tmp_path),secrets=SecretBox.from_file(tmp_path/'key'),
                         get_credentials=lambda _:dict(shop_domain='test.myshopify.com'))
    app=FastAPI(); store=mount_orders(app,core,lambda _:None)
    store.configure(target_shop='test.myshopify.com',preview_verified=True)
    with TestClient(app) as client:
        csrf=re.search(r'"csrf": "([^"]+)"',client.get('/orders').text)[1]
        store.configure(enabled=True)
        assert client.post('/orders/scan',headers={'x-order-csrf':csrf}).status_code==200
        assert finished.wait(3)
        assert store.settings()['enabled'] is not signed_out
        assert store.settings().get('preview_verified',False) is not signed_out
        assert bool(store.settings().get('last_success_at')) is not signed_out
        assert store.list_orders()==[]

@pytest.mark.asyncio
@pytest.mark.parametrize('manual_finish',[None,30])
async def test_scheduler_refreshes_four_minutes_after_latest_check_leaving_one_minute(manual_finish):
    import asyncio
    from app.order_web import poll_orders
    events=[]; now=[0]; finished=[None]
    async def cycle():
        events.append(('check',now[0])); finished[0]=now[0]
        if len(events)>=3: raise asyncio.CancelledError
    async def refresh(): events.append(('refresh',now[0]))
    async def sleep(seconds):
        now[0]+=seconds
        if manual_finish is not None and now[0]>=manual_finish and finished[0]==0:
            finished[0]=manual_finish
    with pytest.raises(asyncio.CancelledError):
        await poll_orders(lambda:True,cycle,refresh,lambda:finished[0],sleep,lambda:now[0])
    shift=manual_finish or 0
    assert events==[('check',0),('refresh',240+shift),('check',300+shift)]

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
        assert 'reconnect=true&amp;reconnect_delay=3000' in page.text
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

@pytest.mark.parametrize('status,expected',[('Awaiting packing',1),('Awaiting shipment',0),('Awaiting collection',0)])
def test_manual_import_only_packing_with_timer_off_and_does_not_repeat(tmp_path,monkeypatch,status,expected):
    import threading
    import app.order_web as web
    from app.tests.test_orders import sample
    monkeypatch.setenv('BRIDGE_DEVELOPMENT','1')
    finished=threading.Event(); created=[]; inspected=[]
    class Browser:
        def __init__(self,*args): pass
        def start(self): pass
        def close(self): pass
        def scan_ids(self): return [sample().order_id]
        def detail(self,order_id): inspected.append(order_id); return replace(sample(),status=status)
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
    from dataclasses import replace
    historical=replace(sample(),order_id='999999999999999999',status='Awaiting collection')
    store.record(historical,'linked','Already dispatched','gid://shopify/Order/999')
    with TestClient(app) as client:
        csrf=re.search(r'"csrf": "([^"]+)"',client.get('/orders').text)[1]
        assert client.post('/orders/import',headers={'x-order-csrf':csrf}).status_code==200
        assert finished.wait(3)
        assert len(created)==expected and not store.settings()['enabled']
        finished.clear()
        assert client.post('/orders/import',headers={'x-order-csrf':csrf}).status_code==200
        assert finished.wait(3)
        assert len(created)==expected
        assert inspected==[sample().order_id,sample().order_id]

def test_packing_result_view_excludes_previous_completed_orders(workspace,monkeypatch):
    from app.tests.test_orders import sample
    monkeypatch.setenv('BRIDGE_DEVELOPMENT','1'); app,store=workspace
    store.record(sample(),'linked','Old completed order','gid://shopify/Order/999')
    store.configure(active_packing_ids=[],shop_id=sample().shop_id)
    with TestClient(app) as client:
        assert sample().order_id not in client.get('/orders').text

def test_import_button_requires_preview(workspace,monkeypatch):
    monkeypatch.setenv('BRIDGE_DEVELOPMENT','1');app,_=workspace
    with TestClient(app) as client:
        csrf=re.search(r'"csrf": "([^"]+)"',client.get('/orders').text)[1]
        assert client.post('/orders/import',headers={'x-order-csrf':csrf}).status_code==400

def test_scan_failure_reports_stage_and_type_without_exception_content(tmp_path,monkeypatch):
    import threading
    import app.order_web as web
    monkeypatch.setenv('BRIDGE_DEVELOPMENT','1')
    finished=threading.Event()
    class Browser:
        def __init__(self,*args): pass
        def start(self): pass
        def close(self): pass
        def scan_ids(self): raise TimeoutError('private customer or session data')
    class Shopify:
        def __init__(self,*args): pass
        async def check_scopes(self,**kwargs): pass
    original=web.OrderStore.configure
    def configure(self,**values):
        original(self,**values)
        if values.get('last_message','').startswith('Scan stopped'): finished.set()
    monkeypatch.setattr(web,'TikTokBrowser',Browser); monkeypatch.setattr(web,'OrderShopify',Shopify)
    monkeypatch.setattr(web.OrderStore,'configure',configure)
    core=SimpleNamespace(settings=SimpleNamespace(data_dir=tmp_path),secrets=SecretBox.from_file(tmp_path/'key'),
                         get_credentials=lambda _:dict(shop_domain='test.myshopify.com'))
    app=FastAPI(); store=mount_orders(app,core,lambda _:None)
    store.configure(target_shop='test.myshopify.com')
    with TestClient(app) as client:
        csrf=re.search(r'"csrf": "([^"]+)"',client.get('/orders').text)[1]
        assert client.post('/orders/scan',headers={'x-order-csrf':csrf}).status_code==200
        assert finished.wait(3)
        message=client.get('/orders/status').json()['message']
        assert 'TikTok shipping queue' in message and 'TimeoutError' in message
        assert 'private' not in message

@pytest.mark.parametrize('valid_order',[True,False])
def test_review_order_does_not_block_verified_orders(tmp_path,monkeypatch,valid_order):
    import threading
    import app.order_web as web
    from app.tests.test_orders import sample
    from app.order_models import OrderProblem
    monkeypatch.setenv('BRIDGE_DEVELOPMENT','1')
    finished=threading.Event(); created=[]
    broken='999999999999999999'
    class Browser:
        def __init__(self,*args): pass
        def start(self): pass
        def close(self): pass
        def scan_ids(self): return [broken,*([sample().order_id] if valid_order else [])]
        def detail(self,order_id):
            if order_id==broken: raise OrderProblem('Source page layout requires review')
            return sample()
    class Shopify:
        def __init__(self,*args): pass
        async def check_scopes(self,**kwargs): pass
        async def find(self,_): return None
        async def create(self,order): created.append(order.order_id); return {'id':'gid://shopify/Order/1'}
        async def tracking(self,_): return {'shipments':[]}
    original=web.OrderStore.configure
    def configure(self,**values):
        original(self,**values)
        if values.get('last_message','').startswith('Scan complete:'): finished.set()
    monkeypatch.setattr(web,'TikTokBrowser',Browser); monkeypatch.setattr(web,'OrderShopify',Shopify)
    monkeypatch.setattr(web.OrderStore,'configure',configure)
    core=SimpleNamespace(settings=SimpleNamespace(data_dir=tmp_path),secrets=SecretBox.from_file(tmp_path/'key'),
                         get_credentials=lambda _:dict(shop_domain='test.myshopify.com'))
    app=FastAPI(); store=mount_orders(app,core,lambda _:None)
    store.configure(shop_id=sample().shop_id,shop_name='Test',target_shop='test.myshopify.com')
    with TestClient(app) as client:
        csrf=re.search(r'"csrf": "([^"]+)"',client.get('/orders').text)[1]
        headers={'x-order-csrf':csrf}
        assert client.post('/orders/scan',headers=headers).status_code==200
        assert finished.wait(3)
        assert store.settings()['preview_verified'] is valid_order
        assert store.get(sample().shop_id,broken)['state']=='review'
        finished.clear()
        result=client.post('/orders/import',headers=headers)
        assert result.status_code==(200 if valid_order else 400)
        if valid_order: assert finished.wait(3)
        assert created==([sample().order_id] if valid_order else [])
