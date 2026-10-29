import asyncio
from .order_models import OrderProblem, money
from .order_shopify import verify_shipping_address


class OrderSync:
    def __init__(self,store,shopify):
        self.store=store; self.shopify=shopify; self.lock=asyncio.Lock()

    async def import_order(self,order,*,writes=False):
        order.validate_identity()
        async with self.lock:
            previous=self.store.get(order.shop_id,order.order_id)
            try:
                existing=await self.shopify.find(order.order_id)
            except Exception:
                # A failed lookup is not evidence that an order doesn't exist.
                if previous and previous['state']=='validation_review':
                    self.store.record(order,'validation_review',previous['message'],previous['shopify_id'])
                else:
                    state='uncertain' if previous and previous['state'] in {'claimed','uncertain'} else 'review'
                    self.store.record(order,state,'Shopify lookup failed; no order was created')
                return
            if existing:
                state='review' if existing.get('cancelledAt') or order.status == 'Cancelled' else 'linked'
                message='Existing Shopify order found'
                reconcile_existing=previous and (previous['state'] in {'claimed','uncertain','validation_review'} or
                    (previous['state']=='review' and previous.get('shopify_id')==existing['id']))
                if state=='linked' and reconcile_existing:
                    total=(existing.get('totalPriceSet') or {}).get('shopMoney') or {}
                    try: total_matches=total.get('currencyCode')==order.currency and money(total.get('amount'))==order.amount
                    except OrderProblem: total_matches=False
                    if (existing.get('displayFinancialStatus')!='PAID' or
                            existing.get('displayFulfillmentStatus')!='UNFULFILLED' or
                            not total_matches):
                        state='validation_review'
                        message='Reconciled Shopify order status or total differs from TikTok; verify before shipping'
                if state=='linked':
                    try: verify_shipping_address(existing.get('shippingAddress'),order.address)
                    except OrderProblem as exc:
                        state='validation_review'; message=str(exc)
                if state=='linked' and previous and previous['state']=='tracking_uncertain':
                    state='tracking_uncertain'
                self.store.record(order,state,message,existing['id'])
                return
            if previous and (previous.get('shopify_id') or previous['state'] in {'claimed','uncertain'}):
                self.store.record(order,'uncertain','Previous creation must be reconciled before another import')
                return
            try: order.validate()
            except OrderProblem as exc:
                self.store.record(order,'review',str(exc)); return
            if not writes:
                self.store.record(order,'preview','Ready for import; automatic writes are off'); return
            if not self.store.claim(order): return
            try:
                created=await self.shopify.create(order)
                if not created or not created.get('id'): raise RuntimeError('Missing created order ID')
            except Exception:
                self.store.record(order,'uncertain','Shopify creation response uncertain; reconcile before retrying')
                return
            self.store.record(order,'linked','Imported into Shopify',created['id'])

    async def sync_tracking(self,order,browser,*,writes=False):
        previous=self.store.get(order.shop_id,order.order_id)
        if not previous or not previous.get('shopify_id') or previous['state'] in {'uncertain','claimed','validation_review'}: return
        async with self.lock:
            try:
                data=await self.shopify.tracking(previous['shopify_id'])
                if data.get('cancelledAt') or order.status == 'Cancelled':
                    self.store.record(order,'review','Cancellation requires review; tracking was not changed'); return
                shipments=data.get('shipments',[])
                if not shipments: return
                if len(shipments)!=1 or not shipments[0].get('complete'):
                    self.store.record(order,'review','Partial or multiple shipments require manual tracking'); return
                shipment=shipments[0]
                number=shipment.get('number','').strip(); company=shipment.get('company','').strip()
                carrier=self.store.settings()['carriers'].get(company)
                if not number or not carrier:
                    self.store.record(order,'review','Tracking number or verified TikTok carrier mapping is missing'); return
                expected={'number':number,'carrier':carrier}
                if previous['tracking']==[expected]: return
                if order.tracking:
                    if order.tracking==[expected]:
                        self.store.record(order,'linked','Tracking already matches',tracking=[expected]); return
                    self.store.record(order,'review','TikTok already has different tracking; no overwrite'); return
                if previous['state']=='tracking_uncertain':
                    self.store.record(order,'tracking_uncertain','Inspect TikTok tracking before any further submission'); return
                if not writes:
                    self.store.record(order,'linked','Tracking ready; automatic tracking writes are off'); return
                # Persist before browser mutation: interruption cannot trigger a blind second submit.
                self.store.record(order,'tracking_uncertain','Verifying TikTok tracking submission')
                saved=await asyncio.to_thread(browser.submit_tracking,order.order_id,carrier,number)
                if saved != expected: raise OrderProblem('Tracking could not be verified')
                self.store.record(order,'linked','Tracking verified in TikTok',tracking=[expected])
            except Exception:
                latest=self.store.get(order.shop_id,order.order_id)
                state='tracking_uncertain' if latest and latest['state']=='tracking_uncertain' else 'review'
                self.store.record(order,state,'Tracking needs review; inspect TikTok before retrying')
