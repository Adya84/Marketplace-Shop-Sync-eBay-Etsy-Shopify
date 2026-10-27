"""Visible Seller Centre pages only; no TikTok private endpoints or API keys.

Selectors are intentionally strict. A changed page stops a scan or creates a
review row instead of guessing recipient, price, carrier, or order identity.
"""
import re
import threading
import time
from urllib.parse import urlparse, parse_qs
from .order_models import SourceOrder, OrderProblem, SignInRequired

ORIGIN='https://seller-uk.tiktok.com'

def browser_failure(exc):
    """Only static categories reach status text, never raw driver messages."""
    from selenium.common.exceptions import WebDriverException
    if isinstance(exc,WebDriverException):
        message=str(exc).lower()
        for code in ('ERR_CONNECTION_RESET','ERR_CONNECTION_CLOSED','ERR_CONNECTION_TIMED_OUT',
                     'ERR_TIMED_OUT','ERR_NETWORK_CHANGED','ERR_NAME_NOT_RESOLVED',
                     'ERR_INTERNET_DISCONNECTED','ERR_HTTP2_PROTOCOL_ERROR',
                     'ERR_QUIC_PROTOCOL_ERROR','ERR_EMPTY_RESPONSE','ERR_ABORTED','ERR_FAILED'):
            if ('net::'+code).lower() in message: return code
        if 'tab crashed' in message: return 'tab crashed'
        if any(value in message for value in ('invalid session id','disconnected','chrome not reachable')):
            return 'session disconnected'
    return type(exc).__name__

def lines(text):
    return [line.strip() for line in text.splitlines() if line.strip()]

def after(values,label):
    if values.count(label)!=1: raise OrderProblem('Source page layout requires review')
    i=values.index(label)
    if i+1>=len(values): raise OrderProblem('Source page is incomplete')
    return values[i+1]

def parse_tracking(text):
    values=lines(text)
    return {'number':after(values,'Tracking ID'),'carrier':after(values,'Shipping provider')}

def parse_detail(text,shop_id,order_id,weights):
    values=lines(text)
    if order_id not in values[:8]: raise OrderProblem('Source order identity does not match')
    statuses={'Awaiting packing','Awaiting shipment','Awaiting collection','In transit','Delivered','Completed','Cancelled','Unpaid'}
    status=next((v for v in values[:20] if v in statuses),None)
    if not status: raise OrderProblem('Source status could not be verified')
    if values.count('Shipping address')!=1 or values.count('What your customer paid')!=1:
        raise OrderProblem('Source address/payment layout requires review')
    payment=values[values.index('What your customer paid')+1:values.index('Customer details')]
    if 'What you earned' in payment: payment=payment[:payment.index('What you earned')]
    def amount(label):
        raw=after(payment,label)
        if not re.fullmatch(r'£[\d,]+\.\d{2}',raw): raise OrderProblem('Source amount requires review')
        return raw[1:].replace(',','')
    address_lines=values[values.index('Shipping address')+1:]
    instructions=''
    if 'Delivery instructions' in address_lines:
        boundary=address_lines.index('Delivery instructions')
        instructions=' '.join(address_lines[boundary+1:])
        address_lines=address_lines[:boundary]
    # Toast notifications may follow the address in the rendered page text.
    postcodes=[i for i,v in enumerate(address_lines) if re.fullmatch(
        r'[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}|GIR\s?0AA',v,re.I)]
    if len(postcodes)!=1 or postcodes[0]<3:
        raise OrderProblem('Delivery address needs one unambiguous postcode')
    address_lines=address_lines[:postcodes[0]+1]
    name=address_lines[0].split(maxsplit=1)
    body=[v for v in address_lines[1:-2] if not v.startswith('(+') and '@' not in v]
    if not body or not address_lines[-2].endswith(',United Kingdom'):
        raise OrderProblem('Delivery street/city/country requires review')
    # A comma may separate a flat/street, not a post town. Preserve every
    # supplied street component and use TikTok's explicit district field.
    street=body[-1]; city=address_lines[-2].split(',')[0]
    address={'firstName':name[0], 'lastName':name[1] if len(name)>1 else '',
             'address1':', '.join([*body[:-1],street.strip()]),'city':city.strip(),
             'zip':address_lines[-1].upper(),'countryCode':'GB'}
    emails=[v for v in address_lines if '@' in v]
    if len(emails)>1: raise OrderProblem('Customer email is ambiguous')
    phones=[v for v in address_lines if v.startswith('(+')]
    if len(phones)==1:
        phone=re.sub(r'[()\s-]','',phones[0])
        if re.fullmatch(r'\+\d{8,15}',phone): address['phone']=phone
    items=[]
    block=[v for v in values[values.index('Current order')+1:values.index('Order history')]
           if v not in {'Seller-signed creator','Affiliate creator'}]
    pos=0
    while pos<len(block):
        match=re.fullmatch(r'SKU ID: (\d+)',block[pos])
        if not match: raise OrderProblem('Item layout requires review')
        end=next((i for i in range(pos+1,len(block)) if block[i].startswith('SKU ID: ')),len(block))
        item=block[pos+1:end]
        # Some listings show the merchant's SKU immediately before price.
        # The TikTok numeric SKU above remains the order's source identity.
        if len(item) in (3,4) and re.fullmatch(r'Seller SKU: .+',item[-2]):
            item=[*item[:-2],item[-1]]
        if len(item) not in (2,3): raise OrderProblem('Item title/options require review')
        price=re.fullmatch(r'£([\d,]+\.\d{2})\s*[x×]\s*(\d+)',item[-1])
        if not price: raise OrderProblem('Item price/quantity requires review')
        sku=match[1]
        items.append({'sku':sku,'title':item[0],'variant':item[1] if len(item)==3 else '',
                      'unit_price':price[1].replace(',',''),'quantity':int(price[2]),'weight_grams':weights.get(sku)})
        pos=end
    parcel=[re.match(r'(\d+) parcels?(?:, \d+ items? included)?$',v) for v in values]
    parcel=[m[1] for m in parcel if m]
    if parcel!=['1']: raise OrderProblem('Multiple or unknown parcels require review')
    return SourceOrder(str(shop_id),str(order_id),status,'GBP',amount('Total'),amount('Shipping fee after discounts'),
                       address,items,'Fulfilled by seller' in values,delivery_instructions=instructions,
                       email=emails[0] if emails else '')

class TikTokBrowser:
    def __init__(self,profile,settings,report=None):
        self.profile=str(profile); self.settings=settings; self.driver=None
        self.report=report or (lambda _:None)
        self.lock=threading.RLock()

    def navigate(self,url,refresh=False):
        """Retry only read-only page loads; never restart or replace the session."""
        from selenium.common.exceptions import WebDriverException, TimeoutException
        if urlparse(url).hostname!='seller-uk.tiktok.com':
            raise OrderProblem('Unsupported TikTok page destination')
        for attempt in range(3):
            try:
                if refresh: self.driver.refresh()
                else: self.driver.get(url)
                return
            except WebDriverException as exc:
                code=re.search(r'net::(ERR_[A-Z0-9_]+)',str(exc))
                retryable=code and code[1] in {
                    'ERR_CONNECTION_RESET','ERR_CONNECTION_CLOSED','ERR_CONNECTION_TIMED_OUT',
                    'ERR_TIMED_OUT','ERR_NETWORK_CHANGED','ERR_NAME_NOT_RESOLVED',
                    'ERR_INTERNET_DISCONNECTED','ERR_HTTP2_PROTOCOL_ERROR',
                    'ERR_QUIC_PROTOCOL_ERROR','ERR_EMPTY_RESPONSE','ERR_ABORTED','ERR_FAILED',
                    'ERR_HTTP_RESPONSE_CODE_FAILURE'}
                if not retryable and not isinstance(exc,TimeoutException): raise
                reason=code[1] if retryable else 'page-load timeout'
                if attempt==2:
                    raise OrderProblem(f'TikTok page load failed after 3 attempts ({reason}); next check will retry.') from None
                self.report(f'TikTok page load failed ({reason}); retrying {attempt+2} of 3…')
                time.sleep((2,5)[attempt])

    def refresh_idle(self):
        with self.lock:
            if not self.driver: return False
            self.check_login()
            url=self.driver.current_url
            if urlparse(url).hostname!='seller-uk.tiktok.com':
                raise OrderProblem('Sign in to TikTok in the browser panel')
            self.navigate(url,refresh=True)
            self.check_login()
            return True

    def start(self):
        with self.lock:
            if self.driver:
                from selenium.common.exceptions import WebDriverException
                from urllib3.exceptions import MaxRetryError, NewConnectionError, ReadTimeoutError
                connection_errors=(WebDriverException,MaxRetryError,NewConnectionError,ReadTimeoutError)
                try:
                    self.driver.execute_script('return 1')
                    return
                except connection_errors:
                    self.report('TikTok browser connection stopped; reopening the saved browser profile…')
                    old=self.driver
                    self.driver=None
                    try: old.quit()
                    except connection_errors: pass
            from selenium import webdriver
            from selenium.webdriver.chrome.service import Service
            options=webdriver.ChromeOptions()
            options.binary_location='/usr/bin/chromium-browser'
            options.add_argument('--user-data-dir='+self.profile)
            options.add_argument('--window-size=1280,900')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--no-first-run')
            options.add_argument('--restore-last-session')
            self.driver=webdriver.Chrome(service=Service('/usr/local/bin/shop-sync-chromedriver'),options=options)
            self.driver.set_page_load_timeout(60)
            self.navigate(ORIGIN+'/homepage')

    def close(self):
        with self.lock:
            if self.driver:
                self.driver.quit(); self.driver=None

    def wait(self,fn):
        from selenium.webdriver.support.ui import WebDriverWait
        def ready(_):
            self.check_login()
            return fn()
        return WebDriverWait(self.driver,30).until(ready)

    def check_login(self):
        url=urlparse(self.driver.current_url)
        if url.hostname=='seller-uk-accounts.tiktok.com' or (
            url.hostname=='seller-uk.tiktok.com' and url.path.startswith('/account/login')):
            raise SignInRequired('TikTok sign-in expired; imports paused. Sign in in the browser panel, run a preview, then enable automatic imports.')

    def find_text(self,text,tag='*'):
        # Static selectors or validated labels; never interpolate order/customer data.
        from selenium.webdriver.common.by import By
        if "'" in text: raise OrderProblem('Unsupported selector label')
        return [e for e in self.driver.find_elements(By.XPATH,f"//{tag}[normalize-space(.)='{text}']") if e.is_displayed()]

    def click_text(self,text,tag='button'):
        matches=self.find_text(text,tag)
        if len(matches)!=1: raise OrderProblem('TikTok action is missing or ambiguous')
        matches[0].click()

    def guard(self):
        from selenium.webdriver.common.by import By
        self.check_login()
        config=self.settings()
        if urlparse(self.driver.current_url).hostname!='seller-uk.tiktok.com':
            raise OrderProblem('Sign in to TikTok in the browser panel')
        name=config['shop_name']
        if not name or not re.fullmatch(r'\d{5,30}',config['shop_id']):
            raise OrderProblem('Set the verified TikTok shop name and ID first')
        banner=self.driver.find_elements(By.CSS_SELECTOR,'header, [role=banner]')
        # Shop switcher has both image alt and visible label in the observed UI.
        found=[]
        for region in banner:
            found.extend(e for e in region.find_elements(By.CSS_SELECTOR,'button, [role=button]')
                         if e.text.strip()==name and any(i.get_attribute('alt')==name for i in e.find_elements(By.CSS_SELECTOR,'img')))
        if len(found)!=1: raise OrderProblem('TikTok login/shop identity requires review')

    def main_text(self):
        from selenium.webdriver.common.by import By
        self.guard()
        return self.driver.find_element(By.CSS_SELECTOR,'main, [role=main]').text

    def detail(self,order_id):
        with self.lock:
            if not re.fullmatch(r'\d{10,30}',order_id): raise OrderProblem('Invalid source order ID')
            self.navigate(ORIGIN+'/order/detail?order_no='+order_id+'&shop_region=GB')
            self.wait(lambda:order_id in self.main_text() and bool(re.search(
                r'(?:^|\n)(?:GIR\s?0AA|[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2})(?:\n|$)',self.main_text(),re.I)))
            config=self.settings()
            order=parse_detail(self.main_text(),config['shop_id'],order_id,config['weights'])
            logistics=self.find_text('Logistics information','button')
            if len(logistics)>1: raise OrderProblem('Multiple parcels require manual review')
            if logistics:
                logistics[0].click()
                from selenium.webdriver.common.by import By
                dialog=self.wait(lambda:next((e for e in self.driver.find_elements(By.CSS_SELECTOR,'[role=dialog]') if e.is_displayed()),None))
                order.tracking=[parse_tracking(dialog.text)]
                self.click_text('Got it')
            return order

    def scan_ids(self):
        from selenium.common.exceptions import StaleElementReferenceException
        with self.lock:
            for attempt in range(3):
                try: return self._scan_ids()
                except StaleElementReferenceException:
                    if attempt==2:
                        raise OrderProblem('TikTok queue kept changing while loading; next check will retry.') from None
                    self.report(f'TikTok updated its queue; reading the fresh page (attempt {attempt+2} of 3)…')
                    time.sleep(1)

    def packing_option(self):
        from selenium.webdriver.common.by import By
        packing=[]
        for label in self.driver.find_elements(By.CSS_SELECTOR,'label'):
            if not label.is_displayed(): continue
            match=re.fullmatch(r'Awaiting packing\s*\(\s*(\d+)\s*\)',label.text.strip())
            if match and label.find_elements(By.CSS_SELECTOR,'input[type=radio]'):
                packing.append((label,int(match[1])))
        if len(packing)!=1: raise OrderProblem('Awaiting packing filter could not be verified')
        return packing[0]

    def _scan_ids(self):
        from selenium.webdriver.common.by import By
        with self.lock:
            # Use the observed Seller Centre queue URL. Home-page card labels
            # can arrive as untranslated locale keys even after successful login.
            self.navigate(ORIGIN+'/order?order_status[]=1&selected_sort=1&shop_region=GB&tab=to_ship')
            self.check_login()
            self.wait(lambda:bool(self.driver.find_elements(By.CSS_SELECTOR,'[role=tab]')))
            self.guard()
            # Home link can retain saved filters. Refuse filtered results until reset.
            tabs=[e for e in self.driver.find_elements(By.CSS_SELECTOR,'[role=tab]') if re.fullmatch(r'To ship\s*\d*',e.text.strip())]
            if len(tabs)!=1: raise OrderProblem('To ship tab could not be verified')
            tabs[0].click()
            filters=[e for e in self.driver.find_elements(By.CSS_SELECTOR,'button') if re.fullmatch(r'Filter(?:\s*\(\d+\))?',e.text.strip())]
            if len(filters)!=1: raise OrderProblem('Order filters could not be verified')
            filters[0].click()
            self.wait(lambda:bool(self.find_text('Clear all','button')))
            self.click_text('Clear all')
            label,expected_count=self.packing_option()
            label.click()
            # React can replace the clicked label immediately. Read its new
            # instance rather than dereferencing the pre-click DOM node.
            label,current_count=self.packing_option()
            if current_count!=expected_count:
                raise OrderProblem('Awaiting packing queue changed; rescan required')
            if not label.find_elements(By.CSS_SELECTOR,'input[type=radio]')[0].is_selected():
                raise OrderProblem('Awaiting packing filter was not selected')
            self.click_text('Apply')
            self.wait(lambda:not any(e.is_displayed() for e in self.driver.find_elements(By.CSS_SELECTOR,'[role=dialog]')))
            def page():
                self.guard()
                text=self.main_text()
                ids=[]
                for e in self.driver.find_elements(By.CSS_SELECTOR,'a[href*="/order/detail?order_no="]'):
                    if not e.is_displayed(): continue
                    row=e.find_element(By.XPATH,'ancestor::tr[1]')
                    if 'Awaiting packing' not in lines(row.text): return None
                    value=parse_qs(urlparse(e.get_attribute('href')).query).get('order_no',[''])[0]
                    if re.fullmatch(r'\d{10,30}',value) and value not in ids: ids.append(value)
                if not ids and not any(v in text for v in ('No orders','No data','No results')): return None
                return ids
            result=[]; seen=set()
            def ready_page():
                current=page()
                return (current,) if current is not None else False
            for _ in range(500):
                # Wrap empty pages so WebDriverWait does not treat [] as loading.
                ids=self.wait(ready_page)[0]
                if not ids and expected_count==0: return []
                signature=tuple(ids)
                if signature in seen: raise OrderProblem('Order pagination repeated; scan incomplete')
                seen.add(signature); result.extend(i for i in ids if i not in result)
                nexts=self.driver.find_elements(By.CSS_SELECTOR,'[aria-label="Next"]')
                if not nexts or len(nexts)!=1: raise OrderProblem('Order pagination could not be verified')
                nxt=nexts[0]
                if nxt.get_attribute('aria-disabled')=='true' or 'disabled' in (nxt.get_attribute('class') or ''):
                    if len(result)!=expected_count: raise OrderProblem('Awaiting packing queue changed; rescan required')
                    return result
                nxt.click()
                def changed_page():
                    current=page()
                    return current is not None and tuple(current)!=signature
                self.wait(changed_page)
            raise OrderProblem('Order pagination limit reached; scan incomplete')

    def submit_tracking(self,order_id,carrier,number):
        with self.lock:
            order=self.detail(order_id)
            expected={'number':number,'carrier':carrier}
            if order.tracking:
                if order.tracking==[expected]: return expected
                raise OrderProblem('Existing TikTok tracking conflicts')
            order.validate()
            # Tracking entry is deliberately unavailable until the live form is
            # verified on the installed host. Never guess a fulfilment action.
            raise OrderProblem('Tracking submission is not verified on this installation; add tracking manually')
