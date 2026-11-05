"""توليد قائمة أسعار العميل من فواتيره السابقة.

الأسعار الخاصة كانت بتتكتب بالإيد في كل بند فاتورة. الموديول ده بيقرا فواتير
العميل **المرحّلة** ويستخرج منها سعر القطعة اللي اتباع بيه فعلاً لكل مقاس،
وآخر سعر هو اللي يسود (أحدث فاتورة بالتاريخ ثم بالرقم).

الفواتير الملغاة أو المسودة بتتجاهل، وكذلك البنود اللي سعرها صفر أو اللي
وحدة بيعها مش معروف عدد قطعها (كرتونة من غير عدد).

السعر بيتخزّن **للقطعة** عشان يساوي أساس `ItemVariant.selling_price`:
    سعر القطعة = سعر الوحدة في الفاتورة ÷ عدد القطع في الوحدة
"""
from decimal import Decimal

from .models import CustomerPrice, SalesInvoiceLine


def derive_prices_from_invoices(customer):
    """بيرجّع {variant_id: (سعر القطعة, رقم الفاتورة, تاريخها)} من الفواتير المرحّلة."""
    lines = (SalesInvoiceLine.objects
             .filter(invoice__customer=customer, invoice__status='POSTED',
                     variant__isnull=False)
             .select_related('invoice', 'variant', 'variant__item',
                             'variant__item__product')
             .order_by('invoice__date', 'invoice__invoice_no', 'id'))

    out = {}
    invoices = set()
    for ln in lines:
        invoices.add(ln.invoice_id)
        price = Decimal(ln.unit_price or 0)
        if price <= 0:
            continue
        factor = ln.unit_factor          # قطعة = 1، وحدة الجملة = عدد القطع فيها
        if factor <= 0:
            continue
        piece = (price / factor).quantize(Decimal('0.01'))
        if piece <= 0:
            continue
        # آخر فاتورة هي اللي تسود — الترتيب تصاعدي فالكتابة الأخيرة هي الأحدث.
        out[ln.variant_id] = (piece, ln.invoice.invoice_no, ln.invoice.date)
    return out, len(invoices)


def build_price_list_from_invoices(customer, skip_equal_to_catalog=True,
                                   overwrite=True):
    """يعبّي/يحدّث جدول أسعار العميل من فواتيره المرحّلة.

    skip_equal_to_catalog: لو السعر المستخرج = سعر الكتالوج، مفيش داعي لصف
        خاص (الكتالوج هيطلع نفس الرقم) — فبنتجاهله عشان الجدول يفضل معبّر.
    overwrite: يحدّث الأسعار الموجودة بالسعر المستخرج من أحدث فاتورة.

    بيرجّع dict فيه: created / updated / unchanged / skipped_same / invoices.
    """
    from inventory.models import ItemVariant

    derived, invoice_count = derive_prices_from_invoices(customer)
    if not derived:
        return {'created': 0, 'updated': 0, 'unchanged': 0, 'skipped_same': 0,
                'invoices': invoice_count}

    catalog = dict(ItemVariant.objects.filter(pk__in=derived)
                   .values_list('pk', 'selling_price'))
    existing = {cp.variant_id: cp for cp in
                CustomerPrice.objects.filter(customer=customer,
                                             variant_id__in=derived)}

    created = updated = unchanged = skipped_same = 0
    to_create = []
    for vid, (piece, inv_no, inv_date) in derived.items():
        std = Decimal(catalog.get(vid) or 0)
        note = f'من فاتورة {inv_no} ({inv_date})'
        cp = existing.get(vid)
        if skip_equal_to_catalog and piece == std and cp is None:
            skipped_same += 1
            continue
        if cp is None:
            to_create.append(CustomerPrice(customer=customer, variant_id=vid,
                                           piece_price=piece, notes=note))
            created += 1
        elif overwrite and Decimal(cp.piece_price) != piece:
            cp.piece_price = piece
            cp.notes = note
            cp.active = True
            cp.save(update_fields=['piece_price', 'notes', 'active', 'updated_at'])
            updated += 1
        else:
            unchanged += 1

    if to_create:
        CustomerPrice.objects.bulk_create(to_create, batch_size=500)

    return {'created': created, 'updated': updated, 'unchanged': unchanged,
            'skipped_same': skipped_same, 'invoices': invoice_count}
