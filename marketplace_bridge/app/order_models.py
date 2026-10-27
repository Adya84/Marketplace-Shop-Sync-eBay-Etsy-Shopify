"""Strict, catalogue-independent order data. No customer data belongs in logs."""
from dataclasses import dataclass, field, asdict
from decimal import Decimal, InvalidOperation
import re


class OrderProblem(ValueError):
    pass

class SignInRequired(OrderProblem):
    pass


def money(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount != amount.quantize(Decimal('.01')):
            raise InvalidOperation
        return amount
    except (InvalidOperation, ValueError, TypeError):
        raise OrderProblem('Invalid source money amount') from None


@dataclass
class SourceOrder:
    shop_id: str
    order_id: str
    status: str
    currency: str
    total: str
    shipping: str
    address: dict
    items: list[dict]
    seller_fulfilled: bool
    tracking: list[dict] = field(default_factory=list)
    tax: str = '0.00'
    delivery_instructions: str = ''
    email: str = ''

    @property
    def amount(self):
        return money(self.total)

    def validate_identity(self):
        if not re.fullmatch(r'\d{10,30}', self.order_id) or not re.fullmatch(r'\d{5,30}', self.shop_id):
            raise OrderProblem('Missing or invalid source shop/order identifier')

    def validate(self):
        self.validate_identity()
        if self.status not in {'Awaiting packing', 'Awaiting shipment'} or not self.seller_fulfilled:
            raise OrderProblem('Order is not seller-fulfilled and ready to ship')
        if self.tracking:
            raise OrderProblem('TikTok already has tracking; review before creating another shipment')
        if self.currency != 'GBP':
            raise OrderProblem('Only verified UK GBP orders are supported')
        if self.email and (not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',self.email) or any(c in self.email for c in '*•…')):
            raise OrderProblem('Customer email is masked or invalid; review before linking a customer')
        for key in ('firstName', 'address1', 'city', 'zip', 'countryCode'):
            value = str(self.address.get(key) or '').strip()
            if not value or any(c in value for c in ('*','•','…')):
                raise OrderProblem('Delivery address is incomplete or masked')
        if self.address['countryCode'] != 'GB' or not re.fullmatch(
            r'(?:GIR\s?0AA|[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2})', self.address['zip'].upper()):
            raise OrderProblem('Delivery postcode/country requires review')
        if not self.items:
            raise OrderProblem('No order items were found')
        subtotal = Decimal('0.00')
        for item in self.items:
            qty=item.get('quantity')
            if type(qty) is not int or qty < 1 or not str(item.get('title') or '').strip():
                raise OrderProblem('Invalid item name or quantity')
            weight=item.get('weight_grams')
            if type(weight) is not int or not 1 <= weight <= 100000:
                raise OrderProblem('Item weight is missing; enter its actual weight for labels')
            subtotal += money(item.get('unit_price')) * qty
        if subtotal + money(self.shipping) + money(self.tax) != self.amount:
            raise OrderProblem('Source item, shipping and tax amounts do not equal the paid total')

    def payload(self):
        return asdict(self)
