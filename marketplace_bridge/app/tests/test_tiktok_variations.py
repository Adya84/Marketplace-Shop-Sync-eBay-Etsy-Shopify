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


@pytest.mark.parametrize('value',['small',' Small ','x'*51])
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
