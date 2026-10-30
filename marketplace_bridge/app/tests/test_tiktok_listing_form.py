import copy
import pytest
from app.tiktok_listing_form import prepare_plan, fill_form, SeleniumListingForm


def product(tmp_path):
    name='a'*32+'.jpg'; (tmp_path/name).write_bytes(b'\xff\xd8\xfffixture')
    return {'id':'b'*32,'revision':2,'destination':'tiktok','title':'Wood chopping board',
        'description':'Made from wood\nPersonalised for you','currency':'GBP','photos':[name],
        'variants':[{'sku':'BOARD-1','price':'18.50','quantity':4,'options':[]}],
        'settings':{'category_path':'Kitchenware > Kitchen Knives > Chopping Boards',
                    'weight_kg':'1.225','height_cm':'3','width_cm':'20','length_cm':'30'}}


def test_transfer_converts_explicit_weight_and_uses_saved_photos(tmp_path):
    listing=product(tmp_path)
    plan=prepare_plan(listing,tmp_path)
    assert plan['weight_g']=='1225'
    assert plan['photos']==[str((tmp_path/listing['photos'][0]).resolve())]
    assert plan['category']=='Kitchenware - Kitchen Knives - Chopping Boards'
    assert plan['stock']=='4' and plan['price']=='18.50' and plan['sku']=='BOARD-1'
    assert listing['settings']['weight_kg']=='1.225'


def test_unsaved_transfer_clears_tiktok_suggested_weight_when_packed_weight_is_unknown(tmp_path):
    listing=product(tmp_path); listing['settings'].pop('weight_kg')
    plan=prepare_plan(listing,tmp_path); form=Form()
    assert plan['weight_g']==''
    result=fill_form(form,plan)
    assert ('weight_g','') in form.changes
    assert result['state']=='needs_review' and 'parcel' in result['message']


@pytest.mark.parametrize('key,value,expected',[
    ('weight_kg','NaN','weight'),('weight_kg','0','weight'),
    ('weight_kg','101','weight'),('length_cm','-1','length'),
    ('length_cm','Infinity','length'),('category_path','','category')])
def test_invalid_settings_stop_before_browser_changes(tmp_path,key,value,expected):
    listing=product(tmp_path); listing['settings'][key]=value
    with pytest.raises(ValueError,match=expected): prepare_plan(listing,tmp_path)


def test_transfer_never_silently_loses_variants_or_uses_other_currency(tmp_path):
    listing=product(tmp_path); listing['variants'][0]['options']=[{'name':'Size','value':'Large'}]
    with pytest.raises(ValueError,match='variation'): prepare_plan(listing,tmp_path)
    listing=product(tmp_path); listing['currency']='USD'
    with pytest.raises(ValueError,match='GBP'): prepare_plan(listing,tmp_path)
    listing=product(tmp_path); listing['photos']=['../secret.jpg']
    with pytest.raises(ValueError,match='photo'): prepare_plan(listing,tmp_path)


class Form:
    def __init__(self,occupied=False): self.occupied=occupied; self.changes=[]
    def assert_blank(self,plan):
        if self.occupied: raise ValueError('An unfinished TikTok form is open.')
    def category(self,value): self.changes.append(('category',value))
    def brand(self,value): self.changes.append(('brand',value))
    def set_field(self,name,value): self.changes.append((name,value))
    def upload(self,paths): self.changes.append(('photos',paths))
    def verify(self,plan): self.changes.append(('verify',copy.deepcopy(plan)))


def test_existing_form_is_never_overwritten(tmp_path):
    form=Form(occupied=True)
    with pytest.raises(ValueError,match='unfinished'): fill_form(form,prepare_plan(product(tmp_path),tmp_path))
    assert form.changes==[]


def test_transfer_fills_all_shared_fields_and_returns_review_not_published(tmp_path):
    form=Form(); plan=prepare_plan(product(tmp_path),tmp_path)
    result=fill_form(form,plan)
    assert result['state']=='needs_review' and 'id' not in result
    for key in ('title','description','stock','price','sku','weight_g','height_cm','width_cm','length_cm'):
        assert (key,plan[key]) in form.changes
    assert ('photos',plan['photos']) in form.changes
    assert form.changes[-1][0]=='verify'


def test_failed_field_verification_cannot_report_prepared(tmp_path):
    class ChangedForm(Form):
        def verify(self,plan): raise ValueError('TikTok did not retain the price.')
    with pytest.raises(ValueError,match='retain'): fill_form(ChangedForm(),prepare_plan(product(tmp_path),tmp_path))


def test_browser_failures_identify_the_stage_without_exposing_driver_details(tmp_path):
    from selenium.common.exceptions import TimeoutException
    class SlowForm(Form):
        def category(self,value): raise TimeoutException('secret driver URL or page contents')
    with pytest.raises(ValueError) as error: fill_form(SlowForm(),prepare_plan(product(tmp_path),tmp_path))
    assert 'category' in str(error.value) and 'TimeoutException' in str(error.value)
    assert 'secret' not in str(error.value)


def test_failure_diagnostics_log_only_static_callsite(caplog):
    from app.tiktok_listing_form import _at_stage
    from urllib3.exceptions import ProtocolError
    def broken(): raise ProtocolError('secret token and product details')
    with pytest.raises(ValueError): _at_stage('bounded form read',broken)
    assert 'bounded form read' in caplog.text and 'ProtocolError' in caplog.text
    assert 'secret' not in caplog.text and 'product details' not in caplog.text


def test_emoji_description_uses_browser_text_insertion_without_losing_unicode():
    from types import SimpleNamespace
    from selenium.webdriver.common.keys import Keys
    calls=[]
    class Element:
        def click(self): calls.append(('click',))
        def send_keys(self,*keys):
            if any(any(ord(c)>65535 for c in key) for key in keys):
                raise AssertionError('ChromeDriver send_keys cannot handle non-BMP text')
            calls.append(('keys',keys))
    browser=SimpleNamespace(driver=SimpleNamespace(execute_cdp_cmd=lambda name,args:calls.append((name,args))))
    form=SeleniumListingForm(browser); form.field=lambda name:Element()
    text='Christmas teacher gift 🎄\nPersonalised for you 🎁'
    form.set_field('description',text)
    assert ('Input.insertText',{'text':text}) in calls
    assert calls[-1]==('keys',(Keys.TAB,))


def test_fractional_pennies_are_rejected_instead_of_changing_the_price(tmp_path):
    listing=product(tmp_path); listing['variants'][0]['price']='18.555'
    with pytest.raises(ValueError,match='decimal'): prepare_plan(listing,tmp_path)


def test_ambiguous_browser_controls_are_rejected_without_typing():
    from types import SimpleNamespace
    controls=[SimpleNamespace(is_displayed=lambda:True),SimpleNamespace(is_displayed=lambda:True)]
    browser=SimpleNamespace(driver=SimpleNamespace(find_elements=lambda *args:controls),guard=lambda:None)
    form=SeleniumListingForm(browser)
    with pytest.raises(ValueError,match='ambiguous'): form.field('title')


def test_tiktok_control_stock_limit_is_checked_before_browser_access(tmp_path):
    listing=product(tmp_path); listing['variants'][0]['quantity']=1000000
    with pytest.raises(ValueError,match='999999'): prepare_plan(listing,tmp_path)


@pytest.mark.parametrize('field,existing',[('weight_g','900'),('weight_g','1225'),('height_cm','9'),('width_cm','99'),('length_cm','40')])
def test_existing_parcel_details_cannot_be_overwritten(tmp_path,field,existing):
    from types import SimpleNamespace
    plan=prepare_plan(product(tmp_path),tmp_path)
    if field=='weight_g' and existing=='1225': plan['weight_g']=''
    state=blank_snapshot(); state['parcel'][field]=existing; state['counts'][field]=1
    browser=SimpleNamespace(driver=SimpleNamespace(execute_script=lambda *args:state),guard=lambda:None)
    form=SeleniumListingForm(browser)
    with pytest.raises(ValueError,match='parcel'): form.assert_blank(plan)


def blank_snapshot():
    return {'title':'','description':'','description_media':0,'photos':0,'category':'','brand':'',
            'sales_values':[],'variations':False,'parcel':{key:'' for key in ('weight_g','height_cm','width_cm','length_cm')},
            'counts':{'title':1,'description':1,'images':1,'category':1,'brand':0,'sale':0,
                      'weight_g':0,'height_cm':0,'width_cm':0,'length_cm':0}}


def test_blank_form_preflight_uses_one_bounded_dom_read(tmp_path):
    from types import SimpleNamespace
    calls=[]
    def snapshot(script): calls.append(script); return blank_snapshot()
    def native(*args): raise AssertionError('Preflight must not call native element inspection commands')
    browser=SimpleNamespace(guard=lambda:None,driver=SimpleNamespace(execute_script=snapshot,find_elements=native))
    SeleniumListingForm(browser).assert_blank(prepare_plan(product(tmp_path),tmp_path))
    assert len(calls)==1


@pytest.mark.parametrize('update',[
    {'title':'Already entered'}, {'description':'Seller text'}, {'description_media':1}, {'photos':1},
    {'category':'Other category'}, {'brand':'Other brand'}, {'sales_values':['4']}, {'variations':True}])
def test_dom_snapshot_rejects_occupied_fields(tmp_path,update):
    from types import SimpleNamespace
    state=blank_snapshot(); state.update(update)
    browser=SimpleNamespace(guard=lambda:None,driver=SimpleNamespace(execute_script=lambda *args:state))
    with pytest.raises(ValueError): SeleniumListingForm(browser).assert_blank(prepare_plan(product(tmp_path),tmp_path))


@pytest.mark.parametrize('state',[None,{},dict(blank_snapshot(),counts=dict(blank_snapshot()['counts'],title=2)),
    dict(blank_snapshot(),counts=dict(blank_snapshot()['counts'],description=0))])
def test_dom_snapshot_fails_closed_when_missing_or_ambiguous(tmp_path,state):
    from types import SimpleNamespace
    browser=SimpleNamespace(guard=lambda:None,driver=SimpleNamespace(execute_script=lambda *args:state))
    with pytest.raises(ValueError): SeleniumListingForm(browser).assert_blank(prepare_plan(product(tmp_path),tmp_path))
