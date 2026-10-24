from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import pytest

from app.order_models import SourceOrder, OrderProblem
from app.order_store import OrderStore
from app.security import SecretBox


def sample(**updates):
    value = dict(shop_id='7496165985360775303', order_id='576970938340776741',
                 status='Awaiting packing', currency='GBP', total='6.99', shipping='0.00',
                 address=dict(firstName='Test', lastName='Buyer', address1='1 Example Road',
                              city='Glasgow', zip='G52 3RZ', countryCode='GB'),
                 items=[dict(title='Photo slate', variant='Square 100mm', quantity=1,
                             unit_price='6.99', sku='1729826906594384007', weight_grams=200)],
                 seller_fulfilled=True)
    value.update(updates)
    return SourceOrder(**value)


def test_valid_order_preserves_source_money():
    order = sample()
    assert order.validate() is None
    assert order.amount == Decimal('6.99')


@pytest.mark.parametrize('field,value', [('zip','G5* ***'), ('address1','1 *** Road'), ('city','')])
def test_masked_or_incomplete_address_stops_import(field, value):
    order=sample(); order.address[field]=value
    with pytest.raises(OrderProblem): order.validate()


@pytest.mark.parametrize('updates', [dict(total='7.00'), dict(total='NaN'), dict(status='Cancelled'),
    dict(seller_fulfilled=False), dict(items=[]), dict(order_id='bad'), dict(shop_id='')])
def test_unsafe_source_order_requires_review(updates):
    with pytest.raises(OrderProblem): sample(**updates).validate()


def test_unknown_weight_requires_review_not_a_guess():
    order=sample(); order.items[0]['weight_grams']=None
    with pytest.raises(OrderProblem, match='weight'): order.validate()

def test_existing_tracking_blocks_a_second_shipment():
    with pytest.raises(OrderProblem,match='already has tracking'):
        sample(tracking=[{'carrier':'Royal Mail','number':'TEST123'}]).validate()

@pytest.mark.parametrize('state',['claimed','uncertain','tracking_uncertain'])
def test_source_failure_preserves_durable_uncertainty(tmp_path,state):
    db=OrderStore(tmp_path/'orders.db',SecretBox.from_file(tmp_path/'key'))
    order=sample(); db.record(order,state)
    db.source_failure(order)
    assert db.get(order.shop_id,order.order_id)['state']==state
    assert not db.claim(order)


def test_claim_is_durable_unique_and_payload_encrypted(tmp_path):
    box=SecretBox.from_file(tmp_path/'key')
    db=OrderStore(tmp_path/'orders.db',box)
    with ThreadPoolExecutor(5) as pool:
        results=list(pool.map(lambda _: db.claim(sample()), range(10)))
    assert sum(results)==1
    assert OrderStore(tmp_path/'orders.db',box).get(sample().shop_id,sample().order_id)['state']=='claimed'
    assert b'Example Road' not in (tmp_path/'orders.db').read_bytes()


def test_settings_default_off_and_review_rows_survive_restart(tmp_path):
    db=OrderStore(tmp_path/'orders.db',SecretBox.from_file(tmp_path/'key'))
    assert not db.settings()['enabled']
    db.record(sample(),'review','Missing weight')
    assert db.list_orders()[0]['message']=='Missing weight'
