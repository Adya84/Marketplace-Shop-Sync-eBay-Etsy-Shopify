"""Destination adapters. No adapter is called by saving a local draft."""
import asyncio
import base64
import copy
import html
import json
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote
import httpx
from .reverse_sync import EbayInventoryWriter
from .shopify import PRODUCT_SET

STAGE='''mutation ListingStage($input:[StagedUploadInput!]!){stagedUploadsCreate(input:$input){stagedTargets{url resourceUrl parameters{name value}} userErrors{field message}}}'''
FILE_CREATE='''mutation ListingFile($files:[FileCreateInput!]!){fileCreate(files:$files){files{id fileStatus} userErrors{field message}}}'''
FILE_STATUS='''query ListingFileStatus($id:ID!){node(id:$id){... on MediaImage{id fileStatus image{url}}}}'''
CURRENT='''query ListingCurrent($id:ID!){product(id:$id){id variants(first:250){nodes{id sku}}}}'''
PUBLISH='''mutation ListingPublish($id:ID!,$input:[PublicationInput!]!){publishablePublish(id:$id,input:$input){userErrors{field message}}}'''
PUBLICATIONS='''query ListingPublications{publications(first:100){nodes{id name}}}'''
SHOP_CURRENCY='''query ListingCurrency{shop{currencyCode}}'''


def errors(payload):
    rows=payload.get('userErrors') or []
    if rows: raise ValueError('; '.join(str(row.get('message') or 'Invalid shop field') for row in rows))


def photo_bytes(directory, name):
    if not re.fullmatch(r'[a-f0-9]{32}\.(jpg|png)',str(name)): raise ValueError('Invalid photo reference.')
    path=Path(directory)/name
    if not path.is_file(): raise ValueError('A listing photo is missing. Upload it again.')
    return path.read_bytes(), 'image/png' if name.endswith('.png') else 'image/jpeg'


def description_html(listing):
    return '<p>'+html.escape(str(listing.get('description') or '')).replace('\n','<br>')+'</p>'


class ShopifyPublisher:
    def __init__(self,client,photos): self.client=client; self.photos=photos

    async def validate(self,listing,settings):
        issues=[]
        if not settings.get('publication_id'): issues.append('Choose a Shopify sales channel in shop settings.')
        if len(listing.get('variants') or [])>250: issues.append('Shopify listing editor currently supports up to 250 variants.')
        currency=(await self.client.graphql(SHOP_CURRENCY))['shop']['currencyCode']
        if currency!=listing['currency']: issues.append('The listing currency must match your Shopify store currency ('+currency+').')
        return issues

    async def photo(self,name,mapping,checkpoint):
        known=mapping.setdefault('media',{}).get(name)
        if known: return await self.ready_image(known)
        data,mime=photo_bytes(self.photos,name)
        payload=await self.client.graphql(STAGE,{'input':[{'filename':name,'mimeType':mime,'resource':'IMAGE','httpMethod':'POST','fileSize':str(len(data))}]})
        result=payload['stagedUploadsCreate']; errors(result)
        target=result['stagedTargets'][0]
        async with httpx.AsyncClient(timeout=90) as client:
            uploaded=await client.post(target['url'],data={p['name']:p['value'] for p in target['parameters']},files={'file':(name,data,mime)})
            uploaded.raise_for_status()
        result=(await self.client.graphql(FILE_CREATE,{'files':[{'originalSource':target['resourceUrl'],'contentType':'IMAGE','alt':name}]}))['fileCreate']
        errors(result)
        asset={'id':result['files'][0]['id']}
        mapping['media'][name]=asset; checkpoint({'media':mapping['media']})
        return await self.ready_image(asset)

    async def ready_image(self,asset):
        for attempt in range(20):
            result=(await self.client.graphql(FILE_STATUS,{'id':asset['id']})).get('node') or {}
            if result.get('fileStatus')=='READY': return asset
            if result.get('fileStatus')=='FAILED': raise ValueError('Shopify could not process a photo. Remove it and upload a new copy.')
            await asyncio.sleep(1)
        raise ValueError('Shopify is still processing a photo. Wait a moment, then retry this listing.')

    async def publish(self,listing,settings,mapping,checkpoint):
        files=[await self.photo(name,mapping,checkpoint) for name in listing['photos']]
        options,variants=self.client._product_options_and_variants(listing['variants'])
        identifier={'id':mapping['id']} if mapping.get('id') else {'handle':'shop-sync-master-'+listing['id']}
        if mapping.get('id'):
            current=(await self.client.graphql(CURRENT,{'id':mapping['id']})).get('product')
            if not current: raise ValueError('The linked Shopify product is missing. Reconcile it before sending again.')
            existing={v['sku']:v['id'] for v in current['variants']['nodes']}
            for variant in variants:
                if variant['sku'] in existing: variant['id']=existing[variant['sku']]
        product={'title':listing['title'],'descriptionHtml':description_html(listing),'status':'ACTIVE',
                 'tags':listing.get('tags') or [],'productOptions':options,'variants':variants,
                 'files':[{'id':item['id']} for item in files]}
        if not mapping.get('id'): product['handle']='shop-sync-master-'+listing['id']
        result=(await self.client.graphql(PRODUCT_SET,{'input':product,'identifier':identifier,'synchronous':True}))['productSet']; errors(result)
        created=result['product']; checkpoint({'id':created['id'],'media':mapping.get('media',{})})
        await self.client._set_inventory(created['variants']['nodes'],listing['variants'])
        result=(await self.client.graphql(PUBLISH,{'id':created['id'],'input':[{'publicationId':settings['publication_id']}]}))['publishablePublish']; errors(result)
        return {'id':created['id'],'media':mapping.get('media',{}),'state':'live','message':'Published to the selected Shopify channel.'}


class EtsyPublisher:
    def __init__(self,client,photos): self.client=client; self.photos=photos

    async def validate(self,listing,settings):
        issues=[f'Choose Etsy {name.replace("_id", "").replace("_", " ")}.' for name in ('taxonomy_id','shipping_profile_id','readiness_state_id','return_policy_id') if not settings.get(name)]
        shop=await self.client.request('GET',f'/v3/application/shops/{self.client.shop_id}')
        currency=shop.get('currency_code')
        if currency and currency!=listing['currency']: issues.append('The listing currency must match your Etsy shop currency ('+currency+').')
        if sum(v.get('quantity',0) for v in listing.get('variants',[]) if isinstance(v.get('quantity'),int))<=0: issues.append('Etsy needs available stock to publish an active listing.')
        return issues

    async def publish(self,listing,settings,mapping,checkpoint):
        variants=listing['variants']; names=[o['name'] for o in variants[0].get('options') or []]
        form={'title':listing['title'],'description':listing['description'],'quantity':sum(v['quantity'] for v in variants),
              'price':variants[0]['price'],'who_made':settings.get('who_made') or 'i_did',
              'when_made':settings.get('when_made') or 'made_to_order','is_supply':False,
              'taxonomy_id':int(settings['taxonomy_id']),'shipping_profile_id':int(settings['shipping_profile_id']),
              'readiness_state_id':int(settings['readiness_state_id']),'return_policy_id':int(settings['return_policy_id']),
              'type':'physical','tags':listing.get('tags') or []}
        base=f'/v3/application/shops/{self.client.shop_id}/listings'
        identifier=mapping.get('id')
        if identifier: await self.client.request('PATCH',base+'/'+str(identifier),form=form)
        else:
            result=await self.client.request('POST',base,params={'legacy':'false'},form=form)
            identifier=str(result.get('listing_id') or '')
            if not identifier: raise RuntimeError('Etsy did not confirm the listing ID.')
            mapping['id']=identifier; checkpoint({'id':identifier})
        # Etsy's two custom properties retain user-entered option names even for
        # categories without equivalent built-in variation properties.
        property_ids=[513,514][:len(names)]
        inventory=[]
        for variant in variants:
            inventory.append({'sku':variant['sku'],'property_values':[
                {'property_id':pid,'property_name':option['name'],'values':[option['value']]}
                for pid,option in zip(property_ids,variant.get('options') or [])],
                'offerings':[{'price':variant['price'],'quantity':variant['quantity'],'is_enabled':True,
                              'readiness_state_id':int(settings['readiness_state_id'])}]})
        await self.client.request('PUT',f'/v3/application/listings/{identifier}/inventory',json_data={
            'products':inventory,'price_on_property':property_ids,'quantity_on_property':property_ids,'sku_on_property':property_ids})
        media=mapping.setdefault('media',{})
        for rank,name in enumerate(listing['photos'],1):
            if name in media:
                await self.client.request('POST',base+f'/{identifier}/images',form={'listing_image_id':media[name],'rank':rank,'overwrite':True})
            else:
                data,mime=photo_bytes(self.photos,name)
                result=await self.client.upload_image(identifier,name,data,mime,rank)
                image_id=result.get('listing_image_id')
                if not image_id: raise RuntimeError('Etsy did not confirm the uploaded photo.')
                media[name]=str(image_id); checkpoint({'id':identifier,'media':media})
        for name in list(media):
            if name not in listing['photos']:
                await self.client.request('DELETE',base+f'/{identifier}/images/{media[name]}')
                del media[name]; checkpoint({'media':media})
        result=await self.client.request('PATCH',base+'/'+str(identifier),form={'state':'active'})
        state=result.get('state') or 'submitted'
        return {'id':str(identifier),'media':media,'state':'live' if state=='active' else state,
                'message':'Published on Etsy.' if state=='active' else 'Submitted to Etsy; check its listing status.'}


class TikTokPublisher:
    def __init__(self,client,photos): self.client=client; self.photos=photos

    async def validate(self,listing,settings):
        issues=[f'Choose TikTok {name.replace("_id", "").replace("_", " ")}.' for name in ('category_id','warehouse_id') if not settings.get(name)]
        for name in ('weight_kg','length_cm','width_cm','height_cm'):
            try:
                if float(settings.get(name) or 0)<=0: raise ValueError()
            except (ValueError,TypeError): issues.append(f'Enter TikTok package {name.replace("_", " ")}.')
        if len((listing.get('variants') or [{}])[0].get('options') or [])>3: issues.append('TikTok allows three variation options.')
        return issues

    @staticmethod
    def payload(listing,settings,images):
        result={'save_mode':'LISTING','title':listing['title'],'description':description_html(listing),
                'category_id':str(settings['category_id']),'main_images':images,'external_product_id':listing['id'],
                'package_weight':{'value':str(settings['weight_kg']),'unit':'KILOGRAM'},
                'package_dimensions':{'length':str(settings['length_cm']),'width':str(settings['width_cm']),'height':str(settings['height_cm']),'unit':'CENTIMETER'},
                'skus':[{'seller_sku':v['sku'],'external_sku_id':v['sku'],
                         'price':{'amount':str(v['price']),'currency':listing['currency']},
                         'inventory':[{'warehouse_id':str(settings['warehouse_id']),'quantity':v['quantity']}],
                         'sales_attributes':[{'name':o['name'],'value_name':o['value']} for o in v.get('options') or []]}
                        for v in listing['variants']]}
        if settings.get('brand_id'): result['brand_id']=str(settings['brand_id'])
        if settings.get('product_attributes'): result['product_attributes']=settings['product_attributes']
        return result

    async def upload_image(self,name):
        data,mime=photo_bytes(self.photos,name); path='/product/202309/images/upload'
        params={'app_key':self.client.app_key,'timestamp':int(time.time()),'shop_cipher':self.client.shop_cipher}
        params['sign']=self.client.generate_sign(path,params)
        async with httpx.AsyncClient(timeout=90) as client:
            response=await client.post(self.client.base_url+path,params=params,
                headers={'x-tts-access-token':self.client.access_token},data={'use_case':'MAIN_IMAGE'},files={'data':(name,data,mime)})
            response.raise_for_status(); payload=response.json()
        if payload.get('code') not in (0,'0',None): raise ValueError('TikTok image upload: '+str(payload.get('message') or 'rejected'))
        uri=(payload.get('data') or {}).get('uri')
        if not uri: raise RuntimeError('TikTok did not confirm the image URI.')
        return {'uri':uri}

    async def publish(self,listing,settings,mapping,checkpoint):
        media=mapping.setdefault('media',{})
        for name in listing['photos']:
            if name not in media:
                media[name]=await self.upload_image(name); checkpoint({'media':media})
        payload=self.payload(listing,settings,[media[name] for name in listing['photos']])
        identifier=mapping.get('id')
        if identifier:
            current=await self.client._request('GET',f'/product/202309/products/{identifier}')
            if current.get('status') in ('DELETED','FROZEN','SUSPENDED'): raise ValueError('Resolve the linked TikTok product status in Seller Center before updating.')
            current_skus={v.get('seller_sku'):v.get('id') for v in current.get('skus') or []}
            for sku in payload['skus']:
                if current_skus.get(sku['seller_sku']): sku['id']=current_skus[sku['seller_sku']]
            for key in ('brand_id','product_attributes','certifications','size_chart'):
                if key not in payload and current.get(key): payload[key]=current[key]
        result=await self.client._request('PUT' if identifier else 'POST',
            f'/product/202309/products/{identifier}' if identifier else '/product/202309/products',body=payload)
        identifier=str(identifier or result.get('product_id') or '')
        if not identifier: raise RuntimeError('TikTok did not confirm the product ID.')
        checkpoint({'id':identifier,'media':media,'skus':result.get('skus') or []})
        return {'id':identifier,'media':media,'skus':result.get('skus') or [],'state':'pending_review',
                'message':'Submitted to TikTok Shop for review; the listing is not confirmed live yet.'}


class EbayPublisher:
    def __init__(self,token,photos,marketplace='EBAY_GB',environment='production'):
        self.token=token; self.photos=photos; self.marketplace=marketplace; self.environment=environment

    async def validate(self,listing,settings):
        issues=[f'Choose eBay {name.replace("_id", "").replace("_", " ")}.' for name in ('category_id','merchant_location_key','payment_policy_id','return_policy_id','fulfillment_policy_id') if not settings.get(name)]
        if self.environment!='production': issues.append('Use a production eBay connection; master listing sandbox publication is not enabled.')
        if self.marketplace=='EBAY_GB' and listing['currency']!='GBP': issues.append('eBay UK listings must use GBP in this editor.')
        if any(len(v.get('sku',''))>50 for v in listing.get('variants') or []): issues.append('eBay SKU must be at most 50 characters.')
        return issues

    async def upload_image(self,name):
        data,mime=photo_bytes(self.photos,name)
        xml='<UploadSiteHostedPicturesRequest xmlns="urn:ebay:apis:eBLBaseComponents"><PictureName>'+name+'</PictureName><PictureSet>Supersize</PictureSet></UploadSiteHostedPicturesRequest>'
        host='api.sandbox.ebay.com' if self.environment=='sandbox' else 'api.ebay.com'
        async with httpx.AsyncClient(timeout=90) as client:
            response=await client.post(f'https://{host}/ws/api.dll',headers={
                'X-EBAY-API-CALL-NAME':'UploadSiteHostedPictures','X-EBAY-API-SITEID':'3',
                'X-EBAY-API-COMPATIBILITY-LEVEL':'1423','X-EBAY-API-IAF-TOKEN':self.token},
                files=[('XML Payload',(None,xml,'text/xml')),('file',(name,data,mime))])
            response.raise_for_status()
        root=ET.fromstring(response.content); ns={'e':'urn:ebay:apis:eBLBaseComponents'}
        url=root.findtext('.//e:FullURL',namespaces=ns)
        if not url:
            message=root.findtext('.//e:LongMessage',namespaces=ns) or 'eBay rejected the photo.'
            raise ValueError(message)
        return url

    async def publish(self,listing,settings,mapping,checkpoint):
        if self.environment!='production': raise ValueError('Master listings require a production eBay connection.')
        if set(mapping.get('skus') or [])-{v['sku'] for v in listing['variants']}:
            raise ValueError('Removing published eBay variations needs a shop review. Keep the existing SKUs here until those variations are ended on eBay.')
        media=mapping.setdefault('media',{})
        for name in listing['photos']:
            if name not in media:
                media[name]=await self.upload_image(name); checkpoint({'media':media})
        outer=self
        class Writer(EbayInventoryWriter):
            async def _request(self,method,path,*,json_data=None,params=None):
                # Deterministic SKUs + recovered offers make a retry an update.
                if method=='POST' and path=='/offer':
                    try: offers=await super()._request('GET','/offer',params={'sku':json_data['sku'],'marketplace_id':outer.marketplace})
                    except RuntimeError as exc:
                        if '404' not in str(exc): raise
                        offers={}
                    rows=offers.get('offers') or []
                    if rows:
                        offer_id=str(rows[0]['offerId'])
                        if offer_id not in (mapping.get('offer_ids') or []):
                            raise ValueError('This eBay SKU already belongs to an offer. Link the existing listing before updating it, or use a different SKU.')
                        await super()._request('PUT','/offer/'+offer_id,json_data=json_data)
                        remote=rows[0].get('listing') or {}
                        if remote.get('listingId'):
                            mapping['id']=str(remote['listingId'])
                            checkpoint({'id':mapping['id']})
                        else: mapping['all_offers_live']=False
                        return {'offerId':offer_id}
                    mapping['all_offers_live']=False
                if method=='PUT' and path.startswith('/inventory_item_group/'):
                    json_data=copy.deepcopy(json_data)
                    json_data.get('variesBy',{}).pop('aspectsImageVariesBy',None)
                result=await super()._request(method,path,json_data=json_data,params=params)
                if path=='/offer' and result.get('offerId'):
                    ids=list(dict.fromkeys([*(mapping.get('offer_ids') or []),str(result['offerId'])]))
                    mapping['offer_ids']=ids; checkpoint({'offer_ids':ids,'media':media})
                return result
        writer=Writer(self.token,self.marketplace)
        # Check every SKU before create_draft can issue its first inventory PUT.
        # Only app-owned offers or the explicitly reconciled listing may change.
        owned=list(mapping.get('offer_ids') or [])
        for variant in listing['variants']:
            try:
                found=await writer._request('GET','/offer',params={'sku':variant['sku'],'marketplace_id':self.marketplace})
            except RuntimeError as exc:
                if '404' not in str(exc): raise
                found={}
            offers=found.get('offers') or []
            for offer in offers:
                offer_id=str(offer['offerId']); remote=str((offer.get('listing') or {}).get('listingId') or '')
                if offer_id not in owned and not (mapping.get('id') and remote==str(mapping['id'])):
                    raise ValueError('This eBay SKU already belongs to another offer. Link its existing listing or choose a different SKU.')
                if offer_id not in owned: owned.append(offer_id)
            if not offers and variant['sku'] not in (mapping.get('skus') or []):
                try: existing=await writer._request('GET','/inventory_item/'+quote(variant['sku'],safe=''))
                except RuntimeError as exc:
                    if '404' not in str(exc): raise
                    existing=None
                if existing is not None: raise ValueError('This SKU already has eBay inventory. Choose a different SKU or reconcile its offer before publishing.')
        mapping['offer_ids']=owned; mapping['skus']=[v['sku'] for v in listing['variants']]
        checkpoint({'offer_ids':owned,'skus':mapping['skus']})
        draft={**listing,'description_html':description_html(listing),'source_id':listing['id'],
               'images':[{'url':media[name]} for name in listing['photos']],
               'kept_options':[o['name'] for o in listing['variants'][0].get('options') or []]}
        config={**settings,'currency':listing['currency'],'marketplace_id':self.marketplace}
        mapping['all_offers_live']=True
        try: result=await writer.create_draft(draft,config)
        except RuntimeError as exc:
            if 'eBay Inventory API 4' in str(exc): raise ValueError(str(exc)) from exc
            raise
        checkpoint({**result,'media':media})
        if mapping.get('all_offers_live') and mapping.get('id'):
            published={'listingId':mapping['id']}
        elif result.get('group_key'):
            published=await writer._request('POST','/offer/publish_by_inventory_item_group',json_data={'inventoryItemGroupKey':result['group_key'],'marketplaceId':self.marketplace})
        else:
            published=await writer._request('POST',f'/offer/{result["offer_ids"][0]}/publish')
        identifier=str(published.get('listingId') or mapping.get('id') or '')
        if not identifier: raise RuntimeError('eBay did not confirm a published listing ID.')
        return {**result,'id':identifier,'media':media,'published':True,'state':'live','message':'Published on eBay.'}
