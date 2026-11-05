import pytest
from app.etsy_orders import parse_receipt, list_receipts
from app.order_models import OrderProblem
from app.order_shopify import build_order


def receipt():
    def price(n): return {'amount':n,'divisor':100,'currency_code':'GBP'}
    return dict(receipt_id=1234567890,is_paid=True,is_shipped=False,status='paid',
        name='Jane Smith',first_line='1 High Street',second_line='',city='York',state='',zip='YO1 7AB',country_iso='GB',
        grandtotal=price(1299),total_shipping_cost=price(200),total_tax_cost=price(0),total_vat_cost=price(0),
        transactions=[dict(transaction_id=987654321,listing_id=123,product_id=456,title='Board',quantity=1,
            price=price(1099),is_digital=False,sku='BOARD',variations=[{'formatted_name':'Name','formatted_value':'Jane'}])])


def test_receipt_builds_physical_etsy_order_without_tiktok_identity():
    order=parse_receipt(receipt(),'12345',{'123:456':700})
    order.validate()
    payload=build_order(order)['order']
    assert 'EtsyOrderID:1234567890' in payload['tags']
    assert not any('TikTok' in x for x in payload['tags'])
    assert payload['lineItems'][0]['weight']['value']==700
    assert 'Jane' in payload['lineItems'][0]['variantTitle']
    assert payload['shippingAddress']['lastName']=='Smith'
    assert payload['shippingLines'][0]['title']=='Etsy seller shipping'


@pytest.mark.parametrize('change',[{'is_paid':False},{'is_shipped':True},{'status':'completed'},{'status':'shipped'},{'status':'canceled'},{'refunds':[{}]}, {'first_line':''}])
def test_unsafe_receipts_cannot_create_orders(change):
    value=receipt();value.update(change)
    with pytest.raises(OrderProblem): parse_receipt(value,'12345',{'123:456':700}).validate()


def test_unknown_weight_or_unreconciled_discount_requires_review():
    with pytest.raises(OrderProblem,match='weight'): parse_receipt(receipt(),'12345',{}).validate()
    value=receipt();value['grandtotal']['amount']=1199
    with pytest.raises(OrderProblem,match='equal'):parse_receipt(value,'12345',{'123:456':700}).validate()


@pytest.mark.parametrize('change',[
    lambda r:r['transactions'][0].update(is_digital=True),
    lambda r:r['grandtotal'].update(currency_code='USD'),
    lambda r:r['grandtotal'].update(divisor=0),
    lambda r:r['total_vat_cost'].update(amount=100),
])
def test_digital_foreign_invalid_money_and_tax_are_held(change):
    value=receipt();change(value)
    with pytest.raises(OrderProblem):parse_receipt(value,'12345',{'123:456':700}).validate()


@pytest.mark.asyncio
async def test_receipts_paginate_paid_unshipped_only():
    class Client:
        shop_id='12345'
        async def _get(self,path,params):
            assert path.endswith('/receipts')
            assert params['was_paid']=='true' and params['was_shipped']=='false'
            return {'count':2,'results':[{'receipt_id':1 if params['offset']==0 else 2,'is_paid':True,'is_shipped':False}]}
    assert [x['receipt_id'] for x in await list_receipts(Client())]==[1,2]


@pytest.mark.asyncio
async def test_etsy_lookup_cannot_link_same_number_from_tiktok():
    from app.order_shopify import OrderShopify
    class Client:
        async def graphql(self,query,variables):
            assert variables['query']=='tag:"EtsyOrderID:1234567890"'
            return {'orders':{'nodes':[{'id':'gid://shopify/Order/1','tags':['TikTokOrderID:1234567890']}], 'pageInfo':{'hasNextPage':False}}}
    assert await OrderShopify(Client(),'Etsy').find('1234567890') is None


@pytest.mark.asyncio
async def test_queue_locally_excludes_shipped_tracked_and_unpaid_even_if_api_ignores_filters():
    class Client:
        shop_id='12345'
        async def _get(self,path,params):
            return {'count':4,'results':[
                {'receipt_id':1,'is_paid':True,'is_shipped':False,'shipments':[]},
                {'receipt_id':2,'is_paid':True,'is_shipped':True},
                {'receipt_id':3,'is_paid':True,'is_shipped':False,'shipments':[{'tracking_code':'sent'}]},
                {'receipt_id':4,'is_paid':False,'is_shipped':False}]}
    assert [x['receipt_id'] for x in await list_receipts(Client())]==[1]


@pytest.mark.asyncio
async def test_filtered_history_does_not_hide_later_open_receipts():
    class Client:
        shop_id='12345'
        async def _get(self,path,params):
            if params['offset']==0:
                return {'count':3,'results':[
                    {'receipt_id':1,'is_paid':True,'is_shipped':True},
                    {'receipt_id':2,'is_paid':True,'is_shipped':False,'status':'completed'}]}
            assert params['offset']==2
            return {'count':3,'results':[{'receipt_id':3,'is_paid':True,'is_shipped':False}]}
    assert [x['receipt_id'] for x in await list_receipts(Client())]==[3]
