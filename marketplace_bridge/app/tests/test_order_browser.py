import pytest
from app.order_browser import parse_detail, parse_tracking
from app.order_models import OrderProblem

DETAIL = '''Back
576970938340776741
Cancel
Print receipt
More actions
Awaiting packing
Location
GB
Fulfilment Type
Fulfilled by seller
1 parcel
,
1 item included
Parcel 1:
Awaiting packing
Current order
SKU ID: 1729826906594384007
Photo slate
Square 100mm
£6.99 x 1
Order history
Order paid
What your customer paid
Item(s) subtotal after discounts
£6.99
Shipping fee after discounts
£0.00
Total
£6.99
What you earned
£6.35
Customer details
Shipping address
Test Buyer
(+44)7000000000
test@example.invalid
1 Example Road, Glasgow
Glasgow,Scotland,United Kingdom
G52 3RZ'''

def test_parse_visible_detail_preserves_address_and_items():
    order=parse_detail(DETAIL,'7496165985360775303','576970938340776741',{'1729826906594384007':200})
    order.validate()
    assert order.address['address1']=='1 Example Road, Glasgow'
    assert order.address['city']=='Glasgow'
    assert order.address['lastName']=='Buyer'
    assert order.items[0]['quantity']==1
    assert order.total=='6.99'

def test_wrong_order_and_ambiguous_address_fail_closed():
    with pytest.raises(OrderProblem): parse_detail(DETAIL,'7496165985360775303','576970938340776742',{})
    order=parse_detail(DETAIL.replace('1 Example Road, Glasgow','1 Example Road'),'7496165985360775303','576970938340776741',{})
    assert order.address['city']=='Glasgow'

def test_masked_address_cannot_import():
    order=parse_detail(DETAIL.replace('Test Buyer','T*** B***'),'7496165985360775303','576970938340776741',{'1729826906594384007':200})
    with pytest.raises(OrderProblem): order.validate()

def test_notifications_after_postcode_do_not_hide_a_complete_address():
    order=parse_detail(DETAIL+'\nYou have several products with low stock.',
        '7496165985360775303','576970938340776741',{'1729826906594384007':200})
    order.validate()
    assert order.address['zip']=='G52 3RZ'

def test_multiple_postcodes_in_address_region_require_review():
    with pytest.raises(OrderProblem):
        parse_detail(DETAIL+'\nSW1A 1AA','7496165985360775303','576970938340776741',{})

def test_flat_and_street_are_never_split_into_a_guessed_town():
    order=parse_detail(DETAIL.replace('1 Example Road, Glasgow','Flat 2, 10 High Street'),
                       '7496165985360775303','576970938340776741',{'1729826906594384007':200})
    order.validate()
    assert order.address['address1']=='Flat 2, 10 High Street'
    assert order.address['city']=='Glasgow'

def test_discount_mismatch_does_not_invent_allocation():
    order=parse_detail(DETAIL.replace('£6.99 x 1','£7.99 x 1'),'7496165985360775303','576970938340776741',{'1729826906594384007':200})
    with pytest.raises(OrderProblem): order.validate()

def test_tracking_panel_requires_unique_values():
    assert parse_tracking('Basic info\nTracking ID\nTEST123\nShipping provider\nRoyal Mail\nDelivery option')=={'number':'TEST123','carrier':'Royal Mail'}
    with pytest.raises(OrderProblem): parse_tracking('Tracking ID\nTEST123\nTracking ID\nOTHER\nShipping provider\nRoyal Mail')
