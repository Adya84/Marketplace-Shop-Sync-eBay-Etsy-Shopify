"""Prepare an unsaved Seller Center form through the signed-in browser only."""
from decimal import Decimal, InvalidOperation
from pathlib import Path
import logging
from .listings import validate_listing
from .listing_publishers import photo_bytes

# A bounded read of rendered controls only. No application state or endpoints.
PREFLIGHT_DOM=r'''
const visible=e=>{if(!e||!e.getClientRects().length)return false;let p=e;
 for(let i=0;p&&i<100;i++,p=p.parentElement){let s=getComputedStyle(p);
 if(s.display==='none'||s.visibility==='hidden'||s.opacity==='0')return false;}return !p;};
const all=s=>Array.from(document.querySelectorAll(s)).filter(visible);
const cut=v=>String(v??'').slice(0,50001), counts={}, pick=(name,s)=>{let a=all(s);counts[name]=a.length;return a.length===1?a[0]:null;};
const title=pick('title','input[data-id="product.publish.product_name"]');
const description=pick('description','#preview-product-description .ProseMirror[contenteditable=true]');
const images=pick('images','#preview-product-image');
const category=pick('category','[data-id="product.publish.category"]');
const brands=all('[role=combobox]:has(input[placeholder="Select a brand"])');
counts.brand=brands.length;
const sale=pick('sale','#preview-sale-information');
const inputs=sale?Array.from(sale.querySelectorAll('input')).filter(e=>visible(e)&&!['radio','checkbox'].includes(e.type)&&e.getAttribute('aria-hidden')!=='true'):[];
const parcel={}, selectors={weight_g:'[data-id="product.publish.package_weight"] input[placeholder="Enter the parcel weight"]',height_cm:'input[placeholder="Height"]',width_cm:'input[placeholder="Width"]',length_cm:'input[placeholder="Length"]'};
for(let [name,selector] of Object.entries(selectors)){let e=pick(name,selector);parcel[name]=e?cut(e.value):'';}
return {title:title?cut(title.value):'',description:description?cut(description.innerText):'',
 description_media:description?description.querySelectorAll('img,video,iframe').length:0,
 photos:images?Array.from(images.querySelectorAll('img')).filter(e=>(e.currentSrc||e.src)&&!(e.currentSrc||e.src).includes('image-upload-placeholder-')).length:0,
 category:category?cut(category.innerText):'',brand:brands.length===1?cut(brands[0].innerText):'',
 sales_values:inputs.slice(0,251).map(e=>cut(e.value)),overflow:inputs.length>251,
 variations:!!(sale&&Array.from(sale.querySelectorAll('[role=switch]')).some(e=>e.getAttribute('aria-checked')==='true')),
 parcel,counts};
'''


def prepare_plan(listing,photos):
    issues=validate_listing(dict(listing,destination='tiktok'))
    if issues: raise ValueError(' '.join(issues))
    if listing['currency']!='GBP': raise ValueError('The UK TikTok browser requires GBP prices.')
    variants=listing['variants']
    if len(variants)!=1 or variants[0].get('options'):
        raise ValueError('TikTok browser variation transfer is not available yet. Your complete variation listing remains saved in Shop Sync.')
    variant=variants[0]
    if variant['quantity']>999999: raise ValueError('TikTok stock must be 999999 or fewer per SKU.')
    if Decimal(str(variant['price'])).as_tuple().exponent < -2:
        raise ValueError('TikTok prices need at most two decimal places.')
    if len(variant['sku'])>50: raise ValueError('TikTok Seller SKU must be 50 characters or fewer.')
    settings=listing.get('settings') or {}
    category=' - '.join(part.strip() for part in str(settings.get('category_path') or '').split('>'))
    if not category or any(not part.strip() for part in category.split(' - ')):
        raise ValueError('Choose the TikTok category path in Shop defaults.')
    def amount(key,limit,multiplier=1,required=True):
        value=settings.get(key)
        if not required and value in (None,''): return ''
        try:
            number=Decimal(str(value))*multiplier
            if not number.is_finite() or not 0<number<=limit: raise ValueError()
        except (InvalidOperation,TypeError,ValueError):
            raise ValueError('Enter a valid TikTok '+key.replace('_',' ')+'.') from None
        return format(number.normalize(),'f')
    paths=[]
    for name in listing['photos']:
        photo_bytes(photos,name)
        paths.append(str((Path(photos)/name).resolve()))
    return {'title':listing['title'],'description':listing['description'],
            'stock':str(variant['quantity']),'price':format(Decimal(str(variant['price'])),'.2f'),
            'sku':variant['sku'],'category':category,'brand':str(settings.get('brand') or '').strip(),
            'weight_g':amount('weight_kg',100000,1000,required=False),
            **{key:amount(key,1000,required=False) for key in ('height_cm','width_cm','length_cm')},
            'photos':paths}


def _at_stage(stage,action,*args):
    from .order_models import OrderProblem
    try: return action(*args)
    except (ValueError,OrderProblem): raise
    except Exception as exc:
        from .order_browser import browser_failure
        # Never log exception strings, arguments, page contents or tracebacks.
        trace=exc.__traceback__; site='unknown'
        while trace:
            code=trace.tb_frame.f_code
            if Path(code.co_filename).name in ('tiktok_listing_form.py','order_browser.py'):
                site=Path(code.co_filename).name+':'+code.co_name+':'+str(trace.tb_lineno)
            trace=trace.tb_next
        logging.getLogger(__name__).warning('TikTok transfer stage=%s failure=%s site=%s',stage,browser_failure(exc),site)
        raise ValueError('TikTok transfer stopped during '+stage+' ('+browser_failure(exc)+'). Review the unsaved browser form before retrying.') from None


def fill_form(form,plan):
    _at_stage('unfinished-form check',form.assert_blank,plan)
    _at_stage('category selection',form.category,plan['category'])
    if plan['brand']: _at_stage('brand selection',form.brand,plan['brand'])
    for name in ('title','description','stock','price','sku','weight_g','height_cm','width_cm','length_cm'):
        if plan[name]!='' or name=='weight_g': _at_stage(name.replace('_',' '),form.set_field,name,plan[name])
    _at_stage('photo upload',form.upload,plan['photos'])
    _at_stage('field verification',form.verify,plan)
    return {'state':'needs_review','message':'Details and photos transferred to TikTok. Review parcel measurements, brand, attributes and compliance in the browser before submitting. This has not been published.'}


class SeleniumListingForm:
    """Only observed form controls. Never invokes save or submit buttons."""
    fields={
        'title':'input[data-id="product.publish.product_name"]',
        'description':'#preview-product-description .ProseMirror[contenteditable=true]',
        'stock':'#preview-sale-information input[role=spinbutton][aria-valuemax="999999"]:not([placeholder])',
        'price':'#preview-sale-information input[currency]:not([placeholder])',
        'sku':'#preview-sale-information input[id^="skus"]',
        'weight_g':'[data-id="product.publish.package_weight"] input[placeholder="Enter the parcel weight"]',
        'height_cm':'input[placeholder="Height"]',
        'width_cm':'input[placeholder="Width"]',
        'length_cm':'input[placeholder="Length"]',
    }

    def __init__(self,browser): self.browser=browser; self.driver=browser.driver

    def one(self,selector,visible=True):
        self.browser.guard()
        elements=self.driver.find_elements('css selector',selector)
        if visible: elements=[element for element in elements if element.is_displayed()]
        if len(elements)!=1: raise ValueError('TikTok form control is missing or ambiguous. Check the browser before continuing.')
        return elements[0]

    def field(self,name): return self.one(self.fields[name])

    def value(self,name):
        element=self.field(name)
        return element.text if name=='description' else element.get_attribute('value') or ''

    def image_sources(self):
        return {e.get_attribute('src') for e in self.driver.find_elements('css selector','#preview-product-image img')
                if e.get_attribute('src') and 'image-upload-placeholder-' not in e.get_attribute('src')}

    def assert_blank(self,plan):
        _at_stage('shop identity verification',self.browser.guard)
        state=_at_stage('bounded form read',self.driver.execute_script,PREFLIGHT_DOM)
        numeric=('weight_g','height_cm','width_cm','length_cm')
        required=('title','description','images','category')
        optional=('brand','sale',*numeric)
        if not isinstance(state,dict) or not isinstance(state.get('counts'),dict) or not isinstance(state.get('parcel'),dict):
            raise ValueError('TikTok form could not be read safely. Wait for the page to finish loading.')
        counts=state['counts']
        if any(type(counts.get(key)) is not int or counts[key]!=1 for key in required) or any(type(counts.get(key)) is not int or counts[key] not in (0,1) for key in optional):
            raise ValueError('TikTok form controls are missing or ambiguous. Wait for the page to finish loading.')
        if (any(not isinstance(state.get(key),str) for key in ('title','description','category','brand')) or
            any(not isinstance(state['parcel'].get(key),str) for key in numeric) or
            type(state.get('photos')) is not int or state['photos']<0 or
            type(state.get('description_media')) is not int or state['description_media']<0 or
            type(state.get('variations')) is not bool or not isinstance(state.get('sales_values'),list) or
            len(state['sales_values'])>251 or any(not isinstance(value,str) for value in state['sales_values']) or state.get('overflow')):
            raise ValueError('TikTok form could not be read safely. Review the browser before continuing.')
        if state['title'].strip() or state['description'].strip() or state['description_media'] or state['photos']:
            raise ValueError('An unfinished TikTok form is open. Finish or clear it in the browser before transferring another listing.')
        current=state['category'].strip()
        if current and current!=plan['category']:
            raise ValueError('A different TikTok category is already selected. Clear the unfinished form before transferring.')
        if current and counts['sale']!=1:
            raise ValueError('Wait for the TikTok sales fields to finish loading before transferring.')
        brand=state['brand'].strip()
        if brand and brand!='Select a brand' and brand.casefold()!=plan['brand'].casefold():
            raise ValueError('A different TikTok brand is already selected. Clear the unfinished form before transferring.')
        for name in numeric:
            actual=state['parcel'][name].strip().replace(',','')
            if not actual: continue
            try: equal=bool(plan[name]) and Decimal(actual)==Decimal(plan[name])
            except InvalidOperation: equal=False
            if not equal:
                raise ValueError('Existing TikTok parcel details differ from this listing. Check or clear them in the browser before transferring.')
        if any(value.strip() for value in state['sales_values']):
            raise ValueError('An unfinished TikTok price or variation form is open. Finish or clear it before transferring.')
        if state['variations']:
            raise ValueError('The TikTok variation editor is open. Turn off Add variations for a single-SKU transfer.')

    @staticmethod
    def xpath_literal(text):
        if "'" not in text: return "'"+text+"'"
        return 'concat('+',"\'",'.join("'"+part+"'" for part in text.split("'"))+')'

    def text_control(self,text,missing_ok=False):
        self.browser.guard()
        literal=self.xpath_literal(text)
        matches=[e for e in self.driver.find_elements('xpath',
            f'//*[normalize-space(.)={literal} and not(.//*[normalize-space(.)={literal}])]') if e.is_displayed()]
        if not matches and missing_ok: return None
        if len(matches)!=1: raise ValueError('TikTok choice is missing or ambiguous. Select it in the browser.')
        return matches[0]

    def category(self,value):
        wrapper=self.one('[data-id="product.publish.category"]')
        if wrapper.text.strip()==value: return
        self.one('#product-cascader-select-view').click()
        search=self.one('input[placeholder="Search"]')
        search.send_keys(value.split(' - ')[-1])
        self.browser.wait(lambda:self.text_control(value,missing_ok=True)).click()
        self.browser.wait(lambda:self.one('[data-id="product.publish.category"]').text.strip()==value)
        self.browser.wait(lambda:bool(self.driver.find_elements('css selector','#preview-sale-information input[id^="skus"]')))

    def brand(self,value):
        selector='[role=combobox]:has(input[placeholder="Select a brand"])'
        self.one(selector).click()
        if value.casefold()=='no brand':
            self.text_control("Choose 'No brand'").click()
        else:
            self.one('input[placeholder="Search from 10,000+ brands"]').send_keys(value)
            self.browser.wait(lambda:self.text_control(value,missing_ok=True)).click()
        self.browser.wait(lambda:value.casefold()==self.one(selector).text.strip().casefold())

    def set_field(self,name,value):
        from selenium.webdriver.common.keys import Keys
        if name=='weight_g':
            unit=self.one('[data-id="product.publish.package_weight"] [role=combobox]')
            if unit.text.strip()!='Grams (g)':
                unit.click(); self.text_control('Grams (g)').click()
        element=self.field(name)
        element.click(); element.send_keys(Keys.CONTROL,'a'); element.send_keys(Keys.BACKSPACE)
        if value:
            if name=='description' or any(ord(char)>0xffff for char in value):
                # Native text insertion supports emoji and contenteditable input
                # events without rewriting ProseMirror's DOM or internal state.
                self.driver.execute_cdp_cmd('Input.insertText',{'text':value})
            else: element.send_keys(value)
        element.send_keys(Keys.TAB)

    def upload(self,paths):
        uploader=self.one('#preview-product-image input[type=file]',visible=False)
        uploader.send_keys('\n'.join(paths))
        self.browser.wait(lambda:len(self.image_sources())==len(paths))

    def verify(self,plan):
        for name in self.fields:
            if plan[name]=='' and name!='weight_g': continue
            actual=self.value(name).replace('\r\n','\n').strip()
            expected=plan[name].replace('\r\n','\n').strip()
            if not expected: equal=not actual
            elif name in ('stock','price','weight_g','height_cm','width_cm','length_cm'):
                try: equal=Decimal(actual.replace(',',''))==Decimal(expected)
                except InvalidOperation: equal=False
            else: equal=actual==expected
            if not equal: raise ValueError('TikTok did not retain the '+name.replace('_',' ')+'. Review the partially filled form in the browser.')
        if self.one('[data-id="product.publish.category"]').text.strip()!=plan['category']:
            raise ValueError('TikTok category changed. Review the browser form.')
        if len(self.image_sources())!=len(plan['photos']):
            raise ValueError('TikTok has not confirmed every photo. Review the browser form.')


def transfer_listing(browser,listing,photos):
    # All validation is completed before opening or changing a browser form.
    plan=prepare_plan(listing,photos)
    with browser.lock:
        try:
            _at_stage('opening product editor',browser.open_listing_editor)
            return fill_form(SeleniumListingForm(browser),plan)
        except Exception:
            # poll() reads the local child status; do not send another command
            # to a failed driver or attempt to restart an unsaved product tab.
            process=getattr(getattr(browser.driver,'service',None),'process',None)
            exit_code=process.poll() if process is not None else None
            logging.getLogger(__name__).warning('TikTok transfer driver_exit=%s',exit_code)
            raise
