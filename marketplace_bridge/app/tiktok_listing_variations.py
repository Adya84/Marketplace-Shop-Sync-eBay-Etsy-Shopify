"""Exact option-combination matching for the visible TikTok SKU table."""
import re
from decimal import Decimal, InvalidOperation


TABLE_DOM=r'''
const section=document.querySelector('#preview-sale-information');
if(!section)return null;
const rows=Array.from(section.querySelectorAll('tr'));
const heads=rows.filter(r=>r.querySelector('th'));
if(heads.length!==1)return null;
const values=(r,s)=>Array.from(r.querySelectorAll(s)).slice(0,3).map(e=>e.value.slice(0,101));
return {headers:Array.from(heads[0].children).slice(0,11).map(e=>e.innerText.slice(0,101)),
 rows:rows.filter(r=>r.querySelector('td')).slice(0,101).map(r=>({
 cells:Array.from(r.children).slice(0,11).map(c=>({text:c.innerText.slice(0,101),span:c.rowSpan,colspan:c.colSpan})),
 id:r.querySelector('input[id^=skus]')?.id||'',
 stock:values(r,'input[role=spinbutton][aria-valuemax="999999"]:not([placeholder])'),
 price:values(r,'input[currency]:not([placeholder])'),sku:values(r,'input[id^=skus]')}))};
'''


def decode_rows(snapshot,names):
    """Expand observed HTML row spans; never infer missing SKU combinations."""
    def fail(): raise ValueError('TikTok variation table is incomplete or ambiguous. Review the browser form.')
    if not isinstance(snapshot,dict) or not isinstance(snapshot.get('headers'),list) or not isinstance(snapshot.get('rows'),list): fail()
    headers=snapshot['headers']; raw=snapshot['rows']; size=len(names)
    if not 1<=size<=3 or len(headers)!=size+5 or not 1<=len(raw)<=100: fail()
    if headers[:size]!=names or [h.strip('* \n') if isinstance(h,str) else None for h in headers[size:size+3]]!=['Stock','Retail price','Seller SKU']: fail()
    carry=[None]*size; remaining=[0]*size; result=[]; identifiers=set()
    for row in raw:
        if not isinstance(row,dict) or not isinstance(row.get('cells'),list): fail()
        cells=row['cells']; active=sum(count>0 for count in remaining)
        if len(cells)+active!=len(headers): fail()
        for cell in cells:
            if (not isinstance(cell,dict) or not isinstance(cell.get('text'),str) or len(cell['text'])>100 or
                type(cell.get('span')) is not int or not 1<=cell['span']<=100 or cell.get('colspan')!=1): fail()
        identifier=row.get('id')
        if not isinstance(identifier,str) or not re.fullmatch(r'skus\d+',identifier) or identifier in identifiers: fail()
        identifiers.add(identifier)
        data={'id':identifier}; values=[]; cursor=0
        for axis in range(size):
            if remaining[axis]: remaining[axis]-=1; values.append(carry[axis])
            else:
                cell=cells[cursor]; cursor+=1
                value=cell['text'].strip()
                if not value or len(value)>50: fail()
                values.append(value); carry[axis]=value; remaining[axis]=cell['span']-1
        if any(cell['span']!=1 for cell in cells[cursor:]): fail()
        for name in ('stock','price','sku'):
            field=row.get(name)
            if not isinstance(field,list) or len(field)!=1 or not isinstance(field[0],str) or len(field[0])>100: fail()
            data[name]=field[0]
        data['values']=values; result.append(data)
    if any(remaining): fail()
    return result


def match_rows(expected,actual):
    """Return SKU -> current row index only for the complete expected matrix."""
    def fail(): raise ValueError('TikTok variation rows differ from this listing. Review the browser before continuing.')
    if not isinstance(actual,list) or len(actual)!=len(expected) or len(actual)>100: fail()
    indices={}
    for index,values in enumerate(actual):
        if not isinstance(values,list) or any(not isinstance(value,str) for value in values): fail()
        key=tuple(values)
        if key in indices: fail()
        indices[key]=index
    wanted=[tuple(row['values']) for row in expected]
    if len(set(wanted))!=len(wanted) or set(wanted)!=set(indices): fail()
    return {row['sku']:indices[tuple(row['values'])] for row in expected}


def verify_rows(expected,actual):
    indices=match_rows(expected,[row['values'] for row in actual])
    for row in expected:
        current=actual[indices[row['sku']]]
        try:
            equal=(current['sku']==row['sku'] and
                   all(Decimal(current[key].replace(',',''))==Decimal(row[key]) for key in ('stock','price')))
        except (InvalidOperation,KeyError,AttributeError): equal=False
        if not equal: raise ValueError('TikTok did not retain every variation SKU, stock and price. Review the browser form.')
