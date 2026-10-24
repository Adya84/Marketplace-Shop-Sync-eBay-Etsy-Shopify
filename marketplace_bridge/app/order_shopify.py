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

    async def check_scopes(self):
        data=await self.client.graphql(SCOPES)
        scopes={x['handle'] for x in data['currentAppInstallation']['accessScopes']}
        if 'write_orders' not in scopes:
            raise OrderProblem('Reconnect Shopify after the publisher adds write_orders permission')
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
        data=await self.client.graphql(CREATE_ORDER,build_order(source))
        result=data['orderCreate']
        if result['userErrors'] or not result.get('order'):
            # Do not expose API messages that may contain buyer data to ordinary logs.
            raise OrderProblem('Shopify rejected order creation; review source fields and permissions')
        return result['order']

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
