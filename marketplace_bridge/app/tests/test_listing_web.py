import json
import re
from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.listing_web import mount_listings


def client_for(tmp_path,monkeypatch):
    monkeypatch.setenv('BRIDGE_DEVELOPMENT','1')
    core=SimpleNamespace(settings=SimpleNamespace(data_dir=tmp_path),get_credentials=lambda _: {})
    app=FastAPI(); store=mount_listings(app,core,lambda _:None)
    client=TestClient(app)
    page=client.get('/listings'); assert page.status_code==200
    token=re.search(r'"csrf": "([^"]+)"',page.text)[1]
    return client,{'x-listing-csrf':token},store


def test_browser_transfer_needs_csrf_and_installed_browser(tmp_path,monkeypatch):
    client,headers,store=client_for(tmp_path,monkeypatch)
    saved=store.save({'title':'Board'})
    path='/listings/api/drafts/'+saved['id']+'/tiktok/prepare'
    assert client.post(path).status_code==403
    assert client.post(path,headers=headers).status_code==503


def test_browser_transfer_uses_saved_shop_override_without_reporting_publication(tmp_path,monkeypatch):
    import time
    from app.tests.test_tiktok_listing_form import product
    client,headers,store=client_for(tmp_path,monkeypatch)
    photos=tmp_path/'listing-photos'; value=product(photos)
    settings=value.pop('settings'); value.pop('destination')
    value['destinations']={'tiktok':{'enabled':True,'overrides':{'title':'Short board title'},'settings':settings}}
    saved=store.save(value); captured=[]
    async def transfer(listing,directory):
        captured.append(listing)
        return {'state':'needs_review','message':'Review in TikTok. Not published.'}
    client.app.state.tiktok_fill_listing_browser=transfer
    with client:
        result=client.post('/listings/api/drafts/'+saved['id']+'/tiktok/prepare',headers=headers)
        assert result.status_code==200 and result.json()['queued']
        for _ in range(100):
            state=client.get('/listings/api/drafts/'+saved['id']+'/results').json()
            if not state['busy']: break
            time.sleep(.01)
        assert not state['busy']
        assert state['results']['tiktok']['status']=='needs_review'
        assert not state['results']['tiktok'].get('mapping',{}).get('id')
    assert captured[0]['title']=='Short board title'
    assert captured[0]['revision']==saved['revision']


def test_existing_remote_tiktok_product_cannot_be_transferred_as_a_new_product(tmp_path,monkeypatch):
    client,headers,store=client_for(tmp_path,monkeypatch)
    saved=store.save({'title':'Board'})
    store.result(saved['id'],'tiktok',status='success',mapping={'id':'12345'})
    async def transfer(*args): raise AssertionError('Existing products must not create a new form')
    client.app.state.tiktok_fill_listing_browser=transfer
    assert client.post('/listings/api/drafts/'+saved['id']+'/tiktok/prepare',headers=headers).status_code==409


def test_drafts_require_csrf_and_do_not_publish(tmp_path,monkeypatch):
    client,headers,store=client_for(tmp_path,monkeypatch)
    assert client.post('/listings/api/drafts',json={'title':'Mug'}).status_code==403
    response=client.post('/listings/api/drafts',headers=headers,json={'title':'Mug','variants':[],'photos':[],'destinations':{}})
    assert response.status_code==200
    identifier=response.json()['id']
    assert store.get(identifier)['title']=='Mug'
    assert store.results(identifier)=={}


def test_photo_checks_content_and_blocks_path_traversal(tmp_path,monkeypatch):
    client,headers,store=client_for(tmp_path,monkeypatch)
    rejected=client.post('/listings/api/photos',headers=headers,files={'file':('fake.jpg',b'<script>bad</script>','image/jpeg')})
    assert rejected.status_code==400
    assert client.get('/listings/photos/not-a-photo.jpg').status_code==404


def test_editor_denies_direct_network_access(tmp_path,monkeypatch):
    monkeypatch.delenv('BRIDGE_DEVELOPMENT',raising=False)
    app=FastAPI(); core=SimpleNamespace(settings=SimpleNamespace(data_dir=tmp_path))
    mount_listings(app,core,lambda _:None)
    assert TestClient(app).get('/listings').status_code==403


def test_uploaded_photo_is_saved_once_and_reused_by_draft(tmp_path,monkeypatch):
    client,headers,store=client_for(tmp_path,monkeypatch)
    image=b'\x89PNG\r\n\x1a\nfixture'
    response=client.post('/listings/api/photos',headers={**headers,'content-type':'image/png'},content=image)
    assert response.status_code==200
    name=response.json()['name']
    saved=client.post('/listings/api/drafts',headers=headers,json={'title':'Mug','photos':[name]}).json()
    assert store.get(saved['id'])['photos']==[name]
    assert client.get('/listings/photos/'+name).content==image


def test_reconcile_normalizes_shopify_numeric_product_id(tmp_path,monkeypatch):
    client,headers,store=client_for(tmp_path,monkeypatch)
    saved=store.save({'title':'Mug'})
    response=client.post('/listings/api/drafts/'+saved['id']+'/reconcile/shopify',headers=headers,json={'id':'123'})
    assert response.status_code==200
    assert store.results(saved['id'])['shopify']['mapping']['id']=='gid://shopify/Product/123'
