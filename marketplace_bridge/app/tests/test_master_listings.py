import asyncio
import copy
import pytest
from app.listing_store import ListingStore
from app.listings import ListingService, effective_listing, validate_listing


def sample():
    return {'title': 'Personalised mug', 'description': 'Your name on a mug', 'currency': 'GBP',
            'photos': ['a'*32+'.jpg'], 'tags': ['mug'],
            'variants': [{'sku': 'MUG-RED', 'price': '12.50', 'quantity': 4,
                          'options': [{'name': 'Colour', 'value': 'Red'}]}],
            'destinations': {'etsy': {'enabled': True}, 'ebay': {'enabled': True}}}


def test_draft_revision_and_overrides_are_persistent(tmp_path):
    store=ListingStore(tmp_path/'listings.db')
    data=sample(); data['destinations']['ebay']['overrides']={'price': '14.00'}
    saved=store.save(data)
    assert saved['revision']==1
    assert effective_listing(saved, 'ebay', {})['variants'][0]['price']=='14.00'
    assert effective_listing(saved, 'etsy', {})['variants'][0]['price']=='12.50'
    assert store.get(saved['id'])['title']==data['title']
    saved['title']='Updated mug'; saved=store.save(saved)
    assert saved['revision']==2
    assert ListingStore(tmp_path/'listings.db').get(saved['id'])['title']=='Updated mug'


def test_save_has_no_remote_writes_and_partial_retry_skips_success(tmp_path):
    calls=[]
    class Writer:
        async def validate(self, listing, settings): return []
        async def publish(self, listing, settings, mapping, checkpoint):
            calls.append(listing['destination'])
            if listing['destination']=='ebay' and calls.count('ebay')==1:
                raise ValueError('Missing required category attribute')
            checkpoint({'id': listing['destination']+'-123'})
            return {'id':listing['destination']+'-123', 'state':'live'}
    store=ListingStore(tmp_path/'listings.db'); service=ListingService(store, lambda _: Writer())
    saved=store.save(sample()); assert calls==[]
    first=asyncio.run(service.publish(saved['id']))
    assert first['etsy']['status']=='success' and first['ebay']['status']=='failed'
    asyncio.run(service.publish(saved['id']))
    assert calls==['etsy','ebay','ebay']
    changed=store.get(saved['id']); changed['description']='New wording'; store.save(changed)
    asyncio.run(service.publish(saved['id']))
    assert calls[-2:]==['etsy','ebay']


def test_unknown_create_outcome_requires_reconciliation(tmp_path):
    class Writer:
        async def validate(self,*args): return []
        async def publish(self,*args): raise TimeoutError('no response')
    store=ListingStore(tmp_path/'listings.db'); service=ListingService(store,lambda _:Writer())
    saved=store.save(sample())
    result=asyncio.run(service.publish(saved['id']))
    assert result['etsy']['status']=='uncertain'
    assert asyncio.run(service.publish(saved['id']))['etsy']['status']=='uncertain'


def test_validation_preserves_marketplace_differences_without_data_loss():
    data=sample(); data['title']='x'*81
    assert any('title' in error.lower() for error in validate_listing(effective_listing(data,'ebay',{})))
    assert not any('title' in error.lower() for error in validate_listing(effective_listing(data,'etsy',{})))
    data['variants'][0]['quantity']=-1
    assert any('quantity' in error.lower() for error in validate_listing(effective_listing(data,'etsy',{})))


def test_publish_uses_saved_snapshot_while_user_edits(tmp_path):
    seen=[]
    store=ListingStore(tmp_path/'listings.db'); saved=store.save(sample())
    class Writer:
        async def validate(self,*args): return []
        async def publish(self, listing, settings, mapping, checkpoint):
            seen.append(listing['title'])
            changed=store.get(saved['id']); changed['title']='Edited while sending'; store.save(changed)
            checkpoint({'id':'remote-1'}); return {'id':'remote-1','state':'live'}
    asyncio.run(ListingService(store,lambda _:Writer()).publish(saved['id']))
    assert seen==['Personalised mug','Personalised mug']
    assert store.results(saved['id'])['etsy']['revision']==1


def test_save_before_retry_does_not_resend_successful_shop(tmp_path):
    calls=[]
    class Writer:
        async def validate(self,*args): return []
        async def publish(self,listing,settings,mapping,checkpoint):
            calls.append(listing['destination'])
            if listing['destination']=='ebay': raise ValueError('Fix category')
            checkpoint({'id':'123'}); return {'id':'123','state':'live'}
    store=ListingStore(tmp_path/'listing.db'); service=ListingService(store,lambda _:Writer())
    saved=store.save(sample()); asyncio.run(service.publish(saved['id']))
    saved=store.save(store.get(saved['id']))
    saved['destinations']['ebay']['settings']={'category_id':'123'}; store.save(saved)
    asyncio.run(service.publish(saved['id']))
    assert calls==['etsy','ebay','ebay']
