import httpx
import pytest
from app.etsy_broker import EtsyOAuthBroker


@pytest.mark.asyncio
@pytest.mark.parametrize('method,status,fallback',[('GET',404,True),('GET',403,False),('POST',404,False)])
async def test_legacy_read_fallback_never_retries_writes_or_auth_errors(monkeypatch,method,status,fallback):
    calls=[]
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def post(self,url,json):
            calls.append((url,json))
            return httpx.Response(200 if url.endswith('/get') else status,json={'shop_id':12345},request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx,'AsyncClient',Client)
    broker=EtsyOAuthBroker('https://broker.example')
    if fallback:
        result=await broker.request('token','key',method,'/v3/application/users/123/shops',params={'limit':1})
        assert result=={'shop_id':12345}
        assert calls[-1]==('https://broker.example/api/etsy/api/get',dict(access_token='token',broker_key='key',path='/v3/application/users/123/shops',params={'limit':1}))
    else:
        with pytest.raises(httpx.HTTPStatusError):await broker.request('token','key',method,'/v3/application/users/123/shops')
    assert len(calls)==(2 if fallback else 1)
