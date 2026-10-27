import base64
import importlib.util
from pathlib import Path
from fastapi.testclient import TestClient


def broker(monkeypatch):
    path=Path(__file__).resolve().parents[3]/'oauth_broker'/'app.py'
    spec=importlib.util.spec_from_file_location('listing_test_broker',path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    monkeypatch.setattr(module,'ETSY_KEYSTRING','test-key')
    monkeypatch.setattr(module,'ETSY_SHARED_SECRET','test-secret')
    monkeypatch.setattr(module,'_etsy_broker_key',lambda _:'valid')
    return module


def test_broker_forwards_binary_image_and_preserves_auth(monkeypatch):
    module=broker(monkeypatch); calls=[]
    class Response:
        status_code=200; content=b'{}'
        def json(self): return {'listing_image_id':123}
    class Client:
        def __init__(self,**kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def request(self,method,url,**kwargs): calls.append((method,url,kwargs)); return Response()
    monkeypatch.setattr(module.httpx,'AsyncClient',Client)
    data=b'\x89PNG\r\n\x1a\nexample'
    request={'access_token':'seller-token','broker_key':'valid','method':'POST',
             'path':'/v3/application/shops/1/listings/2/images','form':{'rank':1},
             'image':{'content_type':'image/png','data':base64.b64encode(data).decode()}}
    response=TestClient(module.app).post('/api/etsy/api/request',json=request)
    assert response.status_code==200
    kwargs=calls[0][2]
    assert kwargs['files']['image'][1]==data
    assert kwargs['headers']['Authorization']=='Bearer seller-token'
    assert 'test-secret' not in response.text


def test_broker_rejects_invalid_key_and_foreign_urls(monkeypatch):
    module=broker(monkeypatch); client=TestClient(module.app)
    assert client.post('/api/etsy/api/request',json={'access_token':'x','broker_key':'bad','path':'/v3/application/shops/1'}).status_code==401
    assert client.post('/api/etsy/api/request',json={'access_token':'x','broker_key':'valid','path':'https://example.com'}).status_code==400
