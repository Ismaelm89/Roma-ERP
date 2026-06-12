from decimal import Decimal
from django.db import models
from django.conf import settings


class Company(models.Model):
    """Singleton — only one row expected."""
    name_ar = models.CharField('الاسم بالعربية', max_length=200)
    name_en = models.CharField('Name (English)', max_length=200, blank=True)
    tax_id = models.CharField('الرقم الضريبي', max_length=50, blank=True)
    commercial_register = models.CharField('السجل التجاري', max_length=50, blank=True)
    address = models.CharField('العنوان', max_length=500, blank=True)
    phone = models.CharField('الهاتف', max_length=50, blank=True)
    email = models.EmailField('البريد', blank=True)
    logo = models.ImageField('الشعار', upload_to='company/', blank=True, null=True)
    default_vat_rate = models.DecimalField('نسبة الضريبة الافتراضية %', max_digits=5, decimal_places=2,
                                            default=Decimal('14.00'))
    currency_code = models.CharField('العملة', max_length=8, default='EGP')

    class Meta:
        verbose_name = 'بيانات الشركة'
        verbose_name_plural = 'بيانات الشركة'

    def __str__(self):
        return self.name_ar or 'Roma'


class Account(models.Model):
    """Chart of accounts entry."""
    TYPE_CHOICES = [
        ('ASSET', 'أصول'),
        ('LIABILITY', 'خصوم'),
        ('EQUITY', 'حقوق ملكية'),
        ('REVENUE', 'إيرادات'),
        ('EXPENSE', 'مصروفات'),
    ]
    code = models.CharField('كود الحساب', max_length=20, unique=True)
    name_ar = models.CharField('اسم الحساب', max_length=200)
    name_en = models.CharField('Name (English)', max_length=200, blank=True)
    account_type = models.CharField('النوع', max_length=20, choices=TYPE_CHOICES)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT,
                                related_name='children', verbose_name='الحساب الأب')
    is_group = models.BooleanField('حساب رئيسي (تجميعي)', default=False)
    is_active = models.BooleanField('نشط', default=True)

    class Meta:
        verbose_name = 'حساب'
        verbose_name_plural = 'دليل الحسابات'
        ordering = ['code']

    def __str__(self):
        return f'{self.code} - {self.name_ar}'


class JournalEntry(models.Model):
    """Header for a balanced set of debit/credit lines."""
    STATUS_CHOICES = [
        ('DRAFT', 'مسودة'),
        ('POSTED', 'مرحّل'),
        ('CANCELLED', 'ملغي'),
    ]
    date = models.DateField('التاريخ')
    reference = models.CharField('المرجع', max_length=100, blank=True)
    description = models.CharField('البيان', max_length=500, blank=True)
    status = models.CharField('الحالة', max_length=10, choices=STATUS_CHOICES, default='POSTED')
    source_doc_type = models.CharField('نوع المستند', max_length=50, blank=True)
    source_doc_id = models.PositiveIntegerField('رقم المستند', null=True, blank=True)
    total_debit = models.DecimalField('إجمالي المدين', max_digits=14, decimal_places=2, default=Decimal('0'))
    total_credit = models.DecimalField('إجمالي الدائن', max_digits=14, decimal_places=2, default=Decimal('0'))
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                                    verbose_name='أنشأ بواسطة')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'قيد يومية'
        verbose_name_plural = 'قيود اليومية'
        ordering = ['-date', '-id']

    def __str__(self):
        return f'JE-{self.id} {self.date}'

    def recalc_totals(self):
        agg = self.lines.aggregate(d=models.Sum('debit'), c=models.Sum('credit'))
        self.total_debit = agg['d'] or Decimal('0')
        self.total_credit = agg['c'] or Decimal('0')
        self.save(update_fields=['total_debit', 'total_credit'])


class JournalLine(models.Model):
    entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name='lines')
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='lines')
    debit = models.DecimalField('مدين', max_digits=14, decimal_places=2, default=Decimal('0'))
    credit = models.DecimalField('دائن', max_digits=14, decimal_places=2, default=Decimal('0'))
    description = models.CharField('البيان', max_length=500, blank=True)
    customer = models.ForeignKey('sales.Customer', null=True, blank=True, on_delete=models.PROTECT,
                                  related_name='journal_lines', verbose_name='العميل')
    variant = models.ForeignKey('inventory.ItemVariant', null=True, blank=True, on_delete=models.PROTECT,
                                 related_name='journal_lines', verbose_name='الصنف')
    supplier = models.ForeignKey('manufacturing.Supplier', null=True, blank=True,
                                  on_delete=models.PROTECT, related_name='journal_lines',
                                  verbose_name='المورد')
    accessory = models.ForeignKey('manufacturing.Accessory', null=True, blank=True,
                                   on_delete=models.PROTECT, related_name='journal_lines',
                                   verbose_name='الإكسسوار')

    class Meta:
        verbose_name = 'بند قيد'
        verbose_name_plural = 'بنود القيود'

    def __str__(self):
        return f'{self.account.code}: D={self.debit} C={self.credit}'


# ============================================================
#  Treasury — cash / bank / e-wallet accounts (item 5)
# ============================================================

class CashAccount(models.Model):
    """خزينة نقدية أو حساب بنكي أو محفظة إلكترونية.

    كل حساب مربوط بحساب في دليل الحسابات (gl_account) تحت مجموعة
    "النقدية والبنوك والمحافظ" (1190000) — بيتعمل تلقائياً عند الإنشاء.
    السندات (قبض / دفع للموردين / مصروفات / شراء أصول) بتختار من أي حساب.
    """
    TYPE_CHOICES = [
        ('CASH', 'نقدية (خزينة)'),
        ('BANK', 'حساب بنكي'),
        ('WALLET', 'محفظة إلكترونية'),
    ]

    name = models.CharField('اسم الحساب', max_length=120,
                            help_text='مثال: خزينة المحل، الأهلي - جاري، فودافون كاش')
    account_type = models.CharField('النوع', max_length=10, choices=TYPE_CHOICES, default='BANK')
    bank_name = models.CharField('اسم البنك / مزود المحفظة', max_length=120, blank=True,
                                  help_text='مثال: البنك الأهلي المصري، فودافون كاش، إنستاباي')
    account_number = models.CharField('رقم الحساب / المحفظة', max_length=60, blank=True)
    gl_account = models.OneToOneField('Account', on_delete=models.PROTECT,
                                       related_name='cash_account', null=True, blank=True,
                                       editable=False, verbose_name='حساب دليل الحسابات')
    is_default = models.BooleanField('الحساب الافتراضي', default=False,
                                      help_text='بيُقترح تلقائياً في السندات الجديدة')
    active = models.BooleanField('نشط', default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'حساب نقدية/بنك/محفظة'
        verbose_name_plural = 'حسابات النقدية والبنوك والمحافظ'
        ordering = ['account_type', 'name']

    def __str__(self):
        return f'{self.name} ({self.get_account_type_display()})'

    @staticmethod
    def _next_gl_code():
        parent = Account.objects.filter(code='1190000').first()
        last = (Account.objects.filter(parent=parent, code__startswith='11900')
                .exclude(code='1190000').order_by('-code').first())
        if last and last.code.isdigit():
            return str(int(last.code) + 1)
        return '1190001'

    def _create_gl_account(self):
        parent = Account.objects.filter(code='1190000').first()
        return Account.objects.create(
            code=self._next_gl_code(),
            name_ar=self.name,
            name_en='',
            account_type='ASSET',
            parent=parent,
            is_group=False,
            is_active=True,
        )

    def save(self, *args, **kwargs):
        if not self.gl_account_id:
            self.gl_account = self._create_gl_account()
        super().save(*args, **kwargs)
        # keep GL account name in sync with the cash-account name
        if self.gl_account_id and self.gl_account.name_ar != self.name:
            self.gl_account.name_ar = self.name
            self.gl_account.save(update_fields=['name_ar'])


# ============================================================
#  Expense vouchers (item 11)
# ============================================================

class ExpenseCategory(models.Model):
    """بند مصروف (رواتب، إيجار، صيانة، مواصلات، ...) مربوط بحساب مصروفات."""
    name_ar = models.CharField('اسم البند', max_length=120, unique=True)
    gl_account = models.ForeignKey('Account', on_delete=models.PROTECT,
                                    related_name='expense_categories',
                                    verbose_name='حساب المصروف',
                                    limit_choices_to={'account_type': 'EXPENSE', 'is_group': False})
    active = models.BooleanField('نشط', default=True)

    class Meta:
        verbose_name = 'بند مصروف'
        verbose_name_plural = 'بنود المصروفات'
        ordering = ['name_ar']

    def __str__(self):
        return self.name_ar


class ExpenseVoucher(models.Model):
    """سند صرف مصروف — يخصم من حساب نقدية ويسجّل المصروف.

    الترحيل: DR حساب المصروف / CR حساب النقدية المختار.
    """
    STATUS_CHOICES = [
        ('DRAFT', 'مسودة'),
        ('POSTED', 'مرحّل'),
        ('CANCELLED', 'ملغي'),
    ]

    voucher_no = models.CharField('رقم السند', max_length=30, unique=True, blank=True,
                                   help_text='سيب الخانة فاضية وهيتولّد تلقائياً (EXP-0001 ...)')
    date = models.DateField('التاريخ')
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT,
                                  related_name='vouchers', verbose_name='بند المصروف')
    description = models.CharField('البيان', max_length=300, blank=True,
                                    help_text='تفاصيل المصروف — مثال: مرتب شهر 5، إيجار المحل')
    amount = models.DecimalField('المبلغ', max_digits=14, decimal_places=2)
    cash_account = models.ForeignKey(CashAccount, on_delete=models.PROTECT,
                                      related_name='expense_vouchers',
                                      verbose_name='مدفوع من (نقدية/بنك/محفظة)')
    reference = models.CharField('المرجع', max_length=100, blank=True)
    notes = models.TextField('ملاحظات', blank=True)
    status = models.CharField('الحالة', max_length=10, choices=STATUS_CHOICES, default='DRAFT')
    journal_entry = models.ForeignKey('JournalEntry', null=True, blank=True,
                                       on_delete=models.SET_NULL, related_name='+', editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'سند صرف مصروف'
        verbose_name_plural = 'سندات صرف المصروفات'
        ordering = ['-date', '-id']

    def __str__(self):
        return f'{self.voucher_no} — {self.category.name_ar}'

    def save(self, *args, **kwargs):
        from core.serials import assign_if_blank
        assign_if_blank(self, 'voucher_no', 'EXP-', 4)
        super().save(*args, **kwargs)


# ============================================================
#  Fixed assets register + purchase (item 10) — no depreciation
# ============================================================

class FixedAsset(models.Model):
    """أصل ثابت — سجل + شراء فقط (من غير إهلاك دلوقتي).

    الترحيل: DR حساب الأصل الثابت (حسب الفئة) / CR نقدية أو مورد (آجل).
    """
    STATUS_CHOICES = [
        ('DRAFT', 'مسودة'),
        ('POSTED', 'مرحّل'),
        ('CANCELLED', 'ملغي'),
    ]
    CATEGORY_CHOICES = [
        ('FURNITURE', 'أثاث ومفروشات'),
        ('MACHINERY', 'آلات ومعدات'),
        ('COMPUTER',  'أجهزة وكمبيوتر'),
        ('VEHICLE',   'سيارات ووسائل نقل'),
        ('OTHER',     'أصول ثابتة أخرى'),
    ]
    CATEGORY_GL = {
        'FURNITURE': '1510000',
        'MACHINERY': '1520000',
        'COMPUTER':  '1530000',
        'VEHICLE':   '1540000',
        'OTHER':     '1590000',
    }
    PAYMENT_CHOICES = [
        ('CASH', 'مدفوع (نقدية/بنك/محفظة)'),
        ('CREDIT', 'آجل (على مورد)'),
    ]

    asset_no = models.CharField('رقم الأصل', max_length=30, unique=True, blank=True,
                                 help_text='سيب الخانة فاضية وهيتولّد تلقائياً (FA-0001 ...)')
    name = models.CharField('اسم الأصل', max_length=200,
                            help_text='مثال: ماكينة أوفر لوك، لاب توب Dell، سيارة نقل')
    category = models.CharField('الفئة', max_length=12, choices=CATEGORY_CHOICES, default='MACHINERY')
    acquisition_date = models.DateField('تاريخ الشراء')
    cost = models.DecimalField('التكلفة', max_digits=14, decimal_places=2)
    payment_method = models.CharField('طريقة الدفع', max_length=10,
                                       choices=PAYMENT_CHOICES, default='CASH')
    cash_account = models.ForeignKey(CashAccount, null=True, blank=True,
                                      on_delete=models.PROTECT, related_name='asset_purchases',
                                      verbose_name='مدفوع من (لو نقدي)',
                                      help_text='إجباري لو طريقة الدفع = مدفوع')
    supplier = models.ForeignKey('manufacturing.Supplier', null=True, blank=True,
                                  on_delete=models.PROTECT, related_name='asset_purchases',
                                  verbose_name='المورد (لو آجل)',
                                  help_text='إجباري لو طريقة الدفع = آجل')
    supplier_invoice_no = models.CharField('رقم فاتورة المورد', max_length=50, blank=True,
                                           help_text='لو اشتريت أكتر من أصل (مكن/معدات) على نفس فاتورة '
                                                     'المورد، اكتب نفس الرقم في كل أصل عشان تعرف إنهم مع بعض')
    serial_number = models.CharField('الرقم التسلسلي', max_length=100, blank=True)
    location = models.CharField('المكان', max_length=200, blank=True)
    notes = models.TextField('ملاحظات', blank=True)
    status = models.CharField('الحالة', max_length=10, choices=STATUS_CHOICES, default='DRAFT')
    journal_entry = models.ForeignKey('JournalEntry', null=True, blank=True,
                                       on_delete=models.SET_NULL, related_name='+', editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'أصل ثابت'
        verbose_name_plural = 'الأصول الثابتة'
        ordering = ['-acquisition_date', '-id']

    def __str__(self):
        return f'{self.asset_no} — {self.name}'

    def save(self, *args, **kwargs):
        from core.serials import assign_if_blank
        assign_if_blank(self, 'asset_no', 'FA-', 4)
        super().save(*args, **kwargs)

    @property
    def gl_code(self):
        return self.CATEGORY_GL.get(self.category, '1590000')
