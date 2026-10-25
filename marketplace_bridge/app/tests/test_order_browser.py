import pytest
from app.order_browser import parse_detail, parse_tracking
from app.order_models import OrderProblem

@pytest.mark.parametrize('count',[0,1])
@pytest.mark.parametrize('redraw',[False,True])
def test_queue_selects_packing_only_and_uses_filtered_count(count,redraw):
    from app.order_browser import TikTokBrowser, ORIGIN
    selected=[False]; reads=[]
    class Element:
        def __init__(self,text='',action=None): self.text=text; self.action=action
        def is_displayed(self): return True
        def click(self):
            if self.action: self.action()
        def get_attribute(self,key): return 'true' if key=='aria-disabled' else ''
    class Input(Element):
        def is_selected(self): return selected[0]
    class Label(Element):
        stale=False
        def click(self):
            super().click(); self.stale=True
        def find_elements(self,*_):
            from selenium.common.exceptions import StaleElementReferenceException
            if self.stale: raise StaleElementReferenceException('React replaced this label')
            return [Input()]
    class Link(Element):
        def __init__(self,i): self.i=i
        def get_attribute(self,_): return ORIGIN+'/order/detail?order_no='+self.i
        def find_element(self,*_): return Element('Awaiting packing' if selected[0] else 'Awaiting collection')
    class Driver:
        def get(self,_): pass
        def find_elements(self,by,selector):
            if selector=='[role=tab]': return [Element('To ship 24')]
            if selector=='button': return [Element('Filter')]
            if selector=='label':
                return [Label(f'Awaiting packing\n({count})',lambda:selected.__setitem__(0,True)),Label('Awaiting collection (23)')]
            if selector.startswith('a[href'):
                reads.append(1)
                if redraw and len(reads)>1:
                    selected[0]=False
                return [Link('11111111111')]*count if selected[0] else [Link(str(11111111111+i)) for i in range(24)]
            if selector=='[aria-label="Next"]': return [Element()]
            if selector.startswith('//button'):
                return [Element('Clear all',lambda:selected.__setitem__(0,False))] if 'Clear all' in selector else [Element('Apply')]
            return []
    browser=TikTokBrowser('unused',lambda:{}); browser.driver=Driver()
    browser.guard=lambda:None; browser.main_text=lambda:'Awaiting packing' if count else 'No orders'
    browser.wait=lambda fn:fn()
    assert browser.scan_ids()==['11111111111']*count

@pytest.mark.parametrize('permanent',[False,True])
def test_queue_retries_stale_dom_read_without_replacing_browser(monkeypatch,permanent):
    from selenium.common.exceptions import StaleElementReferenceException
    from app.order_browser import TikTokBrowser
    import app.order_browser as module
    browser=TikTokBrowser('unused',lambda:{})
    browser.driver=object(); original=browser.driver; calls=[]
    def read():
        calls.append(1)
        if permanent or len(calls)==1: raise StaleElementReferenceException('old queue DOM')
        return ['11111111111']
    monkeypatch.setattr(browser,'_scan_ids',read,raising=False)
    monkeypatch.setattr(module.time,'sleep',lambda _:None)
    if permanent:
        with pytest.raises(OrderProblem,match='kept changing'): browser.scan_ids()
    else: assert browser.scan_ids()==['11111111111']
    assert len(calls)==(3 if permanent else 2) and browser.driver is original

@pytest.mark.parametrize('code',['ERR_CONNECTION_RESET','ERR_HTTP2_PROTOCOL_ERROR'])
def test_transient_navigation_retries_without_replacing_signed_in_driver(monkeypatch,code):
    from selenium.common.exceptions import WebDriverException
    from app.order_browser import TikTokBrowser, ORIGIN
    import app.order_browser as module
    calls=[]; reports=[]
    class Driver:
        def get(self,url):
            calls.append(url)
            if len(calls)==1: raise WebDriverException('unknown error: net::'+code+' private-data')
    browser=TikTokBrowser('unused',lambda:{},reports.append); browser.driver=Driver()
    original=browser.driver
    monkeypatch.setattr(module.time,'sleep',lambda _:None)
    browser.navigate(ORIGIN+'/homepage')
    assert calls==[ORIGIN+'/homepage']*2 and browser.driver is original
    assert reports and 'private-data' not in reports[0]

def test_navigation_retry_is_bounded_and_redacts_error(monkeypatch):
    from selenium.common.exceptions import WebDriverException
    from app.order_browser import TikTokBrowser, ORIGIN
    import app.order_browser as module
    calls=[]
    class Driver:
        def get(self,url):
            calls.append(url); raise WebDriverException('net::ERR_NAME_NOT_RESOLVED secret-session')
    browser=TikTokBrowser('unused',lambda:{}); browser.driver=Driver()
    monkeypatch.setattr(module.time,'sleep',lambda _:None)
    with pytest.raises(OrderProblem) as exc: browser.navigate(ORIGIN+'/homepage')
    assert len(calls)==3 and 'ERR_NAME_NOT_RESOLVED' in str(exc.value)
    assert 'secret-session' not in str(exc.value)

def test_non_network_driver_failure_is_not_blindly_retried():
    from selenium.common.exceptions import WebDriverException
    from app.order_browser import TikTokBrowser, ORIGIN
    calls=[]
    class Driver:
        def get(self,url): calls.append(url); raise WebDriverException('invalid session id')
    browser=TikTokBrowser('unused',lambda:{}); browser.driver=Driver()
    with pytest.raises(WebDriverException): browser.navigate(ORIGIN+'/homepage')
    assert len(calls)==1

def test_idle_refresh_uses_existing_browser_and_does_not_start_signed_out_browser():
    from app.order_browser import TikTokBrowser, ORIGIN
    browser=TikTokBrowser('unused',lambda:{})
    assert browser.refresh_idle() is False
    calls=[]
    class Driver:
        current_url=ORIGIN+'/order/detail?order_no=12345678901'
        def refresh(self): calls.append('refresh')
    browser.driver=Driver()
    assert browser.refresh_idle() is True and calls==['refresh']
    browser.driver.current_url='https://seller-uk-accounts.tiktok.com/account/login'
    with pytest.raises(OrderProblem): browser.refresh_idle()
    assert calls==['refresh']

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

def test_optional_seller_sku_preserves_title_variant_price_and_source_sku():
    detail=DETAIL.replace('Square 100mm\n£6.99','Square 100mm\nSeller SKU: slate-square\n£6.99')
    order=parse_detail(detail,'7496165985360775303','576970938340776741',{'1729826906594384007':200})
    order.validate()
    assert order.items==[dict(sku='1729826906594384007',title='Photo slate',variant='Square 100mm',
                             unit_price='6.99',quantity=1,weight_grams=200)]

def test_unknown_extra_item_metadata_still_requires_review():
    detail=DETAIL.replace('Square 100mm\n£6.99','Square 100mm\nUnexpected option\n£6.99')
    with pytest.raises(OrderProblem):
        parse_detail(detail,'7496165985360775303','576970938340776741',{})

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
