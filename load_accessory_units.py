"""One-time loader: set accessory purchase-unit conversion fields + opening balances.

Run:  python manage.py shell -c "exec(open('load_accessory_units.py', encoding='utf-8').read())"

Idempotent: re-running re-sets the master fields and rebuilds the opening JE.
Quantities below are in the PURCHASE unit; the opening posting receives the
already-converted CONSUMPTION qty + cost (qty_purchase × factor, price ÷ factor).
"""
from decimal import Decimal
from manufacturing.models import Accessory
from core.opening import post_accessories_opening

# name_ar -> (purchase_unit, consumption_unit, units_per_purchase, note,
#             price_per_purchase_unit, qty_in_purchase_unit)
DATA = {
    'ورق طباعة':            ('متر',  'متر',  Decimal('1'),        '',                  Decimal('30'),     Decimal('40000')),
    'ورق حماية للطباعة':    ('كيلو', 'متر',  Decimal('10'),       'وزن المتر 100 جرام', Decimal('25'),     Decimal('1700')),
    'كيس عادى':             ('كيلو', 'قطعة', Decimal('166.6667'), 'وزن القطعة 6 جرام',  Decimal('133.3333'), Decimal('36')),
    'استيك':                ('كيلو', 'متر',  Decimal('25'),       'وزن المتر 40 جرام',  Decimal('150'),    Decimal('182')),
    'كردون':                ('كيلو', 'قطعة', Decimal('166.6667'), 'وزن القطعة 6 جرام',  Decimal('333.3333'), Decimal('79')),
    'تيكيت مطبوع':          ('قطعة', 'قطعة', Decimal('1'),        '',                  Decimal('1'),      Decimal('28500')),
    'حشو بطانة':            ('متر',  'متر',  Decimal('1'),        '',                  Decimal('2'),      Decimal('0')),
    'تطريز':                ('قطعة', 'قطعة', Decimal('1'),        '',                  Decimal('3'),      Decimal('0')),
    'سوسته كبيرة':          ('قطعة', 'قطعة', Decimal('1'),        '',                  Decimal('10'),     Decimal('0')),
    'سوسته صغيرة':          ('قطعة', 'قطعة', Decimal('1'),        '',                  Decimal('1.5'),    Decimal('0')),
    'كيس كبير':             ('كيلو', 'قطعة', Decimal('142.8571'), 'وزن القطعة 7 جرام',  Decimal('714.2857'), Decimal('10')),
    'ورقة تطبيق':           ('كيلو', 'قطعة', Decimal('66.6667'),  'وزن القطعة 15 جرام', Decimal('66.6667'), Decimal('125')),
}

rows = []          # (Accessory, qty_consumption, cost_consumption) for opening
missing = []
for name, (pu, cu, factor, note, price_p, qty_p) in DATA.items():
    a = Accessory.objects.filter(name_ar=name).first()
    if not a:
        missing.append(name)
        continue
    a.purchase_unit = pu
    a.unit = cu
    a.units_per_purchase = factor
    a.conversion_note = note
    a.default_unit_cost = price_p
    a.save(update_fields=['purchase_unit', 'unit', 'units_per_purchase',
                          'conversion_note', 'default_unit_cost'])
    # convert purchase-unit qty/price -> consumption-unit qty/cost
    qty_c = qty_p * factor
    cost_c = (price_p / factor) if factor else price_p
    rows.append((a, qty_c, cost_c))

if missing:
    print('!! MISSING accessories (skipped):', '، '.join(missing))

je = post_accessories_opening(rows)
print('Opening JE:', je.reference if je else None)
total = sum((q * c) for _, q, c in rows)
print('Expected opening value =', total.quantize(Decimal('0.01')))

# echo back what was stored
for a in Accessory.objects.order_by('code'):
    print(a.code, a.name_ar, '| buy', a.purchase_unit, '| use', a.unit,
          '| factor', a.units_per_purchase, '| stock', a.current_stock,
          '| avg', a.average_cost)
