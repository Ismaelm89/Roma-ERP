from decimal import Decimal
from django.db import models
from django.conf import settings


# 27 محافظات جمهورية مصر العربية — مرتبة هجائياً
EGYPT_GOVERNORATES = [
    ('الإسكندرية', 'الإسكندرية'),
    ('الإسماعيلية', 'الإسماعيلية'),
    ('الأقصر', 'الأقصر'),
    ('البحر الأحمر', 'البحر الأحمر'),
    ('البحيرة', 'البحيرة'),
    ('الجيزة', 'الجيزة'),
    ('الدقهلية', 'الدقهلية'),
    ('السويس', 'السويس'),
    ('الشرقية', 'الشرقية'),
    ('الغربية', 'الغربية'),
    ('الفيوم', 'الفيوم'),
    ('القاهرة', 'القاهرة'),
    ('القليوبية', 'القليوبية'),
    ('المنوفية', 'المنوفية'),
    ('المنيا', 'المنيا'),
    ('الوادي الجديد', 'الوادي الجديد'),
    ('أسوان', 'أسوان'),
    ('أسيوط', 'أسيوط'),
    ('بني سويف', 'بني سويف'),
    ('بورسعيد', 'بورسعيد'),
    ('جنوب سيناء', 'جنوب سيناء'),
    ('دمياط', 'دمياط'),
    ('سوهاج', 'سوهاج'),
    ('شمال سيناء', 'شمال سيناء'),
    ('قنا', 'قنا'),
    ('كفر الشيخ', 'كفر الشيخ'),
    ('مطروح', 'مطروح'),
]


class Customer(models.Model):
    """Customer master.  `current_balance` is computed from JournalLine, not stored —
    see spec §4.6 (balances calculated from movements, not static fields)."""
    code = models.CharField('كود العميل', max_length=20, unique=True,
                             blank=True,
                             help_text='سيب الخانة فاضية وهيتولّد تلقائياً (C0001, C0002 ...)')
    name_ar = models.CharField('اسم العميل', max_length=200)
    name_en = models.CharField('Name (English)', max_length=200, blank=True)
    tax_id = models.CharField('الرقم الضريبي', max_length=50, blank=True)
    commercial_register = models.CharField('السجل التجاري', max_length=50, blank=True)
    address = models.CharField('العنوان', max_length=500, blank=True)
    governorate = models.CharField('المحافظة', max_length=100, blank=True,
                                    choices=EGYPT_GOVERNORATES)
    phone = models.CharField('الهاتف', max_length=50, blank=True)
    email = models.EmailField('البريد', blank=True)
    payment_terms_days = models.PositiveIntegerField('شروط السداد (أيام)', default=0)
    credit_limit = models.DecimalField('حد الائتمان', max_digits=14, decimal_places=2,
                                        default=Decimal('0'))
    opening_balance = models.DecimalField('الرصيد الافتتاحي', max_digits=14, decimal_places=2,
                                           default=Decimal('0'))
    active = models.BooleanField('نشط', default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'عميل'
        verbose_name_plural = 'العملاء'
        ordering = ['code']

    def __str__(self):
        return f'{self.code} - {self.name_ar}'

    def save(self, *args, **kwargs):
        from core.serials import assign_if_blank
        assign_if_blank(self, 'code', 'C', 4)
        super().save(*args, **kwargs)

    @property
    def current_balance(self):
        """Live AR balance: opening_balance + Σ(debit) − Σ(credit) of posted journal
        lines tagged with this customer on the AR account."""
        from decimal import Decimal
        from django.db.models import Sum
        from core.account_codes import SYSTEM_ACCOUNTS
        from core.models import JournalLine
        agg = JournalLine.objects.filter(
            customer=self,
            account__code=SYSTEM_ACCOUNTS['AR'],
            entry__status='POSTED',
        ).aggregate(d=Sum('debit'), c=Sum('credit'))
        return (Decimal(self.opening_balance or 0)
                + (agg['d'] or Decimal('0'))
                - (agg['c'] or Decimal('0')))


class SalesInvoice(models.Model):
    STATUS_CHOICES = [
        ('DRAFT', 'مسودة'),
        ('POSTED', 'مرحّلة'),
        ('CANCELLED', 'ملغاة'),
    ]
    invoice_no = models.CharField('رقم الفاتورة', max_length=30, unique=True,
                                    blank=True,
                                    help_text='سيب الخانة فاضية وهيتولّد تلقائياً (INV-0001, INV-0002 ...)')
    date = models.DateField('التاريخ')
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='invoices',
                                  verbose_name='العميل')
    notes = models.TextField('ملاحظات', blank=True)
    subtotal = models.DecimalField('الإجمالي قبل الخصم', max_digits=14, decimal_places=2,
                                    default=Decimal('0'))
    doc_discount_percent = models.DecimalField('نسبة خصم التاجر %',
                                                  max_digits=5, decimal_places=2,
                                                  default=Decimal('0'),
                                                  help_text='إذا أدخلت نسبة، يتم حساب القيمة تلقائياً.')
    doc_discount_amount = models.DecimalField('خصم التاجر', max_digits=14, decimal_places=2,
                                                default=Decimal('0'))
    grand_total = models.DecimalField('الإجمالي', max_digits=14, decimal_places=2,
                                       default=Decimal('0'))

    # Payment terms — open-ended weekly plan (no fixed number of weeks).
    INSTALLMENT_FREQ_CHOICES = [
        ('', 'بدون'),
        ('WEEKLY', 'أسبوعي'),
        ('MONTHLY', 'شهري'),
    ]
    cash_payment_percent = models.DecimalField('نسبة الدفعة الكاش %', max_digits=5,
                                                 decimal_places=2, default=Decimal('0'),
                                                 help_text='النسبة المتفق على دفعها كاش عند الاستلام')
    installment_frequency = models.CharField('نظام السداد', max_length=10, blank=True,
                                              choices=INSTALLMENT_FREQ_CHOICES, default='',
                                              help_text='كيف يتم دفع باقي المبلغ')
    status = models.CharField('الحالة', max_length=10, choices=STATUS_CHOICES, default='DRAFT')
    posted_at = models.DateTimeField(null=True, blank=True)
    posted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name='posted_invoices')
    journal_entry = models.ForeignKey('core.JournalEntry', null=True, blank=True,
                                       on_delete=models.SET_NULL, related_name='+')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                                    related_name='created_invoices')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'فاتورة مبيعات'
        verbose_name_plural = 'فواتير المبيعات'
        ordering = ['-date', '-id']

    def __str__(self):
        return f'{self.invoice_no}'

    def save(self, *args, **kwargs):
        from core.serials import assign_if_blank
        assign_if_blank(self, 'invoice_no', 'INV-', 4)
        super().save(*args, **kwargs)

    @property
    def cash_payment_amount(self):
        """The 'cash on receipt' portion (from cash_payment_percent)."""
        if not self.cash_payment_percent or Decimal(self.cash_payment_percent) <= 0:
            return Decimal('0')
        return (Decimal(self.grand_total) * Decimal(self.cash_payment_percent)
                / Decimal('100')).quantize(Decimal('0.01'))

    @property
    def installments_amount(self):
        """The portion to be paid in installments (grand_total − cash portion)."""
        return (Decimal(self.grand_total) - self.cash_payment_amount).quantize(Decimal('0.01'))

    @property
    def paid_amount(self):
        from decimal import Decimal
        from django.db.models import Sum
        if self.status != 'POSTED':
            return Decimal('0')
        return (self.allocations.filter(receipt__status='POSTED')
                                 .aggregate(s=Sum('amount'))['s'] or Decimal('0'))

    @property
    def balance_due(self):
        from decimal import Decimal
        if self.status != 'POSTED':
            return Decimal('0')
        return Decimal(self.grand_total) - Decimal(self.paid_amount)

    @property
    def total_cogs(self):
        """تكلفة البضاعة المباعة للفاتورة كلها — المرحّلة (cogs_at_posting) للفواتير
        المرحّلة، أو المقدّرة من متوسط تكلفة المخزون الحالي للمسودة."""
        total = Decimal('0')
        for ln in self.lines.select_related('variant').all():
            if self.status == 'POSTED' and ln.cogs_at_posting:
                total += Decimal(ln.cogs_at_posting)
            elif ln.variant_id:
                pieces = Decimal(ln.total_pieces or 0)
                total += pieces * Decimal(ln.variant.average_cost or 0)
        return total.quantize(Decimal('0.01'))

    @property
    def profit(self):
        """ربح/خسارة الفاتورة = الإجمالي بعد الخصم − تكلفة البضاعة المباعة."""
        return (Decimal(self.grand_total or 0) - self.total_cogs).quantize(Decimal('0.01'))

    @property
    def profit_margin_pct(self):
        g = Decimal(self.grand_total or 0)
        if g <= 0:
            return Decimal('0')
        return (self.profit / g * Decimal('100')).quantize(Decimal('0.1'))

    def recalc_totals(self):
        from django.db.models import Sum
        agg = self.lines.aggregate(s=Sum('line_total'))
        self.subtotal = agg['s'] or Decimal('0')
        if Decimal(self.doc_discount_percent or 0) > 0:
            self.doc_discount_amount = (
                Decimal(self.subtotal) * Decimal(self.doc_discount_percent) / Decimal('100')
            ).quantize(Decimal('0.01'))
        self.grand_total = (Decimal(self.subtotal) - Decimal(self.doc_discount_amount)).quantize(Decimal('0.01'))
        self.save(update_fields=['subtotal', 'doc_discount_amount', 'grand_total'])


class SalesInvoiceLine(models.Model):
    """البيع بوحدة مختارة (قطعة/دستة/كرتونة) من مقاس محدد (variant).
      - sale_unit = الوحدة: قطعة / دستة / كرتونة.
      - quantity = العدد بالوحدة دي (مثلاً 3 دستة، 2 كرتونة، 6 قطع).
      - unit_price = سعر الوحدة (يتعبا تلقائياً = سعر القطعة × عدد القطع في الوحدة).
      - عند الترحيل: يخصم (quantity × عدد القطع في الوحدة) قطعة من المقاس.
    """
    SALE_UNIT_CHOICES = [('PIECE', 'قطعة'), ('DOZEN', 'دستة'), ('CARTON', 'كرتونة')]

    invoice = models.ForeignKey(SalesInvoice, on_delete=models.CASCADE, related_name='lines')
    item = models.ForeignKey('inventory.Item', on_delete=models.PROTECT,
                              null=True, blank=True, verbose_name='الصنف',
                              help_text='بيتحدد تلقائياً من المقاس المختار')
    variant = models.ForeignKey('inventory.ItemVariant', on_delete=models.PROTECT,
                                 null=True, blank=True,
                                 verbose_name='المقاس',
                                 help_text='اختار المقاس اللي بتبيعه')
    sale_unit = models.CharField('وحدة البيع', max_length=10, choices=SALE_UNIT_CHOICES,
                                 default='PIECE',
                                 help_text='تبيع بالقطعة ولا الدستة ولا الكرتونة. '
                                           'الكمية والسعر بيتحسبوا على حسب الوحدة.')
    quantity = models.DecimalField('العدد (بالوحدة)', max_digits=12, decimal_places=2,
                                    help_text='العدد بوحدة البيع المختارة (قطع/دستات/كراتين).')
    unit_price = models.DecimalField('سعر الوحدة', max_digits=12, decimal_places=2,
                                      help_text='يتعبا تلقائياً = سعر القطعة × عدد القطع في الوحدة')
    line_total = models.DecimalField('الإجمالي', max_digits=14, decimal_places=2,
                                      default=Decimal('0'))
    cogs_at_posting = models.DecimalField('تكلفة البضاعة المباعة', max_digits=14, decimal_places=2,
                                            default=Decimal('0'))

    class Meta:
        verbose_name = 'بند فاتورة'
        verbose_name_plural = 'بنود الفواتير'

    def __str__(self):
        code = self.item.code if self.item_id else '?'
        suffix = f'-{self.variant.size}' if self.variant_id else ''
        return f'{code}{suffix} × {self.quantity} {self.get_sale_unit_display()}'

    @property
    def _item(self):
        if self.variant_id and self.variant.item_id:
            return self.variant.item
        return self.item if self.item_id else None

    @property
    def dozen_size(self):
        """عدد القطع في الدستة لهذا الصنف."""
        it = self._item
        return (it.dozen_size or 12) if it else 12

    @property
    def unit_factor(self):
        """عدد القطع في وحدة البيع المختارة (قطعة=1، دستة=dozen_size، كرتونة=carton_size)."""
        if self.sale_unit == 'DOZEN':
            return Decimal(self.dozen_size)
        if self.sale_unit == 'CARTON':
            it = self._item
            return Decimal((it.carton_size or 0) if it else 0)
        return Decimal('1')

    @property
    def total_pieces(self):
        """إجمالي القطع الفعلية = العدد × عدد القطع في الوحدة."""
        return (Decimal(self.quantity or 0) * self.unit_factor).quantize(Decimal('0.01'))

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.sale_unit == 'CARTON' and self.variant_id and self.unit_factor <= 0:
            raise ValidationError('حدد «عدد القطع في الكرتونة» على المنتج الفرعي الأول '
                                  'عشان تقدر تبيع بالكرتونة.')

    def save(self, *args, **kwargs):
        # Derive item from the selected variant.
        if self.variant_id and not self.item_id:
            self.item = self.variant.item
        # Auto-fill unit_price = piece selling price × عدد القطع في الوحدة.
        if (not self.unit_price or Decimal(self.unit_price) == 0) and self.variant_id:
            piece = Decimal(self.variant.selling_price or 0)
            self.unit_price = (piece * self.unit_factor).quantize(Decimal('0.01'))
        super().save(*args, **kwargs)

    def recalc(self):
        self.line_total = (Decimal(self.quantity) * Decimal(self.unit_price)).quantize(Decimal('0.01'))


class Receipt(models.Model):
    METHOD_CHOICES = [
        ('CASH', 'نقدي'),
        ('BANK', 'تحويل بنكي'),
        ('CHEQUE', 'شيك'),
        ('POS', 'نقاط بيع'),
    ]
    STATUS_CHOICES = [
        ('DRAFT', 'مسودة'),
        ('POSTED', 'مرحّل'),
        ('CANCELLED', 'ملغي'),
    ]
    receipt_no = models.CharField('رقم السند', max_length=30, unique=True,
                                    blank=True,
                                    help_text='سيب الخانة فاضية وهيتولّد تلقائياً (REC-0001, REC-0002 ...)')
    date = models.DateField('التاريخ')
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='receipts',
                                  verbose_name='العميل')
    method = models.CharField('طريقة الدفع', max_length=10, choices=METHOD_CHOICES, default='CASH')
    cash_account = models.ForeignKey('core.CashAccount', null=True, blank=True,
                                      on_delete=models.PROTECT, related_name='receipts',
                                      verbose_name='النقدية/البنك/المحفظة',
                                      help_text='الحساب اللى استلمت فيه الفلوس. سيبه فاضي عشان يستخدم الحساب الافتراضي.')
    amount = models.DecimalField('المبلغ', max_digits=14, decimal_places=2)
    reference = models.CharField('المرجع', max_length=100, blank=True)
    notes = models.TextField('ملاحظات', blank=True)
    status = models.CharField('الحالة', max_length=10, choices=STATUS_CHOICES, default='DRAFT')
    posted_at = models.DateTimeField(null=True, blank=True)
    journal_entry = models.ForeignKey('core.JournalEntry', null=True, blank=True,
                                       on_delete=models.SET_NULL, related_name='+')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'سند قبض'
        verbose_name_plural = 'سندات القبض'
        ordering = ['-date', '-id']

    def __str__(self):
        return self.receipt_no

    def save(self, *args, **kwargs):
        from core.serials import assign_if_blank
        assign_if_blank(self, 'receipt_no', 'REC-', 4)
        super().save(*args, **kwargs)


class ReceiptAllocation(models.Model):
    """Apply part of a Receipt to a specific SalesInvoice."""
    receipt = models.ForeignKey(Receipt, on_delete=models.CASCADE, related_name='allocations')
    invoice = models.ForeignKey(SalesInvoice, on_delete=models.PROTECT, related_name='allocations',
                                  verbose_name='الفاتورة')
    amount = models.DecimalField('المبلغ المخصص', max_digits=14, decimal_places=2)

    class Meta:
        verbose_name = 'تخصيص دفعة'
        verbose_name_plural = 'تخصيصات الدفعات'

    def __str__(self):
        return f'{self.receipt} → {self.invoice}: {self.amount}'


# ============================================================
#  Sales Returns — partial returns from posted invoices
# ============================================================

class SalesReturn(models.Model):
    """Customer return of part (or all) of a previously sold invoice.
    Each line can be either piece-level (variant set) or bundle-level (variant=None).
    """
    STATUS_CHOICES = [
        ('DRAFT', 'مسودة'),
        ('POSTED', 'مرحّل'),
        ('CANCELLED', 'ملغي'),
    ]
    return_no = models.CharField('رقم المرتجع', max_length=30, unique=True,
                                   blank=True,
                                   help_text='سيب الخانة فاضية وهيتولّد تلقائياً (RET-0001, RET-0002 ...)')
    date = models.DateField('التاريخ')
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='returns',
                                  verbose_name='العميل')
    original_invoice = models.ForeignKey(SalesInvoice, null=True, blank=True,
                                          on_delete=models.PROTECT, related_name='returns',
                                          verbose_name='الفاتورة الأصلية (اختياري)')
    reason = models.CharField('السبب', max_length=200, blank=True,
                               help_text='مثلاً: عيب مصنعى — مقاس غلط — تبديل')
    notes = models.TextField('ملاحظات', blank=True)
    subtotal = models.DecimalField('إجمالي قيمة المرتجع', max_digits=14, decimal_places=2,
                                    default=Decimal('0'))
    grand_total = models.DecimalField('المبلغ المخصوم من المستحق', max_digits=14, decimal_places=2,
                                       default=Decimal('0'))
    status = models.CharField('الحالة', max_length=10, choices=STATUS_CHOICES, default='DRAFT')
    posted_at = models.DateTimeField(null=True, blank=True)
    posted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name='posted_returns')
    journal_entry = models.ForeignKey('core.JournalEntry', null=True, blank=True,
                                       on_delete=models.SET_NULL, related_name='+')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                                    related_name='created_returns')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'مرتجع مبيعات'
        verbose_name_plural = 'مرتجعات المبيعات'
        ordering = ['-date', '-id']

    def __str__(self):
        return self.return_no

    def save(self, *args, **kwargs):
        from core.serials import assign_if_blank
        assign_if_blank(self, 'return_no', 'RET-', 4)
        super().save(*args, **kwargs)

    def recalc_totals(self):
        from django.db.models import Sum
        agg = self.lines.aggregate(s=Sum('line_total'))
        self.subtotal = agg['s'] or Decimal('0')
        self.grand_total = self.subtotal
        self.save(update_fields=['subtotal', 'grand_total'])


class SalesReturnLine(models.Model):
    """بند مرتجع بالقطعة — عدد قطع من مقاس محدد (نفس منطق فاتورة البيع)."""
    return_doc = models.ForeignKey(SalesReturn, on_delete=models.CASCADE, related_name='lines')
    item = models.ForeignKey('inventory.Item', on_delete=models.PROTECT,
                              null=True, blank=True, verbose_name='الصنف',
                              help_text='بيتحدد تلقائياً من المقاس')
    variant = models.ForeignKey('inventory.ItemVariant', on_delete=models.PROTECT,
                                 null=True, blank=True,
                                 verbose_name='المقاس',
                                 help_text='اختار المقاس المرتجع')
    quantity = models.DecimalField('عدد القطع', max_digits=12, decimal_places=2,
                                    help_text='عدد القطع المرتجعة من المقاس ده.')
    unit_price = models.DecimalField('سعر القطعة المُسترد', max_digits=12, decimal_places=2)
    line_total = models.DecimalField('الإجمالي', max_digits=14, decimal_places=2,
                                      default=Decimal('0'))
    cogs_at_posting = models.DecimalField('تكلفة البضاعة المرتجعة', max_digits=14, decimal_places=2,
                                            default=Decimal('0'))

    class Meta:
        verbose_name = 'بند مرتجع'
        verbose_name_plural = 'بنود المرتجعات'

    def __str__(self):
        code = self.item.code if self.item_id else '?'
        suffix = f'-{self.variant.size}' if self.variant_id else ''
        return f'{code}{suffix} × {self.quantity} قطعة'

    @property
    def dozen_size(self):
        if self.variant_id and self.variant.item_id:
            return self.variant.item.dozen_size or 12
        if self.item_id:
            return self.item.dozen_size or 12
        return 12

    @property
    def total_pieces(self):
        return Decimal(self.quantity or 0).quantize(Decimal('0.01'))

    def save(self, *args, **kwargs):
        if self.variant_id and not self.item_id:
            self.item = self.variant.item
        if (not self.unit_price or Decimal(self.unit_price) == 0) and self.variant_id:
            self.unit_price = Decimal(self.variant.selling_price or 0).quantize(Decimal('0.01'))
        super().save(*args, **kwargs)

    def recalc(self):
        self.line_total = (Decimal(self.quantity) * Decimal(self.unit_price)).quantize(Decimal('0.01'))
