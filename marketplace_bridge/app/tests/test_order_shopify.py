import pytest
from app.order_shopify import OrderShopify, build_order
from app.order_models import OrderProblem
from app.tests.test_orders import sample


def test_custom_order_is_physical_paid_without_catalogue_or_receipts():
    payload=build_order(sample())
    item=payload['order']['lineItems'][0]
    assert 'variantId' not in item
    assert item['requiresShipping'] and item['weight']=={'value':200,'unit':'GRAMS'}
    assert payload['order']['financialStatus']=='PAID'
    assert 'fulfillmentStatus' not in payload['order']
    assert payload['order']['shippingAddress']['zip']=='G52 3RZ'
    assert payload['options']==dict(sendReceipt=False,sendFulfillmentReceipt=False,inventoryBehaviour='BYPASS')
    assert 'TikTokOrderID:576970938340776741' in payload['order']['tags']


@pytest.mark.asyncio
async def test_write_scopes_supply_their_read_access_without_alternative_order_scopes():
    class API:
        async def graphql(self,*args):
            return {'currentAppInstallation':{'accessScopes':[{'handle':'write_orders'},{'handle':'write_customers'}]}}
    assert await OrderShopify(API()).check_scopes() == {'write_orders','write_customers'}


@pytest.mark.asyncio
async def test_find_requires_exact_tag_and_rejects_duplicate_matches():
    class API:
        async def graphql(self,*args):
            return {'orders':{'nodes':[{'id':'one','tags':['TikTokOrderID:576970938340776741']},
                                       {'id':'two','tags':['TikTokOrderID:576970938340776741']}],
                              'pageInfo':{'hasNextPage':False}}}
    with pytest.raises(OrderProblem,match='Multiple'):
        await OrderShopify(API()).find(sample().order_id)


@pytest.mark.asyncio
async def test_tracking_multiple_numbers_stays_multiple_for_review():
    class API:
        async def graphql(self,*args):
            return {'order':{'cancelledAt':None,'displayFulfillmentStatus':'FULFILLED',
                'fulfillments':[{'status':'SUCCESS','trackingInfo':[{'number':'A','company':'Royal Mail'},
                                                              {'number':'B','company':'Royal Mail'}]}]}}
    assert len((await OrderShopify(API()).tracking('gid://shopify/Order/1'))['shipments'])==2

@pytest.mark.asyncio
async def test_order_import_attaches_existing_customer_and_suppresses_receipts():
    from app.order_shopify import CUSTOMER_FIND, CREATE_ORDER
    calls=[]
    class API:
        async def graphql(self,query,variables=None):
            calls.append((query,variables))
            if query==CUSTOMER_FIND:
                return {'customers':{'nodes':[{'id':'gid://shopify/Customer/1','defaultEmailAddress':{'emailAddress':'buyer@example.invalid'}}], 'pageInfo':{'hasNextPage':False}}}
            if query==CREATE_ORDER:
                assert variables['order']['customer']=={'toAssociate':{'id':'gid://shopify/Customer/1'}}
                assert variables['order']['lineItems'][0]['requiresShipping']
                assert not variables['order']['lineItems'][0]['taxable']
                assert variables['options']=={'sendReceipt':False,'sendFulfillmentReceipt':False,'inventoryBehaviour':'BYPASS'}
                return {'orderCreate':{'order':{'id':'gid://shopify/Order/1','name':'#1','displayFinancialStatus':'PAID','displayFulfillmentStatus':'UNFULFILLED','totalPriceSet':{'shopMoney':{'amount':'6.99','currencyCode':'GBP'}}},'userErrors':[]}}
            raise AssertionError('Unexpected operation')
    order=sample();order.email='buyer@example.invalid'
    assert (await OrderShopify(API()).create(order))['name']=='#1'
    assert [q for q,_ in calls]==[CUSTOMER_FIND,CREATE_ORDER]

@pytest.mark.asyncio
async def test_mismatched_shopify_total_requires_review():
    from app.order_shopify import CUSTOMER_CREATE, CREATE_ORDER
    class API:
        async def graphql(self,query,variables=None):
            if query==CUSTOMER_CREATE:
                return {'customerCreate':{'customer':{'id':'gid://shopify/Customer/1'},'userErrors':[]}}
            if query==CREATE_ORDER:
                return {'orderCreate':{'order':{'id':'gid://shopify/Order/1','name':'#1','displayFinancialStatus':'PAID','displayFulfillmentStatus':'UNFULFILLED','totalPriceSet':{'shopMoney':{'amount':'7.00','currencyCode':'GBP'}}},'userErrors':[]}}
            raise AssertionError('Unexpected operation')
    with pytest.raises(OrderProblem,match='total'):
        await OrderShopify(API()).create(sample())
