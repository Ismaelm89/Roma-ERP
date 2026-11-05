"""توليد قائمة أسعار عميل من فواتيره المرحّلة.

    python manage.py build_customer_prices C0017
    python manage.py build_customer_prices C0017 --dry-run
    python manage.py build_customer_prices --all
"""
from django.core.management.base import BaseCommand, CommandError

from sales.models import Customer
from sales.pricing import build_price_list_from_invoices, derive_prices_from_invoices


class Command(BaseCommand):
    help = 'يعبّي جدول أسعار العميل الخاصة من فواتيره المرحّلة السابقة.'

    def add_arguments(self, parser):
        parser.add_argument('codes', nargs='*', help='أكواد العملاء (C0017 ...)')
        parser.add_argument('--all', action='store_true',
                            help='كل العملاء النشطين')
        parser.add_argument('--dry-run', action='store_true',
                            help='اعرض بس من غير حفظ')
        parser.add_argument('--include-same', action='store_true',
                            help='خزّن كمان الأسعار المساوية لسعر الكتالوج')

    def handle(self, *args, **o):
        if o['all']:
            customers = list(Customer.objects.filter(active=True))
        else:
            if not o['codes']:
                raise CommandError('اكتب كود عميل أو استخدم --all')
            customers = list(Customer.objects.filter(code__in=o['codes']))
            missing = set(o['codes']) - {c.code for c in customers}
            if missing:
                raise CommandError(f'عملاء مش موجودين: {", ".join(sorted(missing))}')

        for cust in customers:
            if o['dry_run']:
                derived, inv_count = derive_prices_from_invoices(cust)
                if not derived:
                    continue
                self.stdout.write(f'\n{cust.code} {cust.name_ar} — '
                                  f'{len(derived)} مقاس من {inv_count} فاتورة:')
                for vid, (piece, inv_no, inv_date) in sorted(
                        derived.items(), key=lambda kv: kv[1][2], reverse=True)[:400]:
                    from inventory.models import ItemVariant
                    v = ItemVariant.objects.select_related('item').get(pk=vid)
                    std = v.selling_price
                    flag = '=' if piece == std else ('↓' if piece < std else '↑')
                    self.stdout.write(
                        f'  {v.item.code} {v.item.name_ar[:34]:<34} {v.size:<4} '
                        f'{piece:>9,.2f} {flag} كتالوج {std:>9,.2f}   ({inv_no})')
                continue

            res = build_price_list_from_invoices(
                cust, skip_equal_to_catalog=not o['include_same'])
            if res['created'] or res['updated']:
                self.stdout.write(self.style.SUCCESS(
                    f'{cust.code} {cust.name_ar}: جديد {res["created"]} · '
                    f'محدّث {res["updated"]} · زي ما هو {res["unchanged"]} · '
                    f'متجاهل (= الكتالوج) {res["skipped_same"]} · '
                    f'من {res["invoices"]} فاتورة'))
