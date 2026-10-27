"""Bind existing encrypted seller connections to the new listing adapters."""
import base64
import time
import httpx
from .etsy_broker import BrokerEtsyClient
from .listing_publishers import EtsyPublisher, EbayPublisher, TikTokPublisher, ShopifyPublisher, PUBLICATIONS
from .tiktok import TikTokShopClient


class ListingEtsyClient(BrokerEtsyClient):
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
    def __init__(self,core,shopify_factory,photos):
        self.core=core; self.shopify_factory=shopify_factory; self.photos=photos

    def writer(self,destination):
        credential=self.core.get_credentials(destination)
        if destination=='shopify': return ShopifyPublisher(self.shopify_factory(credential),self.photos)
        if destination=='etsy': return EtsyPublisher(ListingEtsyClient(**credential),self.photos)
        if destination=='tiktok': return TikTokPublisher(TikTokShopClient(credential['app_key'],credential['app_secret'],credential['access_token'],credential['shop_cipher']),self.photos)
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
            paths={'categories':'/product/202309/categories','warehouses':'/logistics/202309/warehouses'}
            if kind in ('attributes','rules'):
                if not category.isdigit(): raise ValueError('Choose a TikTok category first.')
                path=f'/product/202309/categories/{category}/{kind}'
            else: path=paths.get(kind)
            if not path: raise ValueError('Unknown shop setting.')
            result=await writer.client._request('GET',path)
            return result
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
