"""Prepare an unsaved Seller Center form through the signed-in browser only."""
from decimal import Decimal, InvalidOperation
from pathlib import Path
from .listings import validate_listing
from .listing_publishers import photo_bytes


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
            'weight_g':amount('weight_kg',100000,1000),
            **{key:amount(key,1000,required=False) for key in ('height_cm','width_cm','length_cm')},
            'photos':paths}


def fill_form(form,plan):
    form.assert_blank(plan)
    form.category(plan['category'])
    if plan['brand']: form.brand(plan['brand'])
    for name in ('title','description','stock','price','sku','weight_g','height_cm','width_cm','length_cm'):
        if plan[name]!='': form.set_field(name,plan[name])
    form.upload(plan['photos'])
    form.verify(plan)
    return {'state':'needs_review','message':'Details and photos transferred to TikTok. Review brand, attributes and compliance in the browser before submitting. This has not been published.'}


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
        if self.value('title').strip() or self.value('description').strip() or self.image_sources():
            raise ValueError('An unfinished TikTok form is open. Finish or clear it in the browser before transferring another listing.')
        current=self.one('[data-id="product.publish.category"]').text.strip()
        if current and current!=plan['category']:
            raise ValueError('A different TikTok category is already selected. Clear the unfinished form before transferring.')
        brands=self.driver.find_elements('css selector','[role=combobox]:has(input[placeholder="Select a brand"])')
        if len(brands)>1: raise ValueError('TikTok brand controls are ambiguous.')
        if brands:
            brand=brands[0].text.strip()
            if brand and brand!='Select a brand' and brand.casefold()!=plan['brand'].casefold():
                raise ValueError('A different TikTok brand is already selected. Clear the unfinished form before transferring.')
        for name in ('weight_g','height_cm','width_cm','length_cm'):
            controls=self.driver.find_elements('css selector',self.fields[name])
            if not any(e.is_displayed() for e in controls): continue
            actual=self.value(name).strip().replace(',','')
            if not actual: continue
            try: equal=bool(plan[name]) and Decimal(actual)==Decimal(plan[name])
            except InvalidOperation: equal=False
            if not equal:
                raise ValueError('Existing TikTok parcel details differ from this listing. Check or clear them in the browser before transferring.')
        # A user can have entered only price/stock or variation values.
        sale=self.driver.find_elements('css selector','#preview-sale-information')
        if len(sale)>1: raise ValueError('TikTok sales controls are ambiguous.')
        if sale:
            inputs=sale[0].find_elements('css selector','input')
            if any(e.is_displayed() and e.get_attribute('type') not in ('radio','checkbox') and
                   e.get_attribute('aria-hidden')!='true' and (e.get_attribute('value') or '').strip()
                   for e in inputs):
                raise ValueError('An unfinished TikTok price or variation form is open. Finish or clear it before transferring.')
            if any(e.get_attribute('aria-checked')=='true' for e in sale[0].find_elements('css selector','[role=switch]')):
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
        element.click(); element.send_keys(Keys.CONTROL,'a'); element.send_keys(value); element.send_keys(Keys.TAB)

    def upload(self,paths):
        uploader=self.one('#preview-product-image input[type=file]',visible=False)
        uploader.send_keys('\n'.join(paths))
        self.browser.wait(lambda:len(self.image_sources())==len(paths))

    def verify(self,plan):
        for name in self.fields:
            if plan[name]=='': continue
            actual=self.value(name).replace('\r\n','\n').strip()
            expected=plan[name].replace('\r\n','\n').strip()
            if name in ('stock','price','weight_g','height_cm','width_cm','length_cm'):
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
        browser.open_listing_editor()
        return fill_form(SeleniumListingForm(browser),plan)
