import threading
import pytest
from types import SimpleNamespace
from app.order_browser import TikTokBrowser
from app.order_models import OrderProblem


class Driver:
    def __init__(self):
        self.urls={'orders':'https://seller-uk.tiktok.com/order','listing':'https://seller-uk.tiktok.com/product/create?channel=manage&shop_region=GB'}
        self.current_window_handle='listing'
        self.switch_to=SimpleNamespace(window=self.window,new_window=self.new_window)
        self.loads=[]
    @property
    def window_handles(self): return list(self.urls)
    @property
    def current_url(self): return self.urls[self.current_window_handle]
    def window(self,handle): self.current_window_handle=handle
    def new_window(self,kind):
        handle='new-'+str(len(self.urls)); self.urls[handle]='about:blank'; self.current_window_handle=handle
    def get(self,url): self.loads.append((self.current_window_handle,url)); self.urls[self.current_window_handle]=url
    def refresh(self): self.loads.append((self.current_window_handle,'refresh'))


def test_order_scan_does_not_navigate_the_listing_tab():
    browser=TikTokBrowser('profile',lambda:{})
    browser.driver=Driver(); browser.order_window='orders'; browser.listing_window='listing'
    browser.navigate('https://seller-uk.tiktok.com/order?tab=to_ship')
    assert browser.driver.loads==[('orders','https://seller-uk.tiktok.com/order?tab=to_ship')]
    assert '/product/create' in browser.driver.urls['listing']


def test_product_page_in_an_untracked_tab_is_preserved():
    browser=TikTokBrowser('profile',lambda:{})
    browser.driver=Driver(); browser.order_window=None
    browser.navigate('https://seller-uk.tiktok.com/order')
    assert browser.driver.loads[0][0]!='listing'
    assert '/product/create' in browser.driver.urls['listing']


def test_idle_refresh_never_refreshes_an_unsaved_product_form():
    browser=TikTokBrowser('profile',lambda:{})
    browser.driver=Driver(); browser.order_window='orders'; browser.listing_window='listing'
    browser.refresh_idle()
    assert browser.driver.loads==[('orders','refresh')]


def test_broken_driver_with_listing_open_is_not_quit_or_recreated():
    from urllib3.exceptions import ProtocolError
    calls=[]
    class BrokenDriver:
        def execute_script(self,*args): raise ProtocolError('private transport details')
        def quit(self): calls.append('quit')
    browser=TikTokBrowser('profile',lambda:{})
    driver=BrokenDriver(); browser.driver=driver; browser.listing_window='listing'
    with pytest.raises(OrderProblem,match='open listing'): browser.start()
    assert browser.driver is driver and calls==[]
