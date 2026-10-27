import asyncio
from pathlib import Path
from app.listing_publishers import TikTokPublisher, EtsyPublisher, ShopifyPublisher, EbayPublisher
from app.reverse_sync import EbayInventoryWriter
import pytest
from app.listings import effective_listing
from app.tests.test_master_listings import sample


def test_tiktok_payload_uses_all_variants_and_shop_settings():
    listing=effective_listing(sample(),'tiktok',{})
    listing['id']='a'*32
    settings={'category_id':'123','warehouse_id':'warehouse-1','weight_kg':'0.35','length_cm':'15','width_cm':'12','height_cm':'10'}
    payload=TikTokPublisher.payload(listing,settings,[{'uri':'image-uri'}])
    assert payload['external_product_id']=='a'*32
    assert payload['main_images']==[{'uri':'image-uri'}]
    assert payload['skus'][0]['price']=={'amount':'12.50','currency':'GBP'}
    assert payload['skus'][0]['inventory']==[{'warehouse_id':'warehouse-1','quantity':4}]
    assert payload['skus'][0]['sales_attributes'][0]['value_name']=='Red'


def test_etsy_records_remote_id_before_inventory_failure(tmp_path):
    calls=[]; checkpoints=[]
    class Client:
        shop_id='1'
        async def request(self,method,path,**kwargs):
            calls.append((method,path,kwargs))
            if path.endswith('/listings'): return {'listing_id':99}
            if path.endswith('/inventory'): raise ValueError('rejected inventory')
            return {}
    listing=effective_listing(sample(),'etsy',{}); listing['id']='a'*32
    writer=EtsyPublisher(Client(),tmp_path)
    settings={'taxonomy_id':'1','shipping_profile_id':'2','readiness_state_id':'3','return_policy_id':'4'}
    try: asyncio.run(writer.publish(listing,settings,{},lambda data:checkpoints.append(data)))
    except ValueError: pass
    assert checkpoints[0]['id']=='99'
    inventory=next(kwargs['json_data'] for method,path,kwargs in calls if path.endswith('/inventory'))
    assert inventory['products'][0]['offerings'][0]['quantity']==4
    assert inventory['products'][0]['offerings'][0]['readiness_state_id']==3


def test_shopify_updates_by_saved_id_and_keeps_remote_variant_ids(tmp_path):
    calls=[]
    class Client:
        def _product_options_and_variants(self,variants):
            return [],[{'sku':v['sku'],'price':v['price']} for v in variants]
        async def graphql(self,query,variables=None):
            calls.append((query,variables))
            if 'ListingCurrent' in query:
                return {'product':{'id':'gid://shopify/Product/1','variants':{'nodes':[{'id':'gid://shopify/ProductVariant/2','sku':'MUG-RED'}]}}}
            if 'productSet' in query:
                return {'productSet':{'product':{'id':'gid://shopify/Product/1','variants':{'nodes':[]}},'userErrors':[]}}
            return {'publishablePublish':{'userErrors':[]}}
        async def _set_inventory(self,*_): pass
    writer=ShopifyPublisher(Client(),tmp_path)
    async def photo(*args): return {'id':'gid://shopify/MediaImage/4'}
    writer.photo=photo
    listing=effective_listing(sample(),'shopify',{}); listing['id']='a'*32
    asyncio.run(writer.publish(listing,{'publication_id':'pub-1'},{'id':'gid://shopify/Product/1'},lambda _:None))
    variables=next(v for q,v in calls if 'productSet' in q)
    assert variables['identifier']=={'id':'gid://shopify/Product/1'}
    assert variables['input']['variants'][0]['id']=='gid://shopify/ProductVariant/2'
    assert variables['input']['status']=='ACTIVE'


def test_ebay_sku_collision_is_rejected_before_any_inventory_write(tmp_path,monkeypatch):
    calls=[]
    async def request(self,method,path,**kwargs):
        calls.append((method,path))
        return {'offers':[{'offerId':'unrelated','listing':{'listingId':'1234'}}]}
    monkeypatch.setattr(EbayInventoryWriter,'_request',request)
    writer=EbayPublisher('token',tmp_path)
    async def photo(*args): return 'https://i.ebayimg.com/photo.jpg'
    writer.upload_image=photo
    listing=effective_listing(sample(),'ebay',{}); listing['id']='a'*32
    with pytest.raises(ValueError,match='already'):
        asyncio.run(writer.publish(listing,{'category_id':'1'}, {},lambda _:None))
    assert not any(method in ('PUT','POST') for method,path in calls)


def test_adding_ebay_variant_publishes_its_new_offer(tmp_path,monkeypatch):
    calls=[]
    async def request(self,method,path,**kwargs):
        calls.append((method,path))
        if method=='GET' and path=='/offer':
            if kwargs['params']['sku']=='MUG-RED': return {'offers':[{'offerId':'old','listing':{'listingId':'123'}}]}
            return {'offers':[]}
        if method=='GET' and path.startswith('/inventory_item/'): raise RuntimeError('eBay Inventory API 404: not found')
        if method=='POST' and path=='/offer': return {'offerId':'new'}
        if 'publish' in path: return {'listingId':'123'}
        return {}
    monkeypatch.setattr(EbayInventoryWriter,'_request',request)
    writer=EbayPublisher('token',tmp_path)
    async def photo(*args): return 'https://i.ebayimg.com/photo.jpg'
    writer.upload_image=photo
    listing=effective_listing(sample(),'ebay',{}); listing['id']='a'*32
    listing['variants'].append({'sku':'MUG-BLUE','price':'13.50','quantity':2,'options':[{'name':'Colour','value':'Blue'}]})
    settings={key:'1' for key in ('category_id','merchant_location_key','payment_policy_id','return_policy_id','fulfillment_policy_id')}
    mapping={'id':'123','offer_ids':['old'],'skus':['MUG-RED']}
    result=asyncio.run(writer.publish(listing,settings,mapping,lambda _:None))
    assert result['state']=='live'
    assert ('POST','/offer/publish_by_inventory_item_group') in calls
