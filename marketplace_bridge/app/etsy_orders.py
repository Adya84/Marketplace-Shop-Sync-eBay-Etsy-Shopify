"""Read-only Etsy receipts. No browser session or tracking writes."""
from decimal import Decimal
from html import unescape
from .order_models import SourceOrder, OrderProblem, money


def etsy_money(value):
    if not isinstance(value,dict) or value.get('currency_code')!='GBP':
        raise OrderProblem('Etsy money/currency needs review; only GBP is supported')
    amount=value.get('amount'); divisor=value.get('divisor')
    if type(amount) is not int or type(divisor) is not int or divisor<=0:
        raise OrderProblem('Invalid Etsy money amount')
    return money(Decimal(amount)/Decimal(divisor))


def parse_receipt(receipt,shop_id,weights):
    if receipt.get('is_paid') is not True or receipt.get('is_shipped') is not False:
        raise OrderProblem('Etsy order is not paid and unshipped')
    if str(receipt.get('status','')).lower() in {'canceled','cancelled','refunded','fully_refunded'} or receipt.get('refunds') or receipt.get('shipments'):
        raise OrderProblem('Etsy cancellation, refund or existing shipment requires review')
    name=unescape(str(receipt.get('name') or '')).strip().split(maxsplit=1)
    if not name: raise OrderProblem('Etsy shipping recipient is missing')
    items=[]
    for transaction in receipt.get('transactions') or []:
        if transaction.get('is_digital') is not False:
            raise OrderProblem('Etsy item is digital or its physical status is unverified')
        key=f"{transaction.get('listing_id')}:{transaction.get('product_id')}"
        options='; '.join(unescape(str(v.get('formatted_name') or 'Option'))+': '+unescape(str(v.get('formatted_value') or '')) for v in transaction.get('variations') or [])
        items.append(dict(title=unescape(str(transaction.get('title') or '')),variant=options,
            sku=str(transaction.get('sku') or key),quantity=transaction.get('quantity'),
            unit_price=str(etsy_money(transaction.get('price'))),weight_grams=weights.get(key),weight_key=key))
    tax=Decimal('0')
    for field in ('total_tax_cost','total_vat_cost'):
        if receipt.get(field) is not None: tax+=etsy_money(receipt[field])
    if tax: raise OrderProblem('Etsy tax/VAT requires review before import')
    return SourceOrder(shop_id=str(shop_id),order_id=str(receipt.get('receipt_id') or ''),marketplace='Etsy',
        status='Awaiting shipment',currency='GBP',total=str(etsy_money(receipt.get('grandtotal'))),
        shipping=str(etsy_money(receipt.get('total_shipping_cost'))),tax='0.00',seller_fulfilled=True,
        address=dict(firstName=name[0],lastName=name[1] if len(name)>1 else '',
            address1=unescape(str(receipt.get('first_line') or '')),address2=unescape(str(receipt.get('second_line') or '')),
            city=unescape(str(receipt.get('city') or '')),province=unescape(str(receipt.get('state') or '')),
            countryCode=str(receipt.get('country_iso') or ''),zip=str(receipt.get('zip') or '')),
        items=items,delivery_instructions=unescape(str(receipt.get('message_from_buyer') or '')))


async def list_receipts(client):
    rows=[]; seen=set();offset=0
    while True:
        payload=await client._get(f'/v3/application/shops/{client.shop_id}/receipts',
            {'limit':100,'offset':offset,'was_paid':'true','was_shipped':'false'})
        page=payload.get('results')
        if not isinstance(page,list): raise OrderProblem('Etsy receipt response is invalid')
        for row in page:
            identity=str(row.get('receipt_id') or '')
            if not identity.isdigit() or identity in seen: raise OrderProblem('Etsy receipt pagination changed; retry scan')
            seen.add(identity)
            # Older OAuth brokers may return receipt history despite query filters.
            # Filter before fetching details or asking for item weights.
            if (row.get('is_paid') is True and row.get('is_shipped') is False
                    and not row.get('shipments') and not row.get('refunds')
                    and str(row.get('status','')).lower() not in
                    {'completed','shipped','canceled','cancelled','refunded','fully_refunded'}):
                rows.append(row)
        offset+=len(page)
        if offset>=int(payload.get('count',offset)): return rows
        if not page: raise OrderProblem('Etsy receipt pagination was incomplete')
