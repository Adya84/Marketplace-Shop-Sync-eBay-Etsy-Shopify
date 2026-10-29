import pytest
from app.order_shopify import OrderShopify, build_order
from app.order_models import OrderProblem
from app.tests.test_orders import sample


def test_single_name_shipping_preserves_name_without_empty_surname_or_source_mutation():
    order=sample(); order.address.update(firstName='Christine',lastName='')
    address=build_order(order)['order']['shippingAddress']
    assert address['firstName']=='' and address['lastName']=='Christine'
    assert order.address['firstName']=='Christine' and order.address['lastName']==''


@pytest.mark.parametrize('field,value',[('address1',''),('city','Elsewhere'),('zip','ZZ1 1ZZ'),
    ('countryCodeV2','US'),('lastName','Someone else')])
def test_incomplete_or_different_returned_shipping_address_requires_review(field,value):
    from app.order_shopify import verify_shipping_address
    address=dict(firstName='Test',lastName='Buyer',address1='1 Example Road',city='Glasgow',
                 zip='G52 3RZ',countryCodeV2='GB')
    address[field]=value
    with pytest.raises(OrderProblem,match='shipping address'):
        verify_shipping_address(address,sample().address)


def test_returned_single_name_address_keeps_exact_printed_recipient():
    from app.order_shopify import verify_shipping_address
    order=sample();order.address.update(firstName='Christine',lastName='')
    verify_shipping_address(dict(firstName='',lastName='Christine',address1='1 Example Road',
        city='Glasgow',zip='G523RZ',countryCodeV2='GB'),order.address)


@pytest.mark.asyncio
async def test_created_order_without_shipping_address_is_not_successful():
    from app.order_shopify import CUSTOMER_CREATE, CREATE_ORDER
    class API:
        async def graphql(self,query,variables=None):
            if query==CUSTOMER_CREATE:
                return {'customerCreate':{'customer':{'id':'gid://shopify/Customer/1'},'userErrors':[]}}
            if query==CREATE_ORDER:
                return {'orderCreate':{'order':{'id':'gid://shopify/Order/1','name':'#1',
                    'shippingAddress':None,'displayFinancialStatus':'PAID','displayFulfillmentStatus':'UNFULFILLED',
                    'totalPriceSet':{'shopMoney':{'amount':'6.99','currencyCode':'GBP'}}},'userErrors':[]}}
    with pytest.raises(OrderProblem,match='shipping address'):
        await OrderShopify(API()).create(sample())


@pytest.mark.asyncio
async def test_existing_order_without_shipping_address_requires_review():
    class API:
        async def graphql(self,*args):
            return {'orders':{'nodes':[{'id':'gid://shopify/Order/1',
                'tags':['TikTokOrderID:576970938340776741'],'shippingAddress':None}],
                'pageInfo':{'hasNextPage':False}}}
    with pytest.raises(OrderProblem,match='shipping address'):
        await OrderShopify(API()).find(sample().order_id)


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
                return {'orderCreate':{'order':{'id':'gid://shopify/Order/1','name':'#1',
                    'shippingAddress':{'firstName':'Test','lastName':'Buyer','address1':'1 Example Road',
                        'city':'Glasgow','zip':'G52 3RZ','countryCodeV2':'GB'},
                    'displayFinancialStatus':'PAID','displayFulfillmentStatus':'UNFULFILLED','totalPriceSet':{'shopMoney':{'amount':'6.99','currencyCode':'GBP'}}},'userErrors':[]}}
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
