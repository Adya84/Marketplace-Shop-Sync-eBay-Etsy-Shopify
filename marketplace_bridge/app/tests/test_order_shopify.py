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
