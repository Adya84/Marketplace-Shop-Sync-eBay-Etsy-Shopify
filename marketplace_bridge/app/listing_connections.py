"""Bind existing encrypted seller connections to the new listing adapters."""
import base64
import time
import httpx
from .etsy_broker import BrokerEtsyClient
from .listing_publishers import EtsyPublisher, EbayPublisher, ShopifyPublisher, PUBLICATIONS


class ListingEtsyClient(BrokerEtsyClient):
    def __init__(self,*args,persist=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.persist=persist or (lambda _:None)

    async def _refresh(self):
        await super()._refresh()
        self.persist(self.credential_payload())

    async def supports_image_upload(self):
        async with httpx.AsyncClient(timeout=15) as client:
            response=await client.get(self.broker_url+'/health')
            response.raise_for_status()
            return response.json().get('features',{}).get('etsy_listing_images') is True

    async def upload_image(self,listing_id,name,data,mime,rank):
        if self.refresh_token and (not self.expires_at or time.time()>=self.expires_at-300): await self._refresh()
        payload={'access_token':self.access_token,'broker_key':self.broker_key,'method':'POST',
                 'path':f'/v3/application/shops/{self.shop_id}/listings/{listing_id}/images',
                 'form':{'rank':rank,'overwrite':True},
                 'image':{'filename':name,'content_type':mime,'data':base64.b64encode(data).decode()}}
        async with httpx.AsyncClient(timeout=90) as client:
            response=await client.post(self.broker_url+'/api/etsy/api/request',json=payload)
            response.raise_for_status(); return response.json()


class Connections:
    def __init__(self,core,shopify_factory,photos,tiktok_browser_publisher=None):
        self.core=core; self.shopify_factory=shopify_factory; self.photos=photos
        self.tiktok_browser_publisher=tiktok_browser_publisher

    def writer(self,destination):
        if destination=='tiktok':
            if self.tiktok_browser_publisher is None:
                raise ValueError('TikTok browser publishing still needs setup. Your listing is saved; it has not been sent to TikTok.')
            return self.tiktok_browser_publisher
        credential=self.core.get_credentials(destination)
        if destination=='shopify': return ShopifyPublisher(self.shopify_factory(credential),self.photos)
        if destination=='etsy': return EtsyPublisher(ListingEtsyClient(**credential,persist=lambda updated:self.core.save_credentials('etsy',updated)),self.photos)
        # eBay's credentials are refreshed in prepare(), before snapshot validation.
        return EbayPublisher(credential['access_token'],self.photos,self.core.settings.ebay_marketplace,self.core.settings.ebay_environment)

    async def prepare(self):
        try: credential=self.core.get_credentials('ebay')
        except Exception: return
        updated=await self.core.ensure_ebay_access_token(credential,self.core.settings.ebay_environment)
        if updated!=credential: self.core.save_credentials('ebay',updated)

    async def options(self,destination,kind,category=''):
        writer=self.writer(destination)
        if destination=='shopify' and kind=='channels':
            return (await writer.client.graphql(PUBLICATIONS))['publications']['nodes']
        if destination=='etsy':
            paths={'categories':'/v3/application/seller-taxonomy/nodes',
                   'shipping':f'/v3/application/shops/{writer.client.shop_id}/shipping-profiles',
                   'processing':f'/v3/application/shops/{writer.client.shop_id}/readiness-state-definitions',
                   'returns':f'/v3/application/shops/{writer.client.shop_id}/policies/return'}
            if kind not in paths: raise ValueError('Unknown shop setting.')
            result=await writer.client.request('GET',paths[kind])
            return result.get('results') or []
        if destination=='tiktok':
            if not hasattr(writer,'options'): raise ValueError('Choose TikTok product settings in its browser.')
            return await writer.options(kind,category)
        if destination=='ebay':
            host='https://api.ebay.com' if writer.environment=='production' else 'https://api.sandbox.ebay.com'
            paths={'payment':'/sell/account/v1/payment_policy','returns':'/sell/account/v1/return_policy',
                   'shipping':'/sell/account/v1/fulfillment_policy','locations':'/sell/inventory/v1/location',
                   'categories':'/commerce/taxonomy/v1/category_tree/3/get_category_subtree',
                   'attributes':'/commerce/taxonomy/v1/category_tree/3/get_item_aspects_for_category'}
            if kind not in paths: raise ValueError('Unknown shop setting.')
            params={'marketplace_id':writer.marketplace} if kind in ('payment','returns','shipping') else {}
            if kind in ('categories','attributes'):
                if not category.isdigit(): raise ValueError('Enter an eBay category ID to load its details.')
                params={'category_id':category}
            async with httpx.AsyncClient(timeout=45) as client:
                response=await client.get(host+paths[kind],params=params,headers={'Authorization':'Bearer '+writer.token})
                response.raise_for_status(); return response.json()
        raise ValueError('Unknown shop setting.')
