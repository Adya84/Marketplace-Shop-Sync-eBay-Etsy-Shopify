import copy
import pytest
from app.tiktok_listing_form import prepare_plan


def listing(tmp_path):
    photo='a'*32+'.png'; (tmp_path/photo).write_bytes(b'\x89PNG\r\n\x1a\nfixture')
    return {'id':'b'*32,'title':'Wood board','description':'Personalised wooden board','currency':'GBP',
        'photos':[photo],'settings':{'category_path':'Kitchenware > Kitchen Knives > Chopping Boards'},
        'variants':[
            {'sku':'S-T','price':'12.99','quantity':0,'options':[{'name':'Size','value':'Small'},{'name':'Design','value':'Teacher'}]},
            {'sku':'S-A','price':'13.99','quantity':2,'options':[{'name':'Size','value':'Small'},{'name':'Design','value':'Assistant'}]},
            {'sku':'L-T','price':'15.99','quantity':3,'options':[{'name':'Size','value':'Large'},{'name':'Design','value':'Teacher'}]},
            {'sku':'L-A','price':'16.99','quantity':4,'options':[{'name':'Size','value':'Large'},{'name':'Design','value':'Assistant'}]}]}


def test_complete_matrix_preserves_each_sku_price_stock_and_option_order(tmp_path):
    master=listing(tmp_path); original=copy.deepcopy(master)
    plan=prepare_plan(master,tmp_path)
    assert plan['axes']==[{'name':'Size','values':['Small','Large']},{'name':'Design','values':['Teacher','Assistant']}]
    assert plan['rows']==[
        {'values':['Small','Teacher'],'sku':'S-T','price':'12.99','stock':'0'},
        {'values':['Small','Assistant'],'sku':'S-A','price':'13.99','stock':'2'},
        {'values':['Large','Teacher'],'sku':'L-T','price':'15.99','stock':'3'},
        {'values':['Large','Assistant'],'sku':'L-A','price':'16.99','stock':'4'}]
    assert master==original


def test_one_option_one_row_keeps_option_instead_of_flattening(tmp_path):
    master=listing(tmp_path); master['variants']=master['variants'][:1]
    master['variants'][0]['options']=master['variants'][0]['options'][:1]
    assert prepare_plan(master,tmp_path)['axes']==[{'name':'Size','values':['Small']}]


def test_sparse_matrix_stops_before_inventing_unrequested_variant(tmp_path):
    master=listing(tmp_path); master['variants'].pop()
    with pytest.raises(ValueError,match='combination'): prepare_plan(master,tmp_path)


@pytest.mark.parametrize('field,value,message',[
    ('price','12.999','decimal'),('quantity',1000000,'stock'),('sku','x'*51,'SKU')])
def test_every_variant_is_validated_not_just_first(tmp_path,field,value,message):
    master=listing(tmp_path); master['variants'][-1][field]=value
    with pytest.raises(ValueError,match=message): prepare_plan(master,tmp_path)


@pytest.mark.parametrize('value',['small',' Small ','x'*51,'Small\nOther'])
def test_ambiguous_or_overlong_option_labels_stop_before_browser_changes(tmp_path,value):
    master=listing(tmp_path)
    for row in master['variants'][2:]: row['options'][0]['value']=value
    with pytest.raises(ValueError,match='option|variation'): prepare_plan(master,tmp_path)


def test_more_than_three_axes_are_rejected(tmp_path):
    master=listing(tmp_path); master['variants']=master['variants'][:1]
    master['variants'][0]['options']=[{'name':str(i),'value':'one'} for i in range(4)]
    with pytest.raises(ValueError,match='three|3'): prepare_plan(master,tmp_path)


def test_adapter_row_limit_is_checked_before_browser_changes(tmp_path):
    master=listing(tmp_path)
    master['variants']=[{'sku':str(i),'price':'1','quantity':1,'options':[{'name':'Design','value':str(i)}]} for i in range(101)]
    with pytest.raises(ValueError,match='100'): prepare_plan(master,tmp_path)


def test_generated_rows_match_by_options_even_when_tiktok_reorders_them():
    from app.tiktok_listing_variations import match_rows
    expected=[{'values':['Small','Teacher'],'sku':'S-T'},{'values':['Large','Teacher'],'sku':'L-T'}]
    actual=[['Large','Teacher'],['Small','Teacher']]
    assert match_rows(expected,actual)=={'S-T':1,'L-T':0}


@pytest.mark.parametrize('actual',[
    [['Small','Teacher']],
    [['Small','Teacher'],['Large','Teacher'],['Other','Teacher']],
    [['Small','Teacher'],['Small','Teacher']],
    [['Teacher','Small'],['Teacher','Large']],
    [['small','Teacher'],['Large','Teacher']]])
def test_missing_extra_duplicate_or_changed_option_rows_are_never_guessed(actual):
    from app.tiktok_listing_variations import match_rows
    expected=[{'values':['Small','Teacher'],'sku':'S-T'},{'values':['Large','Teacher'],'sku':'L-T'}]
    with pytest.raises(ValueError,match='variation'): match_rows(expected,actual)


def grid():
    def row(labels,identifier):
        return {'cells':[{'text':text,'span':span,'colspan':1} for text,span in labels]+[
            {'text':'','span':1,'colspan':1} for _ in range(5)],
            'id':identifier,'stock':['0'],'price':['12.99'],'sku':['']}
    return {'headers':['Design','Size','*\nStock','*\nRetail price','Seller SKU','Product identifier code',''],
        'rows':[row([('Teacher',2),('Small',1)],'skus841'),row([('Large',1)],'skus859'),
                row([('Assistant',2),('Small',1)],'skus842'),row([('Large',1)],'skus860')]}


def test_grouped_tiktok_cells_are_expanded_to_exact_option_combinations():
    from app.tiktok_listing_variations import decode_rows
    rows=decode_rows(grid(),['Design','Size'])
    assert [row['values'] for row in rows]==[['Teacher','Small'],['Teacher','Large'],['Assistant','Small'],['Assistant','Large']]
    assert [row['id'] for row in rows]==['skus841','skus859','skus842','skus860']


@pytest.mark.parametrize('change',[
    lambda s:s['headers'].__setitem__(0,'Different axis'),
    lambda s:s['rows'][0]['cells'][0].__setitem__('span',5),
    lambda s:s['rows'][1].__setitem__('id','skus841'),
    lambda s:s['rows'][1].__setitem__('price',['1','2']),
    lambda s:s['rows'][1]['cells'].pop(),
    lambda s:s['rows'][1].__setitem__('id','unsafe"selector')])
def test_ambiguous_or_incomplete_grouped_table_is_rejected(change):
    from app.tiktok_listing_variations import decode_rows
    snapshot=grid(); change(snapshot)
    with pytest.raises(ValueError,match='variation'): decode_rows(snapshot,['Design','Size'])


def test_variation_transfer_never_overwrites_a_single_sku_row(tmp_path):
    from app.tiktok_listing_form import fill_form
    calls=[]
    class Form:
        def assert_blank(self,p): pass
        def category(self,v): pass
        def set_field(self,name,value): calls.append(name)
        def variations(self,p): calls.append(('variants',[r['sku'] for r in p['rows']]))
        def upload(self,p): pass
        def verify(self,p): pass
    result=fill_form(Form(),prepare_plan(listing(tmp_path),tmp_path))
    assert ('variants',['S-T','S-A','L-T','L-A']) in calls
    assert not {'stock','price','sku'}.intersection(c for c in calls if isinstance(c,str))
    assert result['state']=='needs_review'


@pytest.mark.parametrize('field,value',[('price','13.00'),('stock','1'),('sku','WRONG')])
def test_changed_row_values_cannot_pass_final_verification(field,value):
    from app.tiktok_listing_variations import verify_rows
    expected=[{'values':['Teacher'],'sku':'TEST-T','price':'12.99','stock':'0'}]
    actual=[dict(expected[0],id='skus1')]; actual[0][field]=value
    with pytest.raises(ValueError,match='variation'): verify_rows(expected,actual)


def test_exact_values_are_verified_after_row_reordering():
    from app.tiktok_listing_variations import verify_rows
    expected=[{'values':['Teacher'],'sku':'TEST-T','price':'12.99','stock':'0'},
              {'values':['Assistant'],'sku':'TEST-A','price':'13.99','stock':'4'}]
    assert verify_rows(expected,[dict(expected[1],id='skus2'),dict(expected[0],id='skus1')]) is None


def test_browser_table_snapshot_uses_one_read_and_preserves_grouped_values():
    from types import SimpleNamespace
    from app.tiktok_listing_form import SeleniumListingForm
    reads=[]
    def read(script): reads.append(script); return grid()
    browser=SimpleNamespace(guard=lambda:None,driver=SimpleNamespace(execute_script=read))
    rows=SeleniumListingForm(browser).variation_rows({'axes':[{'name':'Design'},{'name':'Size'}]})
    assert rows[1]['values']==['Teacher','Large'] and rows[1]['id']=='skus859'
    assert len(reads)==1


def test_reused_live_row_id_is_rechecked_before_any_field_write():
    from types import SimpleNamespace
    from app.tiktok_listing_form import SeleniumListingForm
    from app.tiktok_listing_variations import decode_rows
    old=grid(); changed=copy.deepcopy(old)
    changed['rows'][0]['id'],changed['rows'][2]['id']=changed['rows'][2]['id'],changed['rows'][0]['id']
    target=SimpleNamespace(is_displayed=lambda:True)
    container=SimpleNamespace(find_elements=lambda *a:[target])
    sku=SimpleNamespace(find_element=lambda *a:container)
    browser=SimpleNamespace(driver=SimpleNamespace(execute_script=lambda *a:{'snapshot':changed,'id':'skus841','connected':True}))
    form=SeleniumListingForm(browser); form.one=lambda s:sku
    form.variation_rows=lambda p:decode_rows(old,['Design','Size'])
    writes=[]; form.insert_text=lambda *a:writes.append(a)
    rows=[{'values':['Teacher','Small'],'sku':'TS','price':'1','stock':'0'},
          {'values':['Teacher','Large'],'sku':'TL','price':'2','stock':'0'},
          {'values':['Assistant','Small'],'sku':'AS','price':'3','stock':'0'},
          {'values':['Assistant','Large'],'sku':'AL','price':'4','stock':'0'}]
    with pytest.raises(ValueError,match='variation'):
        form.set_variation_field({'rows':rows,'axes':[{'name':'Design'},{'name':'Size'}]},rows[0],'price')
    assert writes==[]


@pytest.mark.parametrize('name',['Save as draft','Submit for review'])
def test_custom_axis_matching_final_action_never_clicks_the_page_button(name):
    from types import SimpleNamespace
    from app.tiktok_listing_form import SeleniumListingForm
    clicks=[]; entered=[]
    class Element:
        def __init__(self,label): self.label=label
        def click(self): clicks.append(self.label)
        def is_displayed(self): return True
        def get_attribute(self,key): return None
        def find_element(self,*args): return popup
    wrapper=Element('picker'); addnew=Element('Add new'); add=Element('Add'); entry=Element('name input')
    class Popup:
        def find_elements(self,kind,selector):
            if selector=='input': return [entry]
            if kind=='xpath': return [add]  # fixed Add action inside picker only
            return []  # no existing option bearing the custom name
    popup=Popup()
    form=SeleniumListingForm(SimpleNamespace(driver=SimpleNamespace()))
    def page_text(text,missing_ok=False):
        if text==name: return Element('FORBIDDEN final action')
        assert text=='Add new'
        return addnew
    form.text_control=page_text
    form.insert_text=lambda element,text:entered.append(text)
    form.choose_variation_name(wrapper,name)
    assert 'FORBIDDEN final action' not in clicks
    assert entered==[name] and clicks==['picker','Add new','Add']
