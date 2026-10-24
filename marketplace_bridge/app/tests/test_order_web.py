import re
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.order_web import mount_orders
from app.security import SecretBox

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
