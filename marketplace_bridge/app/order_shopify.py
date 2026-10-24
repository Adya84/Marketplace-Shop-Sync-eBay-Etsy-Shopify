"""Order-only Shopify operations. Never create products or charge a buyer."""
from .order_models import OrderProblem, money


FIND_ORDER = '''query BridgeFindOrder($query: String!) {
  orders(first: 10, query: $query) {
    nodes { id tags cancelledAt }
    pageInfo { hasNextPage }
  }
}'''
CREATE_ORDER = '''mutation BridgeCreateOrder($order: OrderCreateOrderInput!, $options: OrderCreateOptionsInput) {
  orderCreate(order: $order, options: $options) {
    order { id name }
    userErrors { field message }
  }
}'''
ORDER_TRACKING = '''query BridgeOrderTracking($id: ID!) {
  order(id: $id) {
    cancelledAt displayFulfillmentStatus
    fulfillments(first: 50) { status trackingInfo { number company } }
  }
}'''
SCOPES = '{ currentAppInstallation { accessScopes { handle } } }'
CUSTOMER_FIND='''query BridgeCustomer($query:String!){customers(first:10,query:$query){
 nodes{id defaultEmailAddress{emailAddress}} pageInfo{hasNextPage}}}'''
CUSTOMER_CREATE='''mutation BridgeCustomerCreate($input:CustomerInput!){customerCreate(input:$input){
 customer{id} userErrors{field message}}}'''
DRAFT_CREATE='''mutation BridgeDraftCreate($input:DraftOrderInput!){draftOrderCreate(input:$input){
 draftOrder{id totalPriceSet{shopMoney{amount currencyCode}}} userErrors{field message}}}'''
DRAFT_COMPLETE='''mutation BridgeDraftComplete($id:ID!){draftOrderComplete(id:$id){
 draftOrder{order{id name displayFinancialStatus displayFulfillmentStatus}} userErrors{field message}}}'''


def build_order(source):
    source.validate()
    if money(source.tax) != 0:
        raise OrderProblem('Non-zero marketplace tax requires review before import')
    def price(value): return {'shopMoney':{'amount':str(value),'currencyCode':source.currency}}
    return {'order':{
        'currency':source.currency,'financialStatus':'PAID',
        'sourceName':'Shop Sync TikTok','sourceIdentifier':source.order_id,
        'sourceUrl':f'https://seller-uk.tiktok.com/order/detail?order_no={source.order_id}&shop_region=GB',
        'tags':[f'TikTokOrderID:{source.order_id}',f'TikTokShopID:{source.shop_id}','Shop Sync order import'],
        'note':f'Paid on TikTok Shop. Source order {source.order_id}. Do not collect payment again.'+
               ('\nDelivery instructions: '+source.delivery_instructions if source.delivery_instructions else ''),
        'shippingAddress':source.address,'taxesIncluded':False,
        'lineItems':[{'title':item['title'],'variantTitle':item.get('variant',''),
                      'sku':item.get('sku',''),'quantity':item['quantity'],
                      'priceSet':price(item['unit_price']),'taxable':False,'requiresShipping':True,
                      'weight':{'value':item['weight_grams'],'unit':'GRAMS'}} for item in source.items],
        'shippingLines':[{'title':'TikTok seller shipping','priceSet':price(source.shipping)}],
    },'options':{'sendReceipt':False,'sendFulfillmentReceipt':False,'inventoryBehaviour':'BYPASS'}}


class OrderShopify:
    def __init__(self,client,store=None): self.client=client; self.store=store

    async def check_scopes(self,*,writes=True):
        data=await self.client.graphql(SCOPES)
        scopes={x['handle'] for x in data['currentAppInstallation']['accessScopes']}
        required={'read_orders'}
        if writes:
            required|={'read_customers','write_draft_orders','read_draft_orders','write_quick_sale',
                       'read_quick_sale','read_marketplace_orders','write_customers'}
        available=scopes|({'read_orders'} if 'write_orders' in scopes else set())
        if not required<=available:
            raise OrderProblem('Shopify app permissions are incomplete. The publisher must add order, customer and draft-order permissions before reconnecting')
        return scopes

    async def find(self,order_id):
        if not str(order_id).isdigit(): raise OrderProblem('Invalid TikTok order ID')
        tag=f'TikTokOrderID:{order_id}'
        data=await self.client.graphql(FIND_ORDER,{'query':f'tag:"{tag}"'})
        connection=data['orders']
        matches=[x for x in connection['nodes'] if tag in x.get('tags',[])]
        if len(matches)>1 or connection['pageInfo']['hasNextPage']:
            raise OrderProblem('Multiple Shopify matches require review')
        return matches[0] if matches else None

    async def create(self,source):
        payload=build_order(source)['order']
        customer=None
        if source.email:
            # Validation above excludes quotes/whitespace; escape Shopify search syntax too.
            email=source.email.replace('\\','\\\\').replace('"','\\"')
            data=await self.client.graphql(CUSTOMER_FIND,{'query':f'email:"{email}"'})
            connection=data['customers']
            matches=[c for c in connection['nodes'] if
                     (c.get('defaultEmailAddress') or {}).get('emailAddress','').casefold()==source.email.casefold()]
            if len(matches)>1 or connection['pageInfo']['hasNextPage']:
                raise OrderProblem('Customer identity is ambiguous; review before import')
            if matches: customer=matches[0]
        if not customer:
            details={k:source.address.get(k,'') for k in ('firstName','lastName')}
            if source.email: details['email']=source.email
            details['tags']=[f'TikTokShopID:{source.shop_id}']
            result=(await self.client.graphql(CUSTOMER_CREATE,{'input':details}))['customerCreate']
            if result['userErrors'] or not result.get('customer'):
                raise OrderProblem('Shopify customer creation needs review')
            customer=result['customer']
        draft={'presentmentCurrencyCode':source.currency,'purchasingEntity':{'customerId':customer['id']},
               'shippingAddress':source.address,'useCustomerDefaultAddress':False,
               'tags':payload['tags'],'note':payload['note'],
               'acceptAutomaticDiscounts':False,'allowDiscountCodesInCheckout':False,
               'lineItems':[{'title':i['title']+(' — '+i['variantTitle'] if i['variantTitle'] else ''),
                 'quantity':i['quantity'],'sku':i['sku'],'requiresShipping':True,'taxable':False,
                 'weight':i['weight'],'originalUnitPriceWithCurrency':{
                     'amount':i['priceSet']['shopMoney']['amount'],'currencyCode':source.currency}}
                 for i in payload['lineItems']],
               'shippingLine':{'title':'TikTok seller shipping','priceWithCurrency':{
                   'amount':str(source.shipping),'currencyCode':source.currency}}}
        # No invoice/receipt is sent, no inventory-backed variant is claimed,
        # and completing the draft records the payment already taken on TikTok.
        result=(await self.client.graphql(DRAFT_CREATE,{'input':draft}))['draftOrderCreate']
        if result['userErrors'] or not result.get('draftOrder'):
            raise OrderProblem('Shopify draft creation needs review')
        created=result['draftOrder']
        if self.store: self.store.checkpoint_draft(source,created['id'])
        total=created['totalPriceSet']['shopMoney']
        if total['currencyCode']!=source.currency or money(total['amount'])!=source.amount:
            raise OrderProblem('Shopify draft total differs from TikTok; review draft before completion')
        result=(await self.client.graphql(DRAFT_COMPLETE,{'id':created['id']}))['draftOrderComplete']
        order=(result.get('draftOrder') or {}).get('order')
        if result['userErrors'] or not order or order['displayFinancialStatus']!='PAID' or order['displayFulfillmentStatus']!='UNFULFILLED':
            raise OrderProblem('Shopify draft completion needs review')
        return order

    async def tracking(self,shopify_id):
        data=await self.client.graphql(ORDER_TRACKING,{'id':shopify_id})
        order=data['order']
        if not order: raise OrderProblem('Linked Shopify order is unavailable')
        shipments=[]
        for fulfillment in order['fulfillments']:
            if fulfillment['status']!='SUCCESS': continue
            for info in fulfillment['trackingInfo']:
                shipments.append({'company':info.get('company') or '', 'number':info.get('number') or '',
                                  'complete':order['displayFulfillmentStatus']=='FULFILLED'})
        return {'cancelledAt':order['cancelledAt'],'shipments':shipments}
