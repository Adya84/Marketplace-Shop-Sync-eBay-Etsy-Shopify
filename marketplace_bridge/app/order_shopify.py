"""Order-only Shopify operations. Never create products or charge a buyer."""
from .order_models import OrderProblem, money


FIND_ORDER = '''query BridgeFindOrder($query: String!) {
  orders(first: 10, query: $query) {
    nodes { id tags cancelledAt displayFinancialStatus displayFulfillmentStatus totalPriceSet{shopMoney{amount currencyCode}} }
    pageInfo { hasNextPage }
  }
}'''
CREATE_ORDER = '''mutation BridgeCreateOrder($order: OrderCreateOrderInput!, $options: OrderCreateOptionsInput) {
  orderCreate(order: $order, options: $options) {
    order { id name displayFinancialStatus displayFulfillmentStatus totalPriceSet{shopMoney{amount currencyCode}} }
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
    def __init__(self,client): self.client=client

    async def check_scopes(self,*,writes=True):
        data=await self.client.graphql(SCOPES)
        scopes={x['handle'] for x in data['currentAppInstallation']['accessScopes']}
        required={'read_orders'}
        if writes:
            required|={'write_customers','write_orders'}
        available=scopes|({'read_orders'} if 'write_orders' in scopes else set())|(
            {'read_customers'} if 'write_customers' in scopes else set())
        if not required<=available:
            raise OrderProblem('Shopify app permissions are incomplete. The publisher must add order and customer permissions before reconnecting')
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
        variables=build_order(source)
        payload=variables['order']
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
        payload['customer']={'toAssociate':{'id':customer['id']}}
        result=(await self.client.graphql(CREATE_ORDER,variables))['orderCreate']
        order=result.get('order')
        if result['userErrors'] or not order or order['displayFinancialStatus']!='PAID' or order['displayFulfillmentStatus']!='UNFULFILLED':
            raise OrderProblem('Shopify order creation needs review')
        total=order['totalPriceSet']['shopMoney']
        if total['currencyCode']!=source.currency or money(total['amount'])!=source.amount:
            raise OrderProblem('Shopify order total differs from TikTok; review order before shipping')
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
