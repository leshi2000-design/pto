"""Цена материала справочника: закупка + НДС + надбавка = цена продажи. Без зависимости от Qt.

НДС считается от закупки, если стоит галочка. Надбавка (руб) либо вычисляется по введённой цене продажи («auto»), либо вводится вручную, и тогда цена продажи рассчитывается («manual»).
Надбавка в процентах — от закупочной цены."""
from decimal import ROUND_HALF_UP, Decimal

MODES = {'auto': 'Надбавка вычисляется автоматически (по цене продажи)', 'manual': 'Надбавка вводится вручную (цена продажи рассчитывается)'}


def D(value):
    return Decimal(str(value if value not in (None, '') else 0))


def q2(value):
    return D(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def vat_amount(purchase, vat_on, rate):
    return q2(D(purchase) * D(rate) / 100) if vat_on else Decimal('0.00')


def calc(purchase, vat_on=False, rate=20, mode='auto', price=None, markup=None):
    """{'vat','markup','markup_pct','price'}: auto — надбавка = продажа − закупка − НДС; manual — продажа = закупка + НДС + надбавка."""
    if mode not in MODES:
        raise ValueError('Неизвестный способ расчёта надбавки')
    purchase = q2(purchase)
    vat = vat_amount(purchase, vat_on, rate)
    if mode == 'auto':
        price = q2(price)
        markup = price - purchase - vat
    else:
        markup = q2(markup)
        price = purchase + vat + markup
    pct = (markup / purchase * 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if purchase else Decimal('0.00')
    return dict(vat=vat, markup=markup, markup_pct=pct, price=price)


def validate(item_type, purchase, price):
    """Для материала цена закупки и цена продажи обязательны (больше нуля); у работы цена задаётся формулой."""
    if item_type == 'Материал':
        if D(purchase) <= 0:
            raise ValueError('Для материала обязательна цена закупки (больше нуля).')
        if D(price) <= 0:
            raise ValueError('Для материала обязательна цена продажи (больше нуля).')


def markup_from_percent(purchase, percent):
    return q2(D(purchase) * D(percent) / 100)
