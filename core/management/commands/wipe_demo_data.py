# -*- coding: utf-8 -*-
"""Wipe transactional/demo data so the system can start clean, while KEEPING
all configuration/master data (chart of accounts, sizes, colors, fabric types,
vendor types, cash accounts, expense categories, accessory catalog, company info).

Safe by design:
  * Dry-run by default — prints what WOULD be deleted and changes nothing.
  * Only deletes when called with --confirm.
  * Runs inside a single transaction; any error rolls everything back.

Usage:
    python manage.py wipe_demo_data            # dry-run (counts only)
    python manage.py wipe_demo_data --confirm  # actually delete
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from sales.models import (Customer, SalesInvoice, SalesInvoiceLine, Receipt,
                          ReceiptAllocation, SalesReturn, SalesReturnLine)
from inventory.models import Product, Item, ItemVariant, StockMovement
from manufacturing.models import (Supplier, ProductionOrder, FabricBatch,
                                  FabricMovement, SupplierPayment,
                                  AccessoryPurchase, Accessory,
                                  ManufacturingWagePayment)
from core.models import JournalEntry, ExpenseVoucher, FixedAsset


class Command(BaseCommand):
    help = 'Wipe transactional/demo data; keep configuration. Dry-run unless --confirm.'

    def add_arguments(self, parser):
        parser.add_argument('--confirm', action='store_true',
                            help='Actually perform the deletion (otherwise dry-run).')

    def handle(self, *args, **options):
        confirm = options['confirm']

        # Deletion order: children / referencing rows first, then parents.
        # Each entry: (label, queryset). Deleting a parent will cascade its
        # own child rows (invoice lines, allocations, production inlines, ...).
        steps = [
            ('تخصيصات سندات القبض', ReceiptAllocation.objects.all()),
            ('سندات القبض', Receipt.objects.all()),
            ('بنود مرتجعات المبيعات', SalesReturnLine.objects.all()),
            ('مرتجعات المبيعات', SalesReturn.objects.all()),
            ('بنود فواتير المبيعات', SalesInvoiceLine.objects.all()),
            ('فواتير المبيعات', SalesInvoice.objects.all()),
            ('حركات المخزون', StockMovement.objects.all()),
            ('أوامر الإنتاج (مع بنودها)', ProductionOrder.objects.all()),
            ('حركات القماش', FabricMovement.objects.all()),
            ('مشتريات/دفعات القماش', FabricBatch.objects.all()),
            ('سندات دفع الموردين', SupplierPayment.objects.all()),
            ('سندات صرف المصنعيات', ManufacturingWagePayment.objects.all()),
            ('مشتريات الإكسسوارات', AccessoryPurchase.objects.all()),
            ('سندات صرف المصروفات', ExpenseVoucher.objects.all()),
            ('الأصول الثابتة', FixedAsset.objects.all()),
            # Journal entries (cascade their lines) must go BEFORE suppliers /
            # customers / items, because JournalLine has PROTECT FKs to them.
            ('القيود المحاسبية (مع بنودها)', JournalEntry.objects.all()),
            ('الموردين', Supplier.objects.all()),
            ('العملاء', Customer.objects.all()),
            ('مقاسات المنتجات (SKUs)', ItemVariant.objects.all()),
            ('المنتجات الفرعية', Item.objects.all()),
            # Parent products + their size recipes (CASCADE) must go AFTER the
            # sub-products, because Item.product is PROTECT.
            ('المنتجات الرئيسية (مع الوصفات)', Product.objects.all()),
        ]

        self.stdout.write('=== خطة المسح ===')
        total = 0
        for label, qs in steps:
            n = qs.count()
            total += n
            self.stdout.write(f'  {label}: {n}')
        self.stdout.write(f'  --- إجمالي السجلات المتأثرة (تقريبي، قبل الكاسكيد): {total}')

        kept = [
            'دليل الحسابات (Account)', 'المقاسات (Size)', 'ألوان القماش (FabricColor)',
            'أنواع القماش (FabricType)', 'أنواع الموردين (VendorType)',
            'حسابات النقدية/البنوك/المحافظ (CashAccount)',
            'بنود المصروفات (ExpenseCategory)', 'كتالوج الإكسسوارات (Accessory)',
            'بيانات الشركة (Company)',
        ]
        self.stdout.write('\n=== هيتساب زي ما هو (إعدادات) ===')
        for k in kept:
            self.stdout.write(f'  ✓ {k}')

        if not confirm:
            self.stdout.write(self.style.WARNING(
                '\n[تجربة فقط] مفيش حاجة اتمسحت. شغّل الأمر بـ --confirm عشان المسح الفعلي.'))
            return

        with transaction.atomic():
            for label, qs in steps:
                deleted, _ = qs.delete()
                self.stdout.write(f'  حُذف {label}: {deleted}')
            # Reset the kept accessory catalog stock/cost so it starts clean.
            for acc in Accessory.objects.all():
                changed = False
                if hasattr(acc, 'current_stock') and acc.current_stock:
                    acc.current_stock = 0
                    changed = True
                if hasattr(acc, 'average_cost') and acc.average_cost:
                    acc.average_cost = 0
                    changed = True
                if changed:
                    acc.save()

        self.stdout.write(self.style.SUCCESS(
            '\n✅ تم المسح. النظام بقى نضيف والإعدادات اتحافظ عليها.'))
