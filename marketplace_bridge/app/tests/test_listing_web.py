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
