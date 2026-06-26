"""Roma Manufacturing — Phase 1: Fabric inventory + dyeing workflow.

Concepts:
  - FabricBatch  = one purchase lot of a specific fabric type from a supplier.
                   Has a current quantity (kg) and a cost-per-kg that grows
                   as dye costs are added to it.
  - DyeOrder     = sending part (or all) of a batch to an external dyer,
                   then receiving it back with a (possibly smaller) weight
                   and a dye cost.  The dye cost is added to the batch's
                   total value; the (now-smaller) weight raises cost/kg.
  - FabricMovement = append-only log of every kg-level change to a batch.

Out of scope for Phase 1 (will come later): accessories (elastic, buttons),
production orders, BOM, work stations, payroll allocation.
"""
from decimal import Decimal

from django.conf import settings
from django.db import models


# ============================================================
#  Unified vendor master (replaces FabricSupplier + FabricDyer)
# ============================================================

class VendorType(models.Model):
    """نوع المورد (مورد قماش / مصبغة / إكسسوارات / مكن / ... قابل للزيادة).
    Seeded by data migration with 4 defaults. User can add more freely.
    """
    code = models.CharField('كود النوع', max_length=20, unique=True)
    name_ar = models.CharField('اسم النوع', max_length=100, unique=True)
    sort_order = models.PositiveSmallIntegerField('ترتيب العرض', default=99)
    active = models.BooleanField('نشط', default=True)

    class Meta:
        verbose_name = 'نوع مورد'
        verbose_name_plural = 'أنواع الموردين'
        ordering = ['sort_order', 'name_ar']

    def __str__(self):
        return self.name_ar


def _ap_balance_for_vendor(vendor):
    """Live AP balance using the unified `supplier` FK on JournalLine."""
    from decimal import Decimal as D
    from django.db.models import Sum
    from core.account_codes import SYSTEM_ACCOUNTS
    from core.models import JournalLine
    agg = (JournalLine.objects
           .filter(supplier=vendor,
                   account__code=SYSTEM_ACCOUNTS['AP'],
                   entry__status='POSTED')
           .aggregate(d=Sum('debit'), c=Sum('credit')))
    return (agg['c'] or D('0')) - (agg['d'] or D('0'))


class Supplier(models.Model):
    """مورد موحّد — يخدم كل أنواع الموردين (قماش، مصبغة، إكسسوارات، مكن، ...).
    vendor_type لازم يتحدد عند الإنشاء — هو اللي بيفرّق بين الأنواع.
    """
    code = models.CharField('كود المورد', max_length=20, unique=True, blank=True,
                            help_text='سيب الخانة فاضية وهيتولّد تلقائياً (SUP-0001 ...)')
    name = models.CharField('اسم المورد', max_length=200)
    vendor_type = models.ForeignKey(VendorType, on_delete=models.PROTECT,
                                     related_name='suppliers',
                                     verbose_name='نوع المورد')
    phone = models.CharField('الهاتف', max_length=50, blank=True)
    address = models.CharField('العنوان', max_length=500, blank=True)
    tax_id = models.CharField('الرقم الضريبي', max_length=50, blank=True)
    notes = models.TextField('ملاحظات', blank=True)
    active = models.BooleanField('نشط', default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'مورد'
        verbose_name_plural = 'الموردين'
        ordering = ['vendor_type__sort_order', 'code']
        indexes = [models.Index(fields=['vendor_type', 'active'])]

    def __str__(self):
        return f'{self.code} - {self.name} ({self.vendor_type.name_ar})'

    def save(self, *args, **kwargs):
        from core.serials import assign_if_blank
        assign_if_blank(self, 'code', 'SUP-', 4)
        super().save(*args, **kwargs)

    @property
    def current_balance(self):
        """رصيد حالي = موجب يعني إحنا بنديّن للمورد، سالب يعني دفعنا زيادة."""
        return _ap_balance_for_vendor(self)


# Legacy FabricSupplier and FabricDyer models removed — replaced by unified Supplier.
# Migration 0005 drops the underlying tables.


class FabricType(models.Model):
    """نوع قماش (Cotton 100%, Polyester, Silk ...). كاتالوج."""
    code = models.CharField('كود النوع', max_length=20, unique=True, blank=True,
                            help_text='سيب الخانة فاضية وهيتولّد تلقائياً (FAB-001 ...)')
    name_ar = models.CharField('الاسم', max_length=200,
                                help_text='يقبل عربي أو إنجليزي')
    name_en = models.CharField('Name (English)', max_length=200, blank=True)
    description = models.TextField('الوصف', blank=True)
    active = models.BooleanField('نشط', default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'نوع قماش'
        verbose_name_plural = 'أنواع القماش'
        ordering = ['code']

    def __str__(self):
        return f'{self.code} - {self.name_ar}'

    def save(self, *args, **kwargs):
        from core.serials import assign_if_blank
        assign_if_blank(self, 'code', 'FAB-', 3)
        super().save(*args, **kwargs)


class FabricColor(models.Model):
    """لون قماش (White, Red, Navy ... + flag للخام)."""
    code = models.CharField('كود اللون', max_length=20, unique=True, blank=True,
                            help_text='سيب الخانة فاضية وهيتولّد تلقائياً (CLR-001 ...)')
    name_ar = models.CharField('اسم اللون', max_length=100,
                                help_text='يقبل عربي أو إنجليزي')
    name_en = models.CharField('Name (English)', max_length=100, blank=True)
    is_raw = models.BooleanField('خام (غير متصبّغ)', default=False,
                                  help_text='اختار ده للقماش لما يكون خام مش متصبّغ')
    hex_code = models.CharField('كود HEX', max_length=7, blank=True,
                                 help_text='مثال: #FF0000')
    rgb = models.CharField('RGB', max_length=20, blank=True,
                            help_text='مثال: 255,0,0')
    hsl = models.CharField('HSL', max_length=20, blank=True,
                            help_text='مثال: 0,100%,50%')
    active = models.BooleanField('نشط', default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'لون قماش'
        verbose_name_plural = 'ألوان القماش'
        ordering = ['-is_raw', 'name_ar']

    def __str__(self):
        suffix = ' (خام)' if self.is_raw else ''
        return f'{self.name_ar}{suffix}'

    def save(self, *args, **kwargs):
        from core.serials import assign_if_blank
        assign_if_blank(self, 'code', 'CLR-', 3)
        super().save(*args, **kwargs)


# ============================================================
#  Core inventory: batch + movements + dye orders
# ============================================================

class FabricPurchaseInvoice(models.Model):
    """فاتورة شراء قماش متعددة البنود — هيدر واحد (مورد + رقم + تاريخ + طريقة سداد)
    وتحته كذا بند (FabricBatch واحد لكل نوع/لون/كمية).

    الترحيل بيعمل قيد محاسبي **واحد** للفاتورة كلها:
        DR  مخزون الأقمشة (1330000)   إجمالي البنود
        CR  نقدية / بنك / مورد آجل     إجمالي البنود
    وكل بند بياخد حركة استلام (PURCHASE_IN) ورصيده بيتزود — زي الشراء المفرد بالظبط.
    """
    PAYMENT_CHOICES = [
        ('CASH', 'كاش'),
        ('BANK', 'تحويل بنكي'),
        ('CREDIT', 'آجل (للمورد)'),
    ]

    invoice_no = models.CharField('رقم الفاتورة', max_length=30, unique=True, blank=True,
                                  help_text='سيب الخانة فاضية وهيتولّد تلقائياً (FPI-0001 ...)')
    supplier = models.ForeignKey('Supplier', null=True, blank=True, on_delete=models.PROTECT,
                                 related_name='fabric_invoices', verbose_name='المورد',
                                 limit_choices_to={'vendor_type__code': 'FABRIC_SUPPLIER'},
                                 help_text='إجباري لو الفاتورة آجلة. سيبه فاضي لو كاش/بنك.')
    supplier_ref = models.CharField('رقم فاتورة المورد', max_length=50, blank=True,
                                    help_text='رقم الفاتورة الورقية اللي جايه من المورد (اختياري)')
    date = models.DateField('تاريخ الفاتورة')
    payment_method = models.CharField('طريقة السداد', max_length=10,
                                      choices=PAYMENT_CHOICES, default='CREDIT')
    cash_account = models.ForeignKey('core.CashAccount', null=True, blank=True,
                                     on_delete=models.PROTECT, related_name='fabric_invoices',
                                     verbose_name='مدفوع من (لو كاش/بنك)',
                                     help_text='اختار الخزينة/البنك/المحفظة لو السداد مش آجل')
    is_posted = models.BooleanField('مرحّلة محاسبياً', default=False, editable=False)
    journal_entry = models.ForeignKey('core.JournalEntry', null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name='+', editable=False)
    notes = models.TextField('ملاحظات', blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'فاتورة شراء قماش'
        verbose_name_plural = 'فواتير شراء القماش'
        ordering = ['-date', '-id']

    def __str__(self):
        return f'{self.invoice_no} — {self.supplier.name if self.supplier_id else "كاش"}'

    def save(self, *args, **kwargs):
        from core.serials import assign_if_blank
        assign_if_blank(self, 'invoice_no', 'FPI-', 4)
        super().save(*args, **kwargs)

    @property
    def total(self):
        """إجمالي الفاتورة = مجموع (كمية × سعر) لكل البنود."""
        return sum((b.purchase_total for b in self.lines.all()),
                   Decimal('0')).quantize(Decimal('0.01'))

    @property
    def line_count(self):
        return self.lines.count()


class FabricBatch(models.Model):
    """دفعة قماش — الـ "lot" المخزني.

    الـ flow الكامل:
      1) شراء دفعة (PURCHASE_IN) → in_stock_qty_kg = qty
      2) (اختياري) إرسال للمصبغة (SEND_TO_DYER) → in_stock يقل، at_dyer يزيد
      3) استلام من المصبغة (RECEIVE_FROM_DYER) → at_dyer يقل، in_stock يزيد
         (مع فاقد التصبيغ: الرجوع قد يكون أقل من الإرسال)
         تكلفة التصبيغ تنضاف لـ total_dye_cost → cost_per_kg يرتفع
      4) صرف للإنتاج (ISSUE_TO_PRODUCTION) [Phase 2] → in_stock يقل

    Cost rollup:
      total_value = purchase_qty_kg × purchase_unit_cost + Σ(dye_cost)
      cost_per_kg = total_value ÷ remaining_qty_kg (in_stock + at_dyer)
    """
    PAYMENT_CHOICES = [
        ('CASH', 'كاش'),
        ('BANK', 'تحويل بنكي'),
        ('CREDIT', 'آجل (للمورد)'),
    ]

    batch_no = models.CharField('رقم الدفعة', max_length=30, unique=True, blank=True,
                                 help_text='سيب الخانة فاضية وهيتولّد تلقائياً (FB-0001 ...)')

    # لو الدفعة بند جوّه فاتورة متعددة البنود — المورد/التاريخ/السداد بييجوا من الفاتورة.
    invoice = models.ForeignKey('FabricPurchaseInvoice', null=True, blank=True,
                                on_delete=models.CASCADE, related_name='lines',
                                verbose_name='فاتورة الشراء',
                                help_text='يتساب فاضي للشراء المفرد')

    # Purchase info — supplier must be a Supplier whose vendor_type=FABRIC_SUPPLIER
    supplier = models.ForeignKey('Supplier', on_delete=models.PROTECT,
                                  null=True, blank=True,
                                  related_name='fabric_batches',
                                  verbose_name='المورد',
                                  limit_choices_to={'vendor_type__code': 'FABRIC_SUPPLIER'},
                                  help_text='اختار مورد من نوع "مورد قماش" (اختياري للأرصدة الافتتاحية)')
    fabric_type = models.ForeignKey(FabricType, on_delete=models.PROTECT,
                                     related_name='batches', verbose_name='نوع القماش')
    color = models.ForeignKey(FabricColor, on_delete=models.PROTECT,
                               related_name='batches', verbose_name='اللون الحالي',
                               help_text='اللون اللي القماش عليه دلوقتي (خام لو لسه ما اتصبّغش)')
    purchase_date = models.DateField('تاريخ الشراء')
    purchase_qty_kg = models.DecimalField('الكمية المشتراة (كيلو)', max_digits=12, decimal_places=3)
    purchase_unit_cost = models.DecimalField('سعر الكيلو من المورد', max_digits=12, decimal_places=4)
    purchase_payment_method = models.CharField('طريقة السداد', max_length=10,
                                                 choices=PAYMENT_CHOICES, default='CREDIT')

    # Cached running totals — kept in sync by services. Derived from movements.
    in_stock_qty_kg = models.DecimalField('الرصيد بالمخزن (كيلو)', max_digits=12, decimal_places=3,
                                            default=Decimal('0'))

    is_posted = models.BooleanField('مرحّلة محاسبياً', default=False, editable=False)
    purchase_journal_entry = models.ForeignKey('core.JournalEntry', null=True, blank=True,
                                                on_delete=models.SET_NULL, related_name='+',
                                                editable=False)
    notes = models.TextField('ملاحظات', blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'شراء قماش'
        verbose_name_plural = 'مشتريات القماش'
        ordering = ['-purchase_date', '-id']
        indexes = [
            models.Index(fields=['supplier', 'purchase_date']),
            models.Index(fields=['fabric_type', 'color']),
        ]

    def __str__(self):
        return f'{self.batch_no} - {self.fabric_type.name_ar} / {self.color.name_ar}'

    def save(self, *args, **kwargs):
        from core.serials import assign_if_blank
        assign_if_blank(self, 'batch_no', 'FB-', 4)
        super().save(*args, **kwargs)

    @property
    def purchase_total(self):
        """إجمالي فاتورة شراء القماش (قبل التصبيغ)."""
        qty = Decimal(self.purchase_qty_kg or 0)
        cost = Decimal(self.purchase_unit_cost or 0)
        return (qty * cost).quantize(Decimal('0.01'))

    @property
    def total_value(self):
        """القيمة الإجمالية للدفعة = شراء (مفيش تصبيغ في النموذج الحالي)."""
        return self.purchase_total

    @property
    def remaining_qty_kg(self):
        """الإجمالي المتبقي بالمخزن."""
        return Decimal(self.in_stock_qty_kg or 0)

    @property
    def consumed_qty_kg(self):
        """اللي اتصرف بره الدفعة (إنتاج + فاقد تصبيغ + إهدار)."""
        return Decimal(self.purchase_qty_kg or 0) - self.remaining_qty_kg

    @property
    def cost_per_kg(self):
        """تكلفة الكيلو الحالية — تنخفض لو ما فيش تصبيغ، وترتفع لو فيه تصبيغ أو فاقد."""
        rem = self.remaining_qty_kg
        if rem <= 0:
            return Decimal('0')
        return (self.total_value / rem).quantize(Decimal('0.0001'))


def fabric_available_kg(fabric_type, color=None):
    """إجمالي الكيلوهات المتاحة بالمخزن من نوع قماش/خامة معيّن (كل الدفعات).

    لو حدّدنا اللون، بنحسب المتاح من نفس اللون بس — لأن المخزون متخزّن باللون
    والخصم بيكون من دفعات نفس اللون اللي المنتج الفرعي بيستخدمه."""
    from django.db.models import Sum
    if not fabric_type:
        return Decimal('0')
    ft_id = getattr(fabric_type, 'pk', fabric_type)
    qs = FabricBatch.objects.filter(fabric_type_id=ft_id, in_stock_qty_kg__gt=0)
    if color is not None:
        qs = qs.filter(color_id=getattr(color, 'pk', color))
    agg = qs.aggregate(s=Sum('in_stock_qty_kg'))
    return Decimal(agg['s'] or 0)


def fabric_avg_cost(fabric_type, color=None):
    """متوسط مرجّح لسعر شراء الكيلو عبر دفعات نفس النوع المتاحة بالمخزن.

    ده هو تكلفة الـ average اللي الإنتاج بيتسعّر بيها — مش تكلفة دفعة بعينها.
    لو حدّدنا اللون، المتوسط بيتحسب من دفعات نفس اللون بس.
    """
    if not fabric_type:
        return Decimal('0')
    ft_id = getattr(fabric_type, 'pk', fabric_type)
    qs = FabricBatch.objects.filter(fabric_type_id=ft_id, in_stock_qty_kg__gt=0)
    if color is not None:
        qs = qs.filter(color_id=getattr(color, 'pk', color))
    tot_qty = Decimal('0')
    tot_val = Decimal('0')
    for b in qs:
        q = Decimal(b.in_stock_qty_kg or 0)
        tot_qty += q
        tot_val += q * Decimal(b.purchase_unit_cost or 0)
    if tot_qty <= 0:
        return Decimal('0')
    return (tot_val / tot_qty).quantize(Decimal('0.0001'))


# DyeOrder model removed — Roma buys finished (already-dyed) fabric directly.


class SupplierPayment(models.Model):
    """سند دفع لمورد قماش أو لمصبغة (واحد بس).

    Posting يعمل:
      DR AP (2110000) tagged with the supplier/dyer
      CR Cash / Bank
    وبكده رصيد المورد يقل بقيمة الدفعة.
    """
    METHOD_CHOICES = [
        ('CASH', 'كاش'),
        ('BANK', 'تحويل بنكي'),
        ('CHEQUE', 'شيك'),
    ]
    STATUS_CHOICES = [
        ('DRAFT', 'مسودة'),
        ('POSTED', 'مرحّل'),
        ('CANCELLED', 'ملغي'),
    ]

    payment_no = models.CharField('رقم السند', max_length=30, unique=True, blank=True,
                                   help_text='سيب الخانة فاضية وهيتولّد تلقائياً (SP-0001 ...)')
    date = models.DateField('التاريخ')
    supplier = models.ForeignKey('Supplier', on_delete=models.PROTECT, related_name='payments',
                                  verbose_name='المورد',
                                  help_text='اختار المورد اللي بتدفعله (من أي نوع)')
    method = models.CharField('طريقة الدفع', max_length=10, choices=METHOD_CHOICES, default='CASH')
    cash_account = models.ForeignKey('core.CashAccount', null=True, blank=True,
                                      on_delete=models.PROTECT, related_name='supplier_payments',
                                      verbose_name='النقدية/البنك/المحفظة',
                                      help_text='الحساب اللى دفعت منه. سيبه فاضي عشان يستخدم الحساب الافتراضي.')
    amount = models.DecimalField('المبلغ', max_digits=14, decimal_places=2)
    reference = models.CharField('المرجع (رقم شيك / حوالة)', max_length=100, blank=True)
    notes = models.TextField('ملاحظات', blank=True)
    status = models.CharField('الحالة', max_length=10, choices=STATUS_CHOICES, default='DRAFT')
    journal_entry = models.ForeignKey('core.JournalEntry', null=True, blank=True,
                                       on_delete=models.SET_NULL, related_name='+',
                                       editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'سند دفع لمورد'
        verbose_name_plural = 'سندات دفع للموردين'
        ordering = ['-date', '-id']

    def __str__(self):
        return f'{self.payment_no} → {self.supplier}'

    def save(self, *args, **kwargs):
        from core.serials import assign_if_blank
        assign_if_blank(self, 'payment_no', 'SP-', 4)
        super().save(*args, **kwargs)

    @property
    def party_label(self):
        if not self.supplier_id:
            return '—'
        return f'{self.supplier.vendor_type.name_ar}: {self.supplier.name}'


# ============================================================
#  Production orders (Phase 2a)
# ============================================================

class ProductionOrder(models.Model):
    """أمر إنتاج — لكل ورقة قص.

    الـ flow (مرحلتين):
      DRAFT = "خطة" (تجهيز الورقة وطباعتها للمشرفين — مفيش أي قيود)
            → COMPLETED = "تم الإنتاج" (زرار "انتج": خصم القماش بالفعلي +
              إضافة المنتج التام + كل القيود المحاسبية مرة واحدة)
            → CANCELLED
    RELEASED قديمة — متسابة للتوافق مع بيانات قديمة، مش مستخدمة في الـ flow الجديد.
    """
    STATUS_CHOICES = [
        ('DRAFT',     'خطة'),
        ('RELEASED',  'تم الإفراج (قديم)'),
        ('COMPLETED', 'تم الإنتاج'),
        ('CANCELLED', 'ملغي'),
    ]

    order_no = models.CharField('رقم أمر الإنتاج', max_length=30, unique=True, blank=True,
                                 help_text='سيب الخانة فاضية وهيتولّد تلقائياً (PO-0001 ...)')
    date = models.DateField('التاريخ')
    item = models.ForeignKey('inventory.Item', null=True, blank=True,
                              on_delete=models.PROTECT, related_name='production_orders',
                              verbose_name='الموديل (منتج فرعي)',
                              help_text='اختار المنتج الفرعي بتاع الأمر. الخامة (نوع القماش) '
                                        'بتيجي من المنتج الرئيسي، ولون القماش اللي هيتخصم من '
                                        'المخزن بييجي من المنتج الفرعي ده.')
    # اسم الأمر بييجي تلقائياً من اسم المنتج الفرعي — الخانة اليدوية اتشالت من الفورم.
    title = models.CharField('اسم/وصف الموديل', max_length=200, blank=True,
                              help_text='بيتعبّى تلقائياً باسم المنتج الفرعي.')
    customer = models.ForeignKey('sales.Customer', null=True, blank=True,
                                  on_delete=models.PROTECT, related_name='production_orders',
                                  verbose_name='العميل (اختياري)',
                                  help_text='لو الإنتاج لعميل معين بطلبية مخصصة')
    notes = models.TextField('ملاحظات', blank=True)

    status = models.CharField('الحالة', max_length=15, choices=STATUS_CHOICES, default='DRAFT')
    released_at = models.DateTimeField('تاريخ الإفراج', null=True, blank=True, editable=False)
    released_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name='released_orders',
                                     editable=False)
    completed_at = models.DateTimeField('تاريخ الإكمال', null=True, blank=True, editable=False)
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name='completed_orders',
                                      editable=False)
    released_journal_entry = models.ForeignKey('core.JournalEntry', null=True, blank=True,
                                                 on_delete=models.SET_NULL, related_name='+',
                                                 editable=False)
    completed_journal_entry = models.ForeignKey('core.JournalEntry', null=True, blank=True,
                                                  on_delete=models.SET_NULL, related_name='+',
                                                  editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name='created_orders')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'أمر إنتاج'
        verbose_name_plural = 'أوامر الإنتاج'
        ordering = ['-date', '-id']

    def __str__(self):
        return f'{self.order_no} — {self.title}'

    def save(self, *args, **kwargs):
        from core.serials import assign_if_blank
        assign_if_blank(self, 'order_no', 'PO-', 4)
        # اسم الأمر بييجي تلقائياً من اسم المنتج الفرعي — الخانة اليدوية اتشالت من الفورم.
        if self.item_id:
            self.title = self.item.name_ar
        super().save(*args, **kwargs)

    @property
    def total_pieces(self):
        """مجموع الكميات (لكل sub_model × مقاس). المخطط = الفعلي."""
        from django.db.models import Sum
        return self.sizes.aggregate(s=Sum('quantity'))['s'] or 0

    # Back-compat aliases for templates/services that referenced the old names.
    @property
    def total_planned_pieces(self):
        return self.total_pieces

    @property
    def total_actual_pieces(self):
        return self.total_pieces

    @property
    def total_planned_fabric_kg(self):
        """الكمية قبل الهالك. بعد الإنتاج = مجموع بنود الاستهلاك المتولّدة؛
        قبل الإنتاج = محسوبة من وصفة المنتج تلقائياً."""
        from django.db.models import Sum
        if self.fabric_usages.exists():
            agg = self.fabric_usages.aggregate(s=Sum('planned_qty_kg'))['s'] or Decimal('0')
            return Decimal(agg).quantize(Decimal('0.001'))
        return (self.recipe_planned_fabric_kg
                + self.recipe_planned_shorts_fabric_kg).quantize(Decimal('0.001'))

    @property
    def total_actual_fabric_kg(self):
        """الكمية المستخدمة بالهالك. بعد الإنتاج = المخصوم فعلياً؛
        قبل الإنتاج = من الوصفة + هالك المنتج تلقائياً."""
        from django.db.models import Sum
        if self.fabric_usages.exists():
            agg = self.fabric_usages.aggregate(s=Sum('actual_qty_kg'))['s'] or Decimal('0')
            return Decimal(agg).quantize(Decimal('0.001'))
        return (self.recipe_actual_fabric_kg
                + self.recipe_actual_shorts_fabric_kg).quantize(Decimal('0.001'))

    @property
    def total_fabric_value(self):
        """قيمة القماش = الكمية المستخدمة بالهالك × تكلفة الكيلو — التكلفة دايماً بالهالك.
        بعد الإنتاج: من snapshot كل بند (متوسط وقت الإنتاج) × الكمية الفعلية بالهالك.
        قبل الإنتاج: الكمية المتوقعة بالهالك × المتوسط المرجّح الحالي لسعر
        خامة المنتج — عشان القيمة تظهر صح في مرحلة الخطة (مش بصفر)."""
        p = self.main_product
        waste = Decimal(p.waste_pct or 0) if p else Decimal('0')
        factor = Decimal('1') + waste / Decimal('100')
        if self.fabric_usages.exists():
            total = Decimal('0')
            for u in self.fabric_usages.select_related('batch').all():
                # الكمية الفعلية بالهالك. لو بند قديم اتسجّل بالكمية قبل الهالك بس
                # (actual=0) نحسب تكلفته بالهالك = قبل الهالك × معامل هالك المنتج.
                qty = Decimal(u.actual_qty_kg or 0)
                if qty <= 0:
                    qty = Decimal(u.planned_qty_kg or 0) * factor
                cpk = Decimal(u.cost_per_kg_snapshot or 0)
                if cpk <= 0 and u.batch_id:
                    cpk = Decimal(u.batch.cost_per_kg or 0)
                total += qty * cpk
            return total.quantize(Decimal('0.01'))
        # مرحلة الخطة: قيمة متوقعة من الوصفة (بالهالك) × متوسط سعر خامة المنتج
        ft = p.fabric_type if (p and p.fabric_type_id) else None
        if not ft:
            return Decimal('0')
        return (self.recipe_actual_fabric_kg
                * fabric_avg_cost(ft, self.fabric_color)).quantize(Decimal('0.01'))

    @property
    def total_actual_accessory_cost(self):
        total = Decimal('0')
        for u in self.accessory_usages.all():
            total += u.total_cost
        return total.quantize(Decimal('0.01'))

    @property
    def total_cost(self):
        """إجمالي تكلفة الأمر (فعلي) = القماش + الإكسسوارات + المصنعية.
        المصنعية بتترسمل في تكلفة المنتج التام، ومقابلها استحقاق «مصنعيات مستحقة»
        في الميزانية (Phase C)."""
        return (self.total_fabric_value + self.total_actual_accessory_cost
                + self.recipe_labor_cost).quantize(Decimal('0.01'))

    @property
    def cost_per_piece(self):
        """تكلفة الوحدة الفعلية = إجمالي التكلفة ÷ الكميات الفعلية المنتجة."""
        pcs = self.total_actual_pieces
        if pcs <= 0:
            return Decimal('0')
        return (self.total_cost / Decimal(pcs)).quantize(Decimal('0.0001'))

    # ----- الوصفة (BOM): تغذية الأمر من وصفة المنتج الرئيسي لكل مقاس (Phase 3/B) -----
    @property
    def main_product(self):
        """المنتج الرئيسي اللي الأمر تابع له (من خلال الصنف/المنتج الفرعي).
        الوصفة (قماش/هالك/مصنعية/إكسسوارات) معرّفة على المنتج الرئيسي ده."""
        if self.item_id and self.item.product_id:
            return self.item.product
        return None

    def _recipe_by_size(self):
        """{size_id: ProductSizeRecipe} لوصفة المنتج الرئيسي (لو موجود)."""
        p = self.main_product
        if not p:
            return {}
        return {r.size_id: r for r in
                p.size_recipes.select_related('size').prefetch_related('accessories')}

    def _pieces_by_size(self):
        """{size_id: إجمالي القطع} مجمَّعة من بنود كميات المقاسات."""
        from django.db.models import Sum
        out = {}
        for row in self.sizes.values('size_id').annotate(q=Sum('quantity')):
            out[row['size_id']] = int(row['q'] or 0)
        return out

    @property
    def has_recipe(self):
        """هل المنتج الرئيسي له وصفة تطابق مقاس واحد على الأقل في الأمر؟"""
        recipes = self._recipe_by_size()
        return bool(recipes) and any(sid in recipes for sid in self._pieces_by_size())

    @property
    def recipe_planned_fabric_kg(self):
        """استهلاك القماش المخطط من الوصفة = Σ (كمية القماش للمقاس × عدد قطعه)."""
        recipes = self._recipe_by_size()
        total = Decimal('0')
        for sid, qty in self._pieces_by_size().items():
            r = recipes.get(sid)
            if r:
                total += Decimal(r.fabric_qty_kg or 0) * Decimal(qty)
        return total.quantize(Decimal('0.001'))

    @property
    def recipe_actual_fabric_kg(self):
        """الكمية المستخدمة بالهالك المتوقعة من الوصفة = الكمية قبل الهالك ×
        (1 + نسبة هالك المنتج). نسبة الهالك معرّفة على المنتج كله."""
        p = self.main_product
        waste = Decimal(p.waste_pct or 0) if p else Decimal('0')
        factor = Decimal('1') + waste / Decimal('100')
        return (self.recipe_planned_fabric_kg * factor).quantize(Decimal('0.001'))

    @property
    def recipe_planned_shorts_fabric_kg(self):
        """قماش الشورت المخطط (قبل الهالك) = Σ (قماش الشورت للمقاس × عدد قطعه). للأطقم بس."""
        recipes = self._recipe_by_size()
        total = Decimal('0')
        for sid, qty in self._pieces_by_size().items():
            r = recipes.get(sid)
            if r:
                total += Decimal(getattr(r, 'shorts_fabric_qty_kg', 0) or 0) * Decimal(qty)
        return total.quantize(Decimal('0.001'))

    @property
    def recipe_actual_shorts_fabric_kg(self):
        """قماش الشورت بالهالك = المخطط × (1 + نسبة هالك المنتج)."""
        p = self.main_product
        waste = Decimal(p.waste_pct or 0) if p else Decimal('0')
        factor = Decimal('1') + waste / Decimal('100')
        return (self.recipe_planned_shorts_fabric_kg * factor).quantize(Decimal('0.001'))

    @property
    def recipe_labor_cost(self):
        """إجمالي المصنعية من الوصفة = Σ (مصنعية المقاس × عدد القطع).
        بتترسمل في تكلفة المنتج التام عند الإنتاج (Phase C)."""
        recipes = self._recipe_by_size()
        total = Decimal('0')
        for sid, qty in self._pieces_by_size().items():
            r = recipes.get(sid)
            if r:
                total += Decimal(r.labor_cost or 0) * Decimal(qty)
        return total.quantize(Decimal('0.01'))

    def recipe_accessory_plan(self, with_waste=True):
        """{accessory_id: الكمية المخططة} من الوصفة.

        الأساس = مجموع (كمية الوصفة × قطع المقاس). مع with_waste=True (الافتراضي،
        المستخدَم في الاستهلاك الفعلي) بنطبّق نسبة هالك الإكسسوارات: الأساس × (1 + الهالك %).
        مع with_waste=False بنرجّع الكمية الخام (للعرض في ورقة الطباعة)."""
        recipes = self._recipe_by_size()
        base = {}
        for sid, qty in self._pieces_by_size().items():
            r = recipes.get(sid)
            if not r:
                continue
            for line in r.accessories.all():
                base[line.accessory_id] = (base.get(line.accessory_id, Decimal('0'))
                                           + Decimal(line.qty_per_piece or 0) * Decimal(qty))
        if not base or not with_waste:
            return base
        p = self.main_product
        factor = (Decimal('1')
                  + Decimal(getattr(p, 'accessory_waste_pct', 0) or 0) / Decimal('100'))
        return {acc_id: qty * factor for acc_id, qty in base.items()}

    @property
    def recipe_sizes_without_recipe(self):
        """أكواد مقاسات موجودة في الأمر ومالهاش وصفة على المنتج الرئيسي (للتنبيه)."""
        recipes = self._recipe_by_size()
        out = []
        for s in self.sizes.select_related('size').all():
            if s.quantity and s.size_id not in recipes and s.size.code not in out:
                out.append(s.size.code)
        return out

    @property
    def fabric_color(self):
        """لون القماش اللي هيتخصم من المخزن — بييجي من المنتج الفرعي (الصنف).

        المخزون متخزّن باللون، فالخصم بيكون من دفعات نفس اللون. لو المنتج الفرعي
        مالوش لون محدّد بنرجّع None والخصم بيتم من كل الألوان (توافق مع بيانات قديمة)."""
        if self.item_id and getattr(self.item, 'fabric_color_id', None):
            return self.item.fabric_color
        return None

    @property
    def shorts_fabric_color(self):
        """لون قماش الشورت — من المنتج الفرعي. None لو المنتج مش طقم بلونين."""
        if self.item_id and getattr(self.item, 'shorts_fabric_color_id', None):
            return self.item.shorts_fabric_color
        return None

    @staticmethod
    def _accessory_unit_cost(accessory):
        """تكلفة وحدة الإكسسوار للتسعير: متوسط التكلفة لو موجود وإلا السعر الافتراضي
        (نفس منطق AccessoryUsage.unit_cost عشان الأرقام تتطابق)."""
        if not accessory:
            return Decimal('0')
        avg = Decimal(getattr(accessory, 'average_cost', 0) or 0)
        return avg if avg > 0 else Decimal(getattr(accessory, 'default_unit_cost', 0) or 0)

    def recipe_cost_by_size(self):
        """تكلفة كل مقاس لوحده (قماش + إكسسوارات + مصنعية) — مش متوسط موحّد.

        بترجّع dict: {size_id: {size, code, qty, fabric_value, accessory, labor,
        total, unit}}. مجموع total على كل المقاسات = إجمالي تكلفة الأمر بالظبط،
        وكمان مجموع (unit × qty) = الإجمالي — يعني كل مقاس بتكلفته الحقيقية.

        الطريقة: بنوزّع إجمالي قيمة القماش وإجمالي الإكسسوارات على المقاسات حسب
        وزنها (كمية القماش × القطع، وتكلفة الإكسسوار × القطع)، والمصنعية لكل مقاس
        من وصفته مباشرة. أي فرق تقريب بيتحط على أكبر مقاس عشان المجموع يطابق
        الإجمالي بالظبط (سواء قبل الإنتاج من الوصفة، أو بعده من القيم الفعلية)."""
        recipes = self._recipe_by_size()
        pieces = self._pieces_by_size()

        total_fabric = self.total_fabric_value
        total_acc = self.total_actual_accessory_cost
        total_labor = self.recipe_labor_cost

        rows = {}
        fab_w_sum = Decimal('0')
        acc_w_sum = Decimal('0')
        for sid, qty in pieces.items():
            r = recipes.get(sid)
            if not r or qty <= 0:
                continue
            fab_w = Decimal(r.fabric_qty_kg or 0) * Decimal(qty)
            acc_w = Decimal('0')
            acc_waste = (Decimal('1')
                         + Decimal(getattr(self.main_product, 'accessory_waste_pct', 0) or 0)
                         / Decimal('100'))
            for line in r.accessories.all():
                acc_w += (Decimal(line.qty_per_piece or 0) * Decimal(qty) * acc_waste
                          * self._accessory_unit_cost(line.accessory))
            labor = (Decimal(r.labor_cost or 0) * Decimal(qty)).quantize(Decimal('0.01'))
            rows[sid] = {'size': r.size, 'code': r.size.code, 'qty': qty,
                         '_fab_w': fab_w, '_acc_w': acc_w, 'labor': labor}
            fab_w_sum += fab_w
            acc_w_sum += acc_w

        if not rows:
            return rows

        # وزّع القماش والإكسسوارات حسب الوزن (المصنعية محسوبة مباشرة).
        for row in rows.values():
            row['fabric_value'] = (total_fabric * row['_fab_w'] / fab_w_sum
                                   if fab_w_sum > 0 else Decimal('0'))
            row['accessory'] = (total_acc * row['_acc_w'] / acc_w_sum
                                if acc_w_sum > 0 else Decimal('0'))

        # وفّق كل مكوّن مع إجماليه بالظبط (فرق التقريب لأكبر مقاس).
        def _reconcile(key, target):
            s = Decimal('0')
            for row in rows.values():
                row[key] = Decimal(row[key]).quantize(Decimal('0.01'))
                s += row[key]
            diff = Decimal(target).quantize(Decimal('0.01')) - s
            if diff != 0:
                big = max(rows.values(), key=lambda x: x['qty'])
                big[key] = (big[key] + diff).quantize(Decimal('0.01'))

        _reconcile('fabric_value', total_fabric)
        _reconcile('accessory', total_acc)
        _reconcile('labor', total_labor)

        for row in rows.values():
            row.pop('_fab_w', None)
            row.pop('_acc_w', None)
            row['total'] = (row['fabric_value'] + row['accessory']
                            + row['labor']).quantize(Decimal('0.01'))
            row['unit'] = ((row['total'] / Decimal(row['qty'])).quantize(Decimal('0.0001'))
                           if row['qty'] else Decimal('0'))
        return rows


class ProductionSubModel(models.Model):
    """موديل فرعي داخل أمر إنتاج (عادة 1-6 موديلات في الورقة الواحدة).

    بيانات القص لكل موديل فرعي: نوع التريكو + طباعة/سادة + لون لكل من:
    الصدر، الظهر، الكم، الشورت.
    """
    TYPE_CHOICES = [('سادة', 'سادة'), ('طباعة', 'طباعة')]

    order = models.ForeignKey(ProductionOrder, on_delete=models.CASCADE,
                               related_name='sub_models', verbose_name='أمر الإنتاج',
                               null=True, blank=True)
    sub_model_no = models.PositiveSmallIntegerField('رقم الموديل الفرعي',
                                                      null=True, blank=True,
                                                      help_text='يتولد تلقائياً (1, 2, 3, ...)')
    fabric_description = models.CharField('نوع التريكو/اللياقة', max_length=200, blank=True,
                                            help_text='مثال: تريكو قطني خام، بوليستر، إلخ')

    # Chest (صدر)
    chest_type = models.CharField('نوع الصدر', max_length=10, choices=TYPE_CHOICES,
                                    default='سادة')
    chest_color = models.CharField('لون الصدر', max_length=100, blank=True)
    chest_notes = models.CharField('ملاحظات الصدر', max_length=200, blank=True)

    # Back (ظهر)
    back_type = models.CharField('نوع الظهر', max_length=10, choices=TYPE_CHOICES,
                                   default='سادة')
    back_color = models.CharField('لون الظهر', max_length=100, blank=True)
    back_notes = models.CharField('ملاحظات الظهر', max_length=200, blank=True)

    # Sleeve (كم)
    sleeve_type = models.CharField('نوع الكم', max_length=10, choices=TYPE_CHOICES,
                                     default='سادة')
    sleeve_color = models.CharField('لون الكم', max_length=100, blank=True)
    sleeve_notes = models.CharField('ملاحظات الكم', max_length=200, blank=True)

    # Shorts (شورت)
    shorts_pattern = models.CharField('نوع الشورت', max_length=100, blank=True,
                                        help_text='كابلس / فينو / إلخ')
    shorts_type = models.CharField('طباعة الشورت', max_length=10, choices=TYPE_CHOICES,
                                     default='سادة')
    shorts_color = models.CharField('لون الشورت', max_length=100, blank=True)
    shorts_notes = models.CharField('ملاحظات الشورت', max_length=200, blank=True)

    ticket = models.CharField('التيكت', max_length=50, blank=True)
    notes = models.CharField('ملاحظات إضافية', max_length=300, blank=True)

    class Meta:
        verbose_name = 'ملاحظات منتج'
        verbose_name_plural = 'ملاحظات المنتج'
        ordering = ['-id']

    def __str__(self):
        # Build a short readable summary of the cut data.
        parts = []
        if self.fabric_description:
            parts.append(self.fabric_description)
        if self.chest_color:
            parts.append(f'صدر {self.chest_color}')
        if self.ticket:
            parts.append(f'تيكت {self.ticket}')
        summary = ' · '.join(parts) if parts else 'ملاحظات'
        return f'#{self.pk} {summary}' if self.pk else summary

    def save(self, *args, **kwargs):
        if not self.sub_model_no and self.order_id:
            # Auto-assign next number within this order
            existing = (ProductionSubModel.objects
                        .filter(order_id=self.order_id)
                        .exclude(pk=self.pk)
                        .order_by('-sub_model_no')
                        .first())
            self.sub_model_no = (existing.sub_model_no + 1) if existing else 1
        super().save(*args, **kwargs)


class ProductionSize(models.Model):
    """الكمية لكل (موديل فرعي × مقاس) في أمر الإنتاج.

    مثال: order=PO-0001, sub_model=1, size='M', quantity=12
    """
    order = models.ForeignKey(ProductionOrder, on_delete=models.CASCADE,
                               related_name='sizes', verbose_name='أمر الإنتاج')
    sub_model = models.ForeignKey(ProductionSubModel, on_delete=models.SET_NULL,
                                    related_name='size_quantities',
                                    verbose_name='ملاحظات المنتج',
                                    null=True, blank=True,
                                    help_text='اضغط ➕ لإضافة ملاحظات/بيانات القص لهذا المقاس')
    size = models.ForeignKey('Size', on_delete=models.PROTECT,
                              related_name='production_sizes',
                              verbose_name='المقاس')
    quantity = models.PositiveIntegerField('الكمية (عدد قطع)',
                                            help_text='المخطط = الفعلي. لو في عجز في القطع، '
                                                      'يتعالج بزيادة استهلاك القماش (قص زيادة) — '
                                                      'مش بتغيير العدد هنا.')

    class Meta:
        verbose_name = 'كمية مقاس'
        verbose_name_plural = 'كميات المقاسات'
        ordering = ['order', 'sub_model__sub_model_no', 'size__sort_order']
        # unique_together dropped — sub_model is now nullable, so we can't enforce
        # the old (sub_model, size) constraint reliably.

    def __str__(self):
        return f'{self.order.order_no} / {self.size} × {self.quantity}'


class FabricUsage(models.Model):
    """استهلاك القماش لأمر إنتاج.

    بقى بيتولّد تلقائياً وقت الإنتاج: النظام بياخد نوع القماش/الخامة من المنتج الرئيسي،
    بيحسب الكمية من الوصفة (قبل + بعد الهالك)، وبيخصمها من دفعات القماش المتاحة من
    نفس النوع بتكلفة المتوسط المرجّح (average) — المستخدم ميختارش دفعة بنفسه.
    لكل دفعة اتخصم منها بيتسجّل صف هنا + حركة FabricMovement (ISSUE_TO_PRODUCTION).
    """
    order = models.ForeignKey(ProductionOrder, on_delete=models.CASCADE,
                               related_name='fabric_usages', verbose_name='أمر الإنتاج')
    fabric_type = models.ForeignKey(FabricType, null=True, blank=True,
                                    on_delete=models.PROTECT,
                                    related_name='production_usages',
                                    verbose_name='نوع القماش/الخامة')
    batch = models.ForeignKey(FabricBatch, null=True, blank=True, on_delete=models.PROTECT,
                               related_name='production_usages',
                               verbose_name='دفعة القماش (اتخصم منها)')
    fabric_color = models.ForeignKey(FabricColor, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name='production_usages',
                                     verbose_name='لون القماش',
                                     help_text='لون القماش اللي اتخصم منه — بيتسجّل على الصف المخطط '
                                               'والفعلي عشان نفرّق الفانلة عن الشورت.')
    planned_qty_kg = models.DecimalField('الكمية قبل الهالك (كيلو)', max_digits=12, decimal_places=3,
                                          help_text='الكمية من الوصفة قبل إضافة الهالك')
    actual_qty_kg = models.DecimalField('الكمية المستخدمة بالهالك (كيلو)', max_digits=12,
                                         decimal_places=3, default=Decimal('0'),
                                         help_text='الكمية قبل الهالك + الهالك (اللي اتخصمت فعلياً)')
    cost_per_kg_snapshot = models.DecimalField('تكلفة الكيلو (متوسط وقت الإنتاج)',
                                                 max_digits=12, decimal_places=4,
                                                 default=Decimal('0'), editable=False)
    notes = models.CharField('ملاحظات', max_length=200, blank=True)

    class Meta:
        verbose_name = 'استهلاك قماش'
        verbose_name_plural = 'استهلاكات القماش'

    def __str__(self):
        label = self.batch.batch_no if self.batch_id else (
            self.fabric_type.name_ar if self.fabric_type_id else 'قماش')
        return f'{self.order.order_no}: {label} × {self.actual_qty_kg or self.planned_qty_kg} كجم'


class Size(models.Model):
    """مقاس قابل للاختيار (XS, S, M, L, XL, 5XS..3XL, 2, 4, 6..14, ...).
    Seeded with common sizes. User can add new ones from admin.
    """
    code = models.CharField('المقاس', max_length=10, unique=True,
                            help_text='مثال: S, M, L, XL, 2XL, 10, 12, 14')
    sort_order = models.PositiveSmallIntegerField('الترتيب', default=99,
                                                    help_text='للعرض في القوائم')
    active = models.BooleanField('نشط', default=True)

    class Meta:
        verbose_name = 'مقاس'
        verbose_name_plural = 'المقاسات'
        ordering = ['sort_order', 'code']

    def __str__(self):
        return self.code


# ============================================================
#  Accessories (Phase 2c)
# ============================================================

class Accessory(models.Model):
    """صنف إكسسوار (أساتيك، زراير، علب، أكياس... إلخ).

    بيتشترى عن طريق "مشتريات الإكسسوارات" فيكون ليه رصيد (current_stock) ومتوسط
    تكلفة (average_cost). الإنتاج بيستهلك من الرصيد ده.
    """
    UNIT_CHOICES = [
        ('قطعة', 'قطعة'),
        ('متر', 'متر'),
        ('كيلو', 'كيلو'),
        ('لفة', 'لفة'),
        ('طقم', 'طقم'),
        ('علبة', 'علبة'),
        ('دستة', 'دستة'),
        ('بكرة', 'بكرة'),
    ]

    code = models.CharField('كود الإكسسوار', max_length=20, unique=True, blank=True,
                             help_text='سيب الخانة فاضية وهيتولّد تلقائياً (ACC-0001 ...)')
    name_ar = models.CharField('اسم الإكسسوار', max_length=200)
    unit = models.CharField('وحدة الاستهلاك', max_length=20, choices=UNIT_CHOICES, default='قطعة',
                              help_text='الوحدة اللي بتستهلك بيها في الإنتاج (المخزون والتكلفة محسوبين بيها)')
    purchase_unit = models.CharField('وحدة الشراء', max_length=20, choices=UNIT_CHOICES,
                                      default='قطعة',
                                      help_text='الوحدة اللي بتشتري بيها من المورد')
    units_per_purchase = models.DecimalField('المعدل (وحدات استهلاك لكل وحدة شراء)',
                                              max_digits=12, decimal_places=4, default=Decimal('1'),
                                              help_text='كام وحدة استهلاك في وحدة الشراء الواحدة. '
                                                        'مثال: بتشتري بالكيلو وتستهلك بالمتر والمتر '
                                                        'وزنه 100 جرام → 1000÷100 = 10 متر في الكيلو. '
                                                        'لو الوحدتين نفس الوحدة سيبها 1.')
    conversion_note = models.CharField('شرح المعدل', max_length=200, blank=True,
                                        help_text='توضيح اختياري، مثال: «وزن المتر 100 جرام»')
    default_unit_cost = models.DecimalField('سعر الوحدة', max_digits=12, decimal_places=4,
                                              default=Decimal('0'),
                                              help_text='سعر استرشادي — التكلفة الفعلية بتيجي من '
                                                        'متوسط تكلفة المشتريات')
    current_stock = models.DecimalField('الرصيد الحالي', max_digits=14, decimal_places=3,
                                         default=Decimal('0'), editable=False)
    average_cost = models.DecimalField('متوسط التكلفة', max_digits=12, decimal_places=4,
                                        default=Decimal('0'), editable=False)
    supplier = models.ForeignKey('Supplier', null=True, blank=True,
                                   on_delete=models.PROTECT, related_name='accessories',
                                   verbose_name='المورد الافتراضي',
                                   limit_choices_to={'vendor_type__code': 'ACCESSORIES'})
    notes = models.TextField('ملاحظات', blank=True)
    active = models.BooleanField('نشط', default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'إكسسوار'
        verbose_name_plural = 'الإكسسوارات'
        ordering = ['code']

    def __str__(self):
        return f'{self.code} - {self.name_ar}'

    def save(self, *args, **kwargs):
        from core.serials import assign_if_blank
        assign_if_blank(self, 'code', 'ACC-', 4)
        super().save(*args, **kwargs)

    @property
    def conversion_factor(self):
        """المعدل المستخدم في التحويل — على الأقل 1 لو فاضي/صفر."""
        f = Decimal(self.units_per_purchase or 0)
        return f if f > 0 else Decimal('1')

    @property
    def stock_in_purchase_unit(self):
        """الرصيد الحالي معبَّراً عنه بوحدة الشراء (للعرض)."""
        return (Decimal(self.current_stock or 0) / self.conversion_factor)

    @property
    def cost_per_purchase_unit(self):
        """متوسط التكلفة معبَّراً عنه بوحدة الشراء (للعرض)."""
        return (Decimal(self.average_cost or 0) * self.conversion_factor)


class AccessoryPurchaseInvoice(models.Model):
    """فاتورة شراء إكسسوارات متعددة البنود — هيدر واحد (مورد + رقم + تاريخ + طريقة دفع)
    وتحته كذا بند (AccessoryPurchase واحد لكل صنف).

    الترحيل بيعمل قيد محاسبي **واحد** للفاتورة كلها:
        DR  مخزون الإكسسوارات (1340000)   إجمالي البنود
        CR  نقدية/بنك/محفظة أو مورد آجل    إجمالي البنود
    وكل بند بيزوّد رصيد صنفه ويحدّث متوسط تكلفته (WAC) — زي الشراء المفرد بالظبط.
    """
    PAYMENT_CHOICES = [
        ('CASH', 'مدفوع (نقدية/بنك/محفظة)'),
        ('CREDIT', 'آجل (على المورد)'),
    ]

    invoice_no = models.CharField('رقم الفاتورة', max_length=30, unique=True, blank=True,
                                  help_text='سيب الخانة فاضية وهيتولّد تلقائياً (API-0001 ...)')
    supplier = models.ForeignKey('Supplier', null=True, blank=True,
                                 on_delete=models.PROTECT, related_name='accessory_invoices',
                                 verbose_name='المورد',
                                 limit_choices_to={'vendor_type__code': 'ACCESSORIES'},
                                 help_text='إجباري لو الفاتورة آجلة')
    supplier_ref = models.CharField('رقم فاتورة المورد', max_length=50, blank=True,
                                    help_text='رقم الفاتورة الورقية اللي جايه من المورد (اختياري)')
    date = models.DateField('تاريخ الفاتورة')
    payment_method = models.CharField('طريقة الدفع', max_length=10,
                                      choices=PAYMENT_CHOICES, default='CASH')
    cash_account = models.ForeignKey('core.CashAccount', null=True, blank=True,
                                     on_delete=models.PROTECT, related_name='accessory_invoices',
                                     verbose_name='مدفوع من (لو مدفوع)',
                                     help_text='اختار الخزينة/البنك/المحفظة لو الدفع مش آجل')
    is_posted = models.BooleanField('مرحّلة محاسبياً', default=False, editable=False)
    journal_entry = models.ForeignKey('core.JournalEntry', null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name='+', editable=False)
    notes = models.TextField('ملاحظات', blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'فاتورة شراء إكسسوارات'
        verbose_name_plural = 'فواتير شراء الإكسسوارات'
        ordering = ['-date', '-id']

    def __str__(self):
        sup = self.supplier.name if self.supplier_id else 'بدون مورد'
        return f'{self.invoice_no} — {sup}'

    def save(self, *args, **kwargs):
        from core.serials import assign_if_blank
        assign_if_blank(self, 'invoice_no', 'API-', 4)
        super().save(*args, **kwargs)

    @property
    def total(self):
        """إجمالي الفاتورة = مجموع (كمية × سعر) لكل البنود."""
        return sum((p.total_cost for p in self.lines.all()),
                   Decimal('0')).quantize(Decimal('0.01'))

    @property
    def line_count(self):
        return self.lines.count()


class AccessoryPurchase(models.Model):
    """عملية شراء إكسسوار — بتزود الرصيد وتحدّث متوسط التكلفة.

    الترحيل: DR مخزون الإكسسوارات / CR نقدية أو مورد (آجل).
    """
    PAYMENT_CHOICES = [
        ('CASH', 'مدفوع (نقدية/بنك/محفظة)'),
        ('CREDIT', 'آجل (على المورد)'),
    ]

    purchase_no = models.CharField('رقم الشراء', max_length=30, unique=True, blank=True,
                                    help_text='سيب الخانة فاضية وهيتولّد تلقائياً (AP-0001 ...)')
    # لو البند جوّه فاتورة متعددة البنود — المورد/التاريخ/الدفع بييجوا من الفاتورة.
    invoice = models.ForeignKey('AccessoryPurchaseInvoice', null=True, blank=True,
                                on_delete=models.CASCADE, related_name='lines',
                                verbose_name='فاتورة الشراء',
                                help_text='يتساب فاضي للشراء المفرد')
    date = models.DateField('التاريخ')
    accessory = models.ForeignKey(Accessory, on_delete=models.PROTECT,
                                   related_name='purchases', verbose_name='الإكسسوار')
    supplier = models.ForeignKey('Supplier', null=True, blank=True,
                                  on_delete=models.PROTECT, related_name='accessory_purchases',
                                  verbose_name='المورد',
                                  limit_choices_to={'vendor_type__code': 'ACCESSORIES'},
                                  help_text='إجباري لو الشراء آجل')
    quantity = models.DecimalField('الكمية (بوحدة الشراء)', max_digits=14, decimal_places=3,
                                    help_text='الكمية بوحدة الشراء — النظام يحوّلها لوحدة الاستهلاك تلقائياً')
    unit_cost = models.DecimalField('سعر وحدة الشراء', max_digits=12, decimal_places=4)
    payment_method = models.CharField('طريقة الدفع', max_length=10,
                                       choices=PAYMENT_CHOICES, default='CASH')
    cash_account = models.ForeignKey('core.CashAccount', null=True, blank=True,
                                      on_delete=models.PROTECT, related_name='accessory_purchases',
                                      verbose_name='مدفوع من (لو نقدي)')
    is_posted = models.BooleanField('مرحّل', default=False, editable=False)
    journal_entry = models.ForeignKey('core.JournalEntry', null=True, blank=True,
                                       on_delete=models.SET_NULL, related_name='+', editable=False)
    notes = models.TextField('ملاحظات', blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'شراء إكسسوار'
        verbose_name_plural = 'مشتريات الإكسسوارات'
        ordering = ['-date', '-id']

    def __str__(self):
        return f'{self.purchase_no} — {self.accessory.name_ar}'

    def save(self, *args, **kwargs):
        from core.serials import assign_if_blank
        assign_if_blank(self, 'purchase_no', 'AP-', 4)
        super().save(*args, **kwargs)

    @property
    def total_cost(self):
        return (Decimal(self.quantity or 0)
                * Decimal(self.unit_cost or 0)).quantize(Decimal('0.01'))


class AccessoryUsage(models.Model):
    """استهلاك إكسسوار في أمر إنتاج. عند الإفراج تتسجل التكلفة في WIP."""
    order = models.ForeignKey('ProductionOrder', on_delete=models.CASCADE,
                               related_name='accessory_usages', verbose_name='أمر الإنتاج')
    accessory = models.ForeignKey(Accessory, on_delete=models.PROTECT,
                                    related_name='usages', verbose_name='الإكسسوار')
    actual_qty = models.DecimalField('الكمية المستخدمة', max_digits=12, decimal_places=3,
                                       default=Decimal('0'),
                                       help_text='الكمية المستخدمة فعلياً — التكلفة بتتحسب منها مباشرة')
    is_posted = models.BooleanField('مرحّل', default=False, editable=False)
    notes = models.CharField('ملاحظات', max_length=200, blank=True)

    class Meta:
        verbose_name = 'استهلاك إكسسوار'
        verbose_name_plural = 'استهلاكات الإكسسوارات'

    def __str__(self):
        return f'{self.order.order_no}: {self.accessory.name_ar} × {self.actual_qty}'

    @property
    def unit_cost(self):
        """السعر = متوسط تكلفة مخزون الإكسسوار، وإلا السعر الافتراضي لو لسه مفيش مشتريات."""
        if not self.accessory_id:
            return Decimal('0')
        avg = Decimal(self.accessory.average_cost or 0)
        return avg if avg > 0 else Decimal(self.accessory.default_unit_cost or 0)

    @property
    def supplier(self):
        """المورد بياخده من الـ Accessory.supplier."""
        return self.accessory.supplier if self.accessory_id else None

    @property
    def qty_before_waste(self):
        """الكمية الخام من الوصفة قبل هالك الإكسسوارات (للعرض). لو مفيش وصفة
        مطابقة بنرجّع الكمية المستخدمة زي ما هي."""
        if not self.order_id or not self.accessory_id:
            return Decimal(self.actual_qty or 0)
        base = self.order.recipe_accessory_plan(with_waste=False)
        val = base.get(self.accessory_id)
        return Decimal(val if val is not None else (self.actual_qty or 0))

    @property
    def total_cost(self):
        return (Decimal(self.actual_qty or 0)
                * Decimal(self.unit_cost)).quantize(Decimal('0.01'))


class ProductionStageRowBase(models.Model):
    """صف صنايعي/كمية في مرحلة من مراحل أمر الإنتاج (طباعة / جودة / كوي).

    كل مرحلة ليها جدول مستقل، ومجموع كميات أي مرحلة المفروض يساوي إجمالي
    كميات المقاسات — بيتفحص ويتنبّه عند الحفظ.
    """
    worker = models.CharField('الصنايعي', max_length=200, blank=True)
    qty = models.PositiveIntegerField('الكمية', default=0)

    class Meta:
        abstract = True
        ordering = ['id']

    def __str__(self):
        return f'{self.order.order_no} / {self.worker or "—"} ({self.qty})'


class ProductionPrintingRow(ProductionStageRowBase):
    """1) مرحلة الطباعة — الصنايعي والكمية."""
    order = models.ForeignKey('ProductionOrder', on_delete=models.CASCADE,
                               related_name='printing_rows', verbose_name='أمر الإنتاج')

    class Meta(ProductionStageRowBase.Meta):
        verbose_name = 'صف طباعة'
        verbose_name_plural = 'مرحلة الطباعة'


class ProductionOperationRow(ProductionStageRowBase):
    """2) مراحل التشغيل — رقم/اسم المرحلة + المكنة + الصنايعي + الكمية."""
    order = models.ForeignKey('ProductionOrder', on_delete=models.CASCADE,
                               related_name='operation_rows', verbose_name='أمر الإنتاج')
    stage_no = models.CharField('رقم المرحلة', max_length=30, blank=True)
    stage_name = models.CharField('اسم المرحلة', max_length=200, blank=True)
    machine = models.CharField('المكنة', max_length=200, blank=True)

    class Meta(ProductionStageRowBase.Meta):
        verbose_name = 'صف تشغيل'
        verbose_name_plural = 'مراحل التشغيل'


class ProductionQualityRow(ProductionStageRowBase):
    """3) مرحلة الجودة — الصنايعي والكمية."""
    order = models.ForeignKey('ProductionOrder', on_delete=models.CASCADE,
                               related_name='quality_rows', verbose_name='أمر الإنتاج')

    class Meta(ProductionStageRowBase.Meta):
        verbose_name = 'صف جودة'
        verbose_name_plural = 'مرحلة الجودة'


class ProductionIroningRow(ProductionStageRowBase):
    """4) مرحلة الكوي — الصنايعي والكمية."""
    order = models.ForeignKey('ProductionOrder', on_delete=models.CASCADE,
                               related_name='ironing_rows', verbose_name='أمر الإنتاج')

    class Meta(ProductionStageRowBase.Meta):
        verbose_name = 'صف كوي'
        verbose_name_plural = 'مرحلة الكوي'


class FabricMovement(models.Model):
    """Append-only — كل حركة كيلو على دفعة قماش.

    لا تنشأ يدوياً — services.py بتنشئها لكل عملية شراء/إرسال/استلام/صرف.
    """
    MOVEMENT_TYPES = [
        ('PURCHASE_IN', 'استلام من المورد'),
        ('ISSUE_TO_PRODUCTION', 'صرف للإنتاج'),
        ('ADJUST_IN', 'تسوية موجبة'),
        ('ADJUST_OUT', 'تسوية سالبة'),
        ('WASTE', 'إهدار / تالف'),
    ]

    batch = models.ForeignKey(FabricBatch, on_delete=models.PROTECT, related_name='movements',
                               verbose_name='دفعة القماش')
    date = models.DateField('التاريخ')
    movement_type = models.CharField('نوع الحركة', max_length=30, choices=MOVEMENT_TYPES)
    quantity_kg = models.DecimalField('الكمية (كيلو)', max_digits=12, decimal_places=3,
                                       help_text='كمية موجبة دائماً — نوع الحركة بيحدد in/out')
    cost_per_kg_snapshot = models.DecimalField('تكلفة الكيلو وقت الحركة', max_digits=12, decimal_places=4,
                                                 default=Decimal('0'))
    document_type = models.CharField('نوع المستند', max_length=50, blank=True)
    document_id = models.PositiveIntegerField('رقم المستند', null=True, blank=True)
    notes = models.CharField('ملاحظات', max_length=500, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'حركة قماش'
        verbose_name_plural = 'حركات القماش'
        ordering = ['-date', '-id']
        indexes = [
            models.Index(fields=['batch', 'date']),
            models.Index(fields=['movement_type']),
        ]

    def __str__(self):
        return f'{self.batch.batch_no} {self.movement_type} {self.quantity_kg}كجم'


# ============================================================
#  Product recipe / BOM per size (Phase 3)
# ============================================================

class ProductSizeRecipe(models.Model):
    """وصفة المنتج لكل مقاس — كمية القماش + تكلفة المصنعية + سعر البيع + حد إعادة الطلب
    للقطعة/المقاس الواحد. (نسبة الهالك بقت على المنتج كله مش لكل مقاس.)

    بتتعرّف مرة واحدة على المنتج الرئيسي (inventory.Product)، وكل أوامر الإنتاج
    للمنتجات الفرعية التابعة له بتستخدمها لحساب:
      - الكمية قبل الهالك      = كمية القماش × عدد القطع
      - الكمية المستخدمة بالهالك = قبل الهالك × (1 + نسبة هالك المنتج)
      - تكلفة المصنعية         = مصنعية المقاس × عدد القطع (بتترسمل في المخزون).
    """
    product = models.ForeignKey('inventory.Product', on_delete=models.CASCADE,
                                related_name='size_recipes', verbose_name='المنتج')
    size = models.ForeignKey(Size, on_delete=models.PROTECT,
                             related_name='product_recipes', verbose_name='المقاس')
    fabric_qty_kg = models.DecimalField('كمية القماش للقطعة (كيلو)', max_digits=10,
                                        decimal_places=4, default=Decimal('0'),
                                        help_text='كمية القماش اللي القطعة الواحدة من المقاس ده '
                                                  'بتستهلكها — قبل إضافة الهالك. (للأطقم = قماش الفانلة.)')
    shorts_fabric_qty_kg = models.DecimalField('قماش الشورت للقطعة (كيلو)', max_digits=10,
                                               decimal_places=4, default=Decimal('0'),
                                               help_text='للأطقم بس: كمية قماش الشورت للقطعة الواحدة '
                                                         '(قبل الهالك). بتتخصم من لون الشورت بتاع المنتج '
                                                         'الفرعي. سيبها 0 لو المنتج مش طقم بلونين.')
    labor_cost = models.DecimalField('تكلفة المصنعية للقطعة', max_digits=12, decimal_places=4,
                                     default=Decimal('0'),
                                     help_text='أجور التشغيل/المصنعية للقطعة الواحدة من المقاس ده. '
                                               'بتتضاف لتكلفة المخزون ومقابلها استحقاق في الميزانية.')
    selling_price = models.DecimalField('سعر البيع للقطعة', max_digits=12, decimal_places=2,
                                        default=Decimal('0'),
                                        help_text='سعر بيع القطعة الواحدة من المقاس ده. بيتطبّق على '
                                                  'كل المنتجات الفرعية التابعة للمنتج الرئيسي. سعر '
                                                  'الدستة = ده × عدد القطع في الدستة.')
    reorder_level = models.DecimalField('حد إعادة الطلب (بالقطعة)', max_digits=12, decimal_places=2,
                                        default=Decimal('0'),
                                        help_text='لما رصيد القطع للمقاس ده ينزل عن العدد ده، '
                                                  'يبقى وقت تطلب/تنتج تاني. بيتطبّق على كل المنتجات '
                                                  'الفرعية التابعة للمنتج الرئيسي.')
    notes = models.CharField('ملاحظات', max_length=200, blank=True)

    class Meta:
        verbose_name = 'وصفة مقاس'
        verbose_name_plural = 'وصفات المقاسات'
        ordering = ['product', 'size__sort_order']
        unique_together = [('product', 'size')]

    def __str__(self):
        return f'{self.product} / {self.size} — {self.fabric_qty_kg}كجم'

    @property
    def fabric_qty_with_waste(self):
        """كمية القماش للقطعة بعد إضافة الهالك (نسبة الهالك معرّفة على المنتج كله)."""
        waste = Decimal(self.product.waste_pct or 0) if self.product_id else Decimal('0')
        return (Decimal(self.fabric_qty_kg or 0)
                * (Decimal('1') + waste / Decimal('100')))


class ProductSizeAccessory(models.Model):
    """استهلاك إكسسوار في وصفة مقاس (للقطعة الواحدة)."""
    recipe = models.ForeignKey(ProductSizeRecipe, on_delete=models.CASCADE,
                               related_name='accessories', verbose_name='وصفة المقاس')
    accessory = models.ForeignKey(Accessory, on_delete=models.PROTECT,
                                  related_name='recipe_lines', verbose_name='الإكسسوار')
    qty_per_piece = models.DecimalField('الكمية للقطعة', max_digits=12, decimal_places=3,
                                        default=Decimal('0'),
                                        help_text='كمية الإكسسوار اللي القطعة الواحدة بتستهلكها.')

    class Meta:
        verbose_name = 'إكسسوار الوصفة'
        verbose_name_plural = 'إكسسوارات الوصفة'
        unique_together = [('recipe', 'accessory')]

    def __str__(self):
        return f'{self.recipe.size}: {self.accessory.name_ar} × {self.qty_per_piece}'


# ============================================================
#  Manufacturing wage payments (صرف مصنعيات) — Phase C
# ============================================================

class ManufacturingWagePayment(models.Model):
    """صرف مصنعيات — دفع أجور التشغيل/المصنعية للعمال أو المشرفين.

    المصنعية بتترسمل وقت الإنتاج كاستحقاق في الميزانية
    (CR «مصنعيات مستحقة» 2320000). سند الصرف ده بيدفع مقابل الاستحقاق:
      - يخصم من «مصنعيات مستحقة» في حدود رصيدها       (DR 2320000)
      - أي زيادة عن المستحق تروح «فرق مصنعيات» مصروف  (DR 5360000)
      - CR النقدية/البنك بالمبلغ المدفوع
    لو دفعت أقل من المستحق، الباقي يفضل رصيد دائن في الميزانية (مصنعيات مستحقة).
    """
    METHOD_CHOICES = [
        ('CASH', 'كاش'),
        ('BANK', 'تحويل بنكي'),
        ('CHEQUE', 'شيك'),
    ]
    STATUS_CHOICES = [
        ('DRAFT', 'مسودة'),
        ('POSTED', 'مرحّل'),
        ('CANCELLED', 'ملغي'),
    ]

    payment_no = models.CharField('رقم السند', max_length=30, unique=True, blank=True,
                                   help_text='سيب الخانة فاضية وهيتولّد تلقائياً (MW-0001 ...)')
    date = models.DateField('التاريخ')
    payee = models.CharField('المستفيد (اسم العامل/المشرف)', max_length=200, blank=True,
                              help_text='اختياري — اسم اللي استلم المصنعية')
    expense_category = models.ForeignKey('core.ExpenseCategory', null=True, blank=True,
                                         on_delete=models.SET_NULL, related_name='+',
                                         verbose_name='نوع المصروف',
                                         help_text='بند المصروف لتصنيف الصرف وتجميعه في القوائم والتقارير '
                                                   '(للتصنيف فقط — مش بيغيّر القيد المحاسبي؛ الصرف بيترحّل زي ما هو).')
    amount = models.DecimalField('المبلغ', max_digits=14, decimal_places=2)
    method = models.CharField('طريقة الدفع', max_length=10, choices=METHOD_CHOICES, default='CASH')
    cash_account = models.ForeignKey('core.CashAccount', null=True, blank=True,
                                      on_delete=models.PROTECT, related_name='wage_payments',
                                      verbose_name='النقدية/البنك/المحفظة',
                                      help_text='الحساب اللى دفعت منه. سيبه فاضي عشان يستخدم الحساب الافتراضي.')
    reference = models.CharField('المرجع (رقم شيك / حوالة)', max_length=100, blank=True)
    notes = models.TextField('ملاحظات', blank=True)
    status = models.CharField('الحالة', max_length=10, choices=STATUS_CHOICES, default='DRAFT')

    # Snapshots of how the payment split at posting time (للعرض والمراجعة).
    accrued_portion = models.DecimalField('المسدّد من المستحق', max_digits=14, decimal_places=2,
                                           default=Decimal('0'), editable=False)
    expense_portion = models.DecimalField('الزيادة (فرق مصنعيات)', max_digits=14, decimal_places=2,
                                           default=Decimal('0'), editable=False)
    journal_entry = models.ForeignKey('core.JournalEntry', null=True, blank=True,
                                       on_delete=models.SET_NULL, related_name='+',
                                       editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'صرف مصنعيات'
        verbose_name_plural = 'صرف المصنعيات'
        ordering = ['-date', '-id']

    def __str__(self):
        who = self.payee or 'مصنعيات'
        return f'{self.payment_no} — {who} ({self.amount})'

    def save(self, *args, **kwargs):
        from core.serials import assign_if_blank
        assign_if_blank(self, 'payment_no', 'MW-', 4)
        super().save(*args, **kwargs)


# ============================================================
#  Year-end manufacturing wage adjustment (تسوية مصنعيات)
# ============================================================

class ManufacturingWageAdjustment(models.Model):
    """تسوية مصنعيات آخر الفترة — تعديل «مصنعيات مستحقة» (2320000) لأعلى أو لأسفل،
    والفرق بيروح قائمة الأرباح والخسائر عبر «فرق مصنعيات» (5370000):
      - زيادة (أنتجت أكتر/المصنعية لازم تزيد):
            DR فرق مصنعيات (مصروف ↑ في ق.الدخل) / CR مصنعيات مستحقة (التزام ↑)
      - نقص (أنتجت أقل/المصنعية تقل):
            DR مصنعيات مستحقة (التزام ↓) / CR فرق مصنعيات (يقلّل مصروف ق.الدخل)
    تسوية محاسبية فقط — مفيش نقدية. السداد الفعلي بيتم عبر «صرف مصنعيات».
    """
    DIRECTION_CHOICES = [
        ('INCREASE', 'زيادة المصنعيات (تكلفة أكبر)'),
        ('DECREASE', 'نقص المصنعيات (تكلفة أقل)'),
    ]
    STATUS_CHOICES = [
        ('DRAFT', 'مسودة'),
        ('POSTED', 'مرحّل'),
    ]
    adjustment_no = models.CharField('رقم التسوية', max_length=30, unique=True, blank=True,
                                     help_text='سيب الخانة فاضية وهيتولّد تلقائياً (MWA-0001 ...)')
    date = models.DateField('التاريخ')
    direction = models.CharField('نوع التسوية', max_length=10, choices=DIRECTION_CHOICES,
                                 default='INCREASE')
    amount = models.DecimalField('المبلغ', max_digits=14, decimal_places=2)
    notes = models.TextField('السبب / ملاحظات', blank=True)
    status = models.CharField('الحالة', max_length=10, choices=STATUS_CHOICES, default='DRAFT')
    journal_entry = models.ForeignKey('core.JournalEntry', null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name='+', editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'تسوية مصنعيات'
        verbose_name_plural = 'تسويات المصنعيات (آخر السنة)'
        ordering = ['-date', '-id']

    def __str__(self):
        return f'{self.adjustment_no} — {self.get_direction_display()} ({self.amount})'

    def save(self, *args, **kwargs):
        from core.serials import assign_if_blank
        assign_if_blank(self, 'adjustment_no', 'MWA-', 4)
        super().save(*args, **kwargs)
