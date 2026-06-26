from decimal import Decimal
from django.db import models
from django.conf import settings


# Natural clothing-size order — used for sorting variants in lists, prints, reports.
# Roma sells mixed-collection items: numeric sizes (10, 12, 14) AND letter sizes (S, M, L, XL).
# Letters are offset to 100+ so numeric sizes (typical: 2..50) sort first naturally.
LETTER_SIZE_ORDER = {'XS': 100, 'S': 101, 'M': 102, 'L': 103, 'XL': 104, 'XXL': 105, 'XXXL': 106, 'XXXXL': 107}


def size_sort_key(size: str) -> int:
    """Return an integer rank for a size string. Numeric sizes sort first (10, 12, ...),
    then letter sizes (S, M, L, ...), then unknown sizes."""
    if not size:
        return 999
    s = size.strip().upper()
    try:
        return int(float(s))
    except ValueError:
        return LETTER_SIZE_ORDER.get(s, 999)


class Product(models.Model):
    """منتج رئيسي (مجموعة) — مثال: «تيشرت أندية». تحته منتجات فرعية (Item) قابلة
    للبيع والتخزين، والوصفة (قماش + هالك + إكسسوارات + مصنعية) لكل مقاس بتتعرّف على
    المنتج الرئيسي وبتغذّي أوامر إنتاج كل المنتجات الفرعية التابعة له."""
    PRODUCT_TYPE_CHOICES = [
        ('MANUFACTURING', 'منتج تصنيع'),
        ('FINISHED', 'منتج تام'),
    ]
    WHOLESALE_UNIT_CHOICES = [
        ('DOZEN', 'دستة'),
        ('CARTON', 'كرتونة'),
    ]
    code = models.CharField('كود المنتج', max_length=20, unique=True, blank=True,
                            help_text='سيب الخانة فاضية وهيتولّد تلقائياً (PRD-0001, PRD-0002 ...)')
    name_ar = models.CharField('اسم المنتج', max_length=200)
    name_en = models.CharField('Name (English)', max_length=200, blank=True)
    product_type = models.CharField('نوع المنتج', max_length=15, choices=PRODUCT_TYPE_CHOICES,
                                    default='MANUFACTURING',
                                    help_text='«تصنيع» = له وصفة وبيتصنّع بأوامر إنتاج. '
                                              '«تام» = بيتشترى جاهز ويتباع زي ما هو. لو اخترت «تام» '
                                              'هيتعمل منتج فرعي تلقائي بنفس الاسم تقدر تبيع منه.')
    wholesale_unit = models.CharField('وحدة الجملة', max_length=10, choices=WHOLESALE_UNIT_CHOICES,
                                      default='DOZEN',
                                      help_text='الوحدة اللي بتبيع بيها بالجملة — دستة ولا كرتونة. '
                                                'بتظهر في الفاتورة جنب «قطعة».')
    wholesale_unit_size = models.PositiveSmallIntegerField('عدد القطع في وحدة الجملة', default=12,
                                                           help_text='كام قطعة في وحدة الجملة '
                                                                     '(الدستة أو الكرتونة).')
    category = models.CharField('الفئة', max_length=100, blank=True)
    fabric_type = models.ForeignKey('manufacturing.FabricType', null=True, blank=True,
                                    on_delete=models.PROTECT, related_name='products',
                                    verbose_name='نوع القماش/الخامة',
                                    help_text='نوع القماش/الخامة المستخدمة في تصنيع المنتج ده '
                                              '(من كتالوج «أنواع الأقمشة»).')
    dozen_size = models.PositiveSmallIntegerField('عدد القطع في الدستة', default=12,
                                                  help_text='الدستة = وحدة البيع الافتراضية. '
                                                            'بتتطبّق على كل المنتجات الفرعية التابعة '
                                                            'للمنتج ده.')
    waste_pct = models.DecimalField('نسبة هالك القماش % (للمنتج كله)', max_digits=5, decimal_places=2,
                                    default=Decimal('0'),
                                    help_text='نسبة الزيادة على القماش بسبب الهالك — بتتحسب على '
                                              'المنتج كله مش لكل مقاس. مثال: 5 يعني الكمية المستخدمة '
                                              'بالهالك = الكمية قبل الهالك × 1.05.')
    accessory_waste_pct = models.DecimalField('نسبة هالك الإكسسوارات % (للمنتج كله)',
                                              max_digits=5, decimal_places=2,
                                              default=Decimal('5'),
                                              help_text='نسبة الزيادة على استهلاك الإكسسوارات بسبب '
                                                        'الهالك في الإنتاج. مثال: 5 يعني الكمية '
                                                        'المستهلكة = كمية الوصفة × 1.05.')
    notes = models.TextField('ملاحظات', blank=True)
    active = models.BooleanField('نشط', default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'منتج'
        verbose_name_plural = 'المنتجات'
        ordering = ['code']

    def __str__(self):
        return f'{self.code} - {self.name_ar}'

    def save(self, *args, **kwargs):
        from core.serials import assign_if_blank
        assign_if_blank(self, 'code', 'PRD-', 4)
        # وحدة الجملة بقت هي المصدر الوحيد — «عدد القطع في الدستة» القديم بيتبعها
        # تلقائياً عشان الكود الداخلي القديم يفضل متّسق (الخانة اتشالت من الفورم).
        self.dozen_size = self.wholesale_unit_size or 12
        super().save(*args, **kwargs)
        # The main product is the authoritative source of the wholesale unit + the
        # per-size recipe (sizes + selling price). Propagate to every sub-product
        # so their cached unit + SKUs stay in sync.
        for item in self.sub_products.all():
            sync_variants_from_recipe(item)


class Item(models.Model):
    """منتج فرعي (وحدة البيع/التخزين) — مثال: «تيشرت الأهلي الأحمر موسم 2026».
    تابع لـ Product (منتج رئيسي)، وله SKU لكل مقاس (ItemVariant)."""
    product = models.ForeignKey('Product', null=True, blank=True, on_delete=models.PROTECT,
                                related_name='sub_products', verbose_name='المنتج الرئيسي',
                                help_text='المنتج اللي المنتج الفرعي ده تابع له. الوصفة '
                                          '(قماش/هالك/مصنعية) بتتعرّف على المنتج الرئيسي.')
    code = models.CharField('كود الموديل', max_length=20, unique=True,
                             blank=True,
                             help_text='سيب الخانة فاضية وهيتولّد تلقائياً (ITM-0001, ITM-0002 ...)')
    name_ar = models.CharField('الاسم', max_length=200)
    name_en = models.CharField('Name (English)', max_length=200, blank=True)
    category = models.CharField('الفئة', max_length=100, blank=True)
    fabric = models.CharField('الخامة', max_length=100, blank=True,
                              help_text='مثال: قطن 100%، بوليستر، حرير، صوف، خليط')
    fabric_color = models.ForeignKey('manufacturing.FabricColor', null=True, blank=True,
                                     on_delete=models.PROTECT, related_name='items',
                                     verbose_name='لون القماش المستخدم',
                                     help_text='اللون اللي بيتخصم من مخزون القماش وقت الإنتاج. '
                                               'المخزون متخزّن باللون، فلازم تختار اللون عشان '
                                               'الخصم يبقى من نفس اللون الصح. (للأطقم = لون الفانلة.)')
    shorts_fabric_color = models.ForeignKey('manufacturing.FabricColor', null=True, blank=True,
                                            on_delete=models.PROTECT, related_name='items_shorts',
                                            verbose_name='لون قماش الشورت',
                                            help_text='للأطقم بس: لون قماش الشورت اللي هيتخصم منه '
                                                      'قماش الشورت وقت الإنتاج. سيبه فاضي لو المنتج '
                                                      'مش طقم بلونين.')
    description = models.TextField('الوصف', blank=True)
    dozen_size = models.PositiveSmallIntegerField('عدد القطع في الدستة', default=12,
                                                     help_text='الدستة = الوحدة الافتراضية للبيع. '
                                                               'مقاس واحد فيها 12 قطعة عادة.')
    image = models.ImageField('الصورة', upload_to='items/', blank=True, null=True)
    active = models.BooleanField('نشط', default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'منتج فرعي'
        verbose_name_plural = 'المنتجات الفرعية'
        ordering = ['code']

    def __str__(self):
        return f'{self.code} - {self.name_ar}'

    def save(self, *args, **kwargs):
        from core.serials import assign_if_blank
        assign_if_blank(self, 'code', 'ITM-', 4)
        # The main product owns the dozen size — mirror it onto this cache so the
        # INSERT/UPDATE carries the right value without an extra write.
        if self.product_id and self.product.dozen_size:
            self.dozen_size = self.product.dozen_size
        super().save(*args, **kwargs)
        # Now that we have a PK + code, materialize one SKU per recipe size from
        # the main product (no manual size entry — sizes come from the recipe).
        if self.product_id:
            sync_variants_from_recipe(self)


def sync_variants_from_recipe(item):
    """Refresh a sub-product (Item) from its MAIN product — the authoritative source.

    The main product owns the sizes, the per-size selling price, the per-size reorder
    level, and the dozen size; the sub-product only adds a selling name + image. So here we:
      * copy the main product's dozen size onto the item cache,
      * make sure every recipe size has a matching SKU (ItemVariant),
      * push the recipe's per-size selling price + reorder level onto each SKU.

    We never DELETE SKUs — StockMovement.variant is PROTECT and old SKUs may carry
    stock/history; a size removed from the recipe simply stops being auto-managed.
    A price is only overwritten when the recipe carries a non-zero price, so existing
    prices are never wiped while data is still being migrated.
    """
    product = item.product if item.product_id else None
    if product is None:
        return
    # 1) dozen-size cache — queryset update so we don't recurse into Item.save().
    if product.dozen_size and item.dozen_size != product.dozen_size:
        item.dozen_size = product.dozen_size
        Item.objects.filter(pk=item.pk).update(dozen_size=product.dozen_size)
    # 2) one SKU per recipe size; reprice + re-flag reorder from the recipe.
    existing = {v.size: v for v in item.variants.all()}
    for recipe in product.size_recipes.select_related('size').all():
        size_code = recipe.size.code
        price = recipe.selling_price or Decimal('0')
        reorder = recipe.reorder_level or Decimal('0')
        variant = existing.get(size_code)
        if variant is None:
            ItemVariant.objects.create(item=item, size=size_code, selling_price=price,
                                       reorder_level=reorder)
            continue
        changed = []
        if price and variant.selling_price != price:
            variant.selling_price = price
            changed.append('selling_price')
        if variant.reorder_level != reorder:
            variant.reorder_level = reorder
            changed.append('reorder_level')
        if changed:
            variant.save(update_fields=changed)


class ItemVariant(models.Model):
    """SKU = item × size. Holds cached stock + WAC; refreshed by StockMovement.apply()."""
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='variants',
                              verbose_name='المنتج الفرعي')
    size = models.CharField('المقاس', max_length=10,
                            help_text='مقاس حر — مثال: S, M, L, XL, XXL أو 10, 12, 14, 16')
    sku_code = models.CharField('كود SKU', max_length=40, unique=True, blank=True)
    barcode = models.CharField('الباركود', max_length=50, blank=True)
    current_stock = models.DecimalField('الرصيد الحالي', max_digits=12, decimal_places=2,
                                         default=Decimal('0'))
    average_cost = models.DecimalField('متوسط التكلفة', max_digits=12, decimal_places=4,
                                        default=Decimal('0'))
    selling_price = models.DecimalField('سعر البيع (للقطعة)', max_digits=12, decimal_places=2,
                                          default=Decimal('0'),
                                          help_text='سعر بيع القطعة الواحدة من المقاس ده. '
                                                    'سعر الدستة = ده × عدد القطع في الدستة.')
    reorder_level = models.DecimalField('حد إعادة الطلب (بالقطعة)', max_digits=12, decimal_places=2,
                                         default=Decimal('0'),
                                         help_text='لما رصيد القطع ينزل عن العدد ده، '
                                                   'يبقى وقت تطلب/تنتج تاني.')
    # Numeric rank for size ordering — auto-set in save() from size_sort_key().
    # Numbers first (10, 12, 14...), then letters (S, M, L, XL...). Never edited directly.
    size_order = models.PositiveSmallIntegerField(default=999, editable=False)

    class Meta:
        verbose_name = 'SKU'
        verbose_name_plural = 'الـ SKUs'
        unique_together = [('item', 'size')]
        ordering = ['item__code', 'size_order']  # numeric sizes first, then S, M, L, XL...

    def __str__(self):
        return self.sku_code or f'{self.item.code}-{self.size}'

    def save(self, *args, **kwargs):
        if not self.sku_code:
            self.sku_code = f'ROM-{self.item.code}-{self.size}'
        self.size_order = size_sort_key(self.size)
        super().save(*args, **kwargs)


class StockMovement(models.Model):
    """Append-only log of every stock change. Posting this row updates ItemVariant cache."""
    MOVEMENT_TYPES = [
        ('OPENING', 'رصيد افتتاحي'),
        ('PURCHASE_IN', 'إدخال مشتريات'),
        ('SALES_OUT', 'صرف مبيعات'),
        ('SALES_RETURN_IN', 'مرتجع مبيعات'),
        ('PURCHASE_RETURN_OUT', 'مرتجع مشتريات'),
        ('ADJUST_IN', 'تسوية موجبة'),
        ('ADJUST_OUT', 'تسوية سالبة'),
        ('WASTE', 'هالك / تالف'),
    ]
    IN_TYPES = {'OPENING', 'PURCHASE_IN', 'SALES_RETURN_IN', 'ADJUST_IN'}

    variant = models.ForeignKey(ItemVariant, on_delete=models.PROTECT, related_name='movements',
                                 verbose_name='الصنف')
    date = models.DateField('التاريخ')
    movement_type = models.CharField('نوع الحركة', max_length=30, choices=MOVEMENT_TYPES)
    quantity = models.DecimalField('الكمية', max_digits=12, decimal_places=2)
    unit_cost = models.DecimalField('تكلفة الوحدة', max_digits=12, decimal_places=4,
                                     default=Decimal('0'),
                                     help_text='للحركات الواردة فقط (تستخدم في حساب متوسط التكلفة)')
    document_type = models.CharField('نوع المستند', max_length=50, blank=True)
    document_id = models.PositiveIntegerField('رقم المستند', null=True, blank=True)
    notes = models.CharField('ملاحظات', max_length=500, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'حركة مخزون'
        verbose_name_plural = 'حركات المخزون'
        ordering = ['-date', '-id']
        indexes = [
            models.Index(fields=['variant', 'date']),
            models.Index(fields=['document_type', 'document_id']),
        ]

    def __str__(self):
        return f'{self.variant} {self.movement_type} qty={self.quantity}'

    @property
    def is_inbound(self):
        return self.movement_type in self.IN_TYPES

    def apply_to_variant(self):
        v = self.variant
        qty = Decimal(self.quantity)
        if self.is_inbound:
            old_stock = v.current_stock
            old_cost = v.average_cost
            new_stock = old_stock + qty
            if old_stock <= 0:
                # مفيش رصيد سابق صحيح يتمزج بيه (صفر أو سالب) — المتوسط = تكلفة الوارد.
                # ده بيمنع تلف متوسط التكلفة لو الرصيد كان وصل سالب بالغلط.
                v.average_cost = Decimal(self.unit_cost)
            elif new_stock > 0:
                v.average_cost = ((old_stock * old_cost) + (qty * Decimal(self.unit_cost))) / new_stock
            v.current_stock = new_stock
        else:
            v.current_stock = v.current_stock - qty
        v.save(update_fields=['current_stock', 'average_cost'])


class FinishedGoodsPurchaseInvoice(models.Model):
    """فاتورة شراء منتجات تامة جاهزة (تجارة) — هيدر واحد (مورد + رقم + تاريخ + دفع)
    وتحته كذا بند (FinishedGoodsPurchaseLine لكل SKU).

    الترحيل بيعمل قيد محاسبي **واحد** للفاتورة كلها:
        DR  المخزون (منتجات تامة)        إجمالي البنود
        CR  نقدية/بنك/محفظة أو مورد آجل   إجمالي البنود
    وكل بند بيزوّد رصيد الـ SKU ويحدّث متوسط تكلفته (WAC) بحركة PURCHASE_IN.
    البيع بعد كده بيشتغل عادي (COGS من متوسط التكلفة).
    """
    PAYMENT_CHOICES = [
        ('CASH', 'مدفوع (نقدية/بنك/محفظة)'),
        ('CREDIT', 'آجل (على المورد)'),
    ]

    invoice_no = models.CharField('رقم الفاتورة', max_length=30, unique=True, blank=True,
                                  help_text='سيب الخانة فاضية وهيتولّد تلقائياً (FGP-0001 ...)')
    supplier = models.ForeignKey('manufacturing.Supplier', null=True, blank=True,
                                 on_delete=models.PROTECT, related_name='finished_goods_invoices',
                                 verbose_name='المورد',
                                 limit_choices_to={'vendor_type__code': 'FINISHED_GOODS'},
                                 help_text='إجباري لو الفاتورة آجلة')
    supplier_ref = models.CharField('رقم فاتورة المورد', max_length=50, blank=True,
                                    help_text='رقم الفاتورة الورقية اللي جايه من المورد (اختياري)')
    date = models.DateField('تاريخ الفاتورة')
    payment_method = models.CharField('طريقة الدفع', max_length=10,
                                      choices=PAYMENT_CHOICES, default='CASH')
    cash_account = models.ForeignKey('core.CashAccount', null=True, blank=True,
                                     on_delete=models.PROTECT, related_name='finished_goods_invoices',
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
        verbose_name = 'فاتورة شراء منتجات تامة'
        verbose_name_plural = 'مشتريات المنتجات التامة (تجارة)'
        ordering = ['-date', '-id']

    def __str__(self):
        return self.invoice_no or f'FGP-{self.pk}'

    def save(self, *args, **kwargs):
        from core.serials import assign_if_blank
        assign_if_blank(self, 'invoice_no', 'FGP-', 4)
        super().save(*args, **kwargs)

    @property
    def total(self):
        return sum((l.total_cost for l in self.lines.all()), Decimal('0'))


class FinishedGoodsPurchaseLine(models.Model):
    """بند في فاتورة شراء منتجات تامة — SKU واحد بكمية وتكلفة (بالقطعة أو بوحدة الجملة)."""
    PURCHASE_UNIT_CHOICES = [('PIECE', 'قطعة'), ('WHOLESALE', 'وحدة الجملة')]

    invoice = models.ForeignKey(FinishedGoodsPurchaseInvoice, on_delete=models.CASCADE,
                                related_name='lines', verbose_name='الفاتورة')
    variant = models.ForeignKey(ItemVariant, on_delete=models.PROTECT,
                                related_name='purchase_lines', verbose_name='المنتج (SKU)')
    purchase_unit = models.CharField('وحدة الشراء', max_length=10,
                                     choices=PURCHASE_UNIT_CHOICES, default='WHOLESALE',
                                     help_text='بتشتري بالقطعة ولا بوحدة الجملة (دستة/كرتونة). '
                                               'بيتخزّن في المخزون بالقطعة تلقائياً.')
    quantity = models.DecimalField('الكمية (بالوحدة)', max_digits=12, decimal_places=2)
    unit_cost = models.DecimalField('تكلفة الوحدة', max_digits=12, decimal_places=4,
                                    help_text='تكلفة القطعة أو الكرتونة/الدستة حسب وحدة الشراء.')
    is_posted = models.BooleanField('مرحّل', default=False, editable=False)

    class Meta:
        verbose_name = 'بند منتج تام'
        verbose_name_plural = 'بنود المنتجات التامة'

    def __str__(self):
        return f'{self.variant} × {self.quantity}'

    @property
    def _product(self):
        if self.variant_id and self.variant.item_id and self.variant.item.product_id:
            return self.variant.item.product
        return None

    @property
    def unit_factor(self):
        """عدد القطع في وحدة الشراء (قطعة=1، وحدة الجملة=wholesale_unit_size)."""
        if self.purchase_unit == 'WHOLESALE':
            p = self._product
            return Decimal((p.wholesale_unit_size or 0) if p else 0)
        return Decimal('1')

    @property
    def pieces_in(self):
        """عدد القطع الفعلية اللي هتدخل المخزون = الكمية × عدد القطع في الوحدة."""
        return (Decimal(self.quantity or 0) * self.unit_factor).quantize(Decimal('0.01'))

    @property
    def piece_cost(self):
        """تكلفة القطعة = تكلفة الوحدة ÷ عدد القطع في الوحدة."""
        f = self.unit_factor
        return (Decimal(self.unit_cost or 0) / f).quantize(Decimal('0.0001')) if f > 0 else Decimal('0')

    @property
    def total_cost(self):
        return (Decimal(self.quantity or 0)
                * Decimal(self.unit_cost or 0)).quantize(Decimal('0.01'))


# ------------------------------------------------------------------ Stock-take
class StockTake(models.Model):
    """جرد مخزون — تعدّ الكميات الفعلية وتقارنها برصيد النظام، والترحيل بيرحّل العجز/الزيادة
    على حساب «فروق جرد» (5210000):
        زيادة: DR المخزون / CR فروق جرد
        عجز:   DR فروق جرد / CR المخزون
    كل بند بيظبط رصيد الصنف على الكمية المعدودة بحركة ADJUST_IN/ADJUST_OUT.
    """
    take_no = models.CharField('رقم الجرد', max_length=30, unique=True, blank=True,
                               help_text='سيب الخانة فاضية وهيتولّد تلقائياً (ST-0001 ...)')
    date = models.DateField('تاريخ الجرد')
    notes = models.TextField('ملاحظات', blank=True)
    is_posted = models.BooleanField('مرحّل محاسبياً', default=False, editable=False)
    journal_entry = models.ForeignKey('core.JournalEntry', null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name='+', editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'جرد مخزون'
        verbose_name_plural = 'جرد المخزون'
        ordering = ['-date', '-id']

    def __str__(self):
        return self.take_no or f'ST-{self.pk}'

    def save(self, *args, **kwargs):
        from core.serials import assign_if_blank
        assign_if_blank(self, 'take_no', 'ST-', 4)
        super().save(*args, **kwargs)

    @property
    def total_variance_value(self):
        return sum((l.variance_value for l in self.lines.all()), Decimal('0'))


class StockTakeLine(models.Model):
    """بند جرد — صنف واحد بالكمية الفعلية المعدودة."""
    stock_take = models.ForeignKey(StockTake, on_delete=models.CASCADE,
                                   related_name='lines', verbose_name='الجرد')
    item = models.ForeignKey(Item, null=True, blank=True, on_delete=models.PROTECT,
                             related_name='+', verbose_name='الصنف',
                             help_text='اختار المنتج الأول، وبعدين المقاس هيتفلتر عليه.')
    variant = models.ForeignKey(ItemVariant, on_delete=models.PROTECT,
                                related_name='stock_take_lines', verbose_name='المقاس')
    counted_qty = models.DecimalField('الكمية الفعلية المعدودة', max_digits=12, decimal_places=2)
    system_qty_at_post = models.DecimalField('رصيد النظام وقت الترحيل', max_digits=12,
                                             decimal_places=2, null=True, blank=True, editable=False)
    is_posted = models.BooleanField('مرحّل', default=False, editable=False)

    class Meta:
        verbose_name = 'بند جرد'
        verbose_name_plural = 'بنود الجرد'

    def __str__(self):
        return f'{self.variant} — عدّ {self.counted_qty}'

    def save(self, *args, **kwargs):
        # المقاس (variant) هو المرجع — اشتق منه الصنف عشان يفضلوا متسقين.
        if self.variant_id:
            self.item_id = self.variant.item_id
        super().save(*args, **kwargs)

    @property
    def system_qty(self):
        """رصيد النظام: المخزّن وقت الترحيل لو مرحّل، وإلا الرصيد الحالي."""
        if self.is_posted and self.system_qty_at_post is not None:
            return Decimal(self.system_qty_at_post)
        return Decimal(self.variant.current_stock or 0) if self.variant_id else Decimal('0')

    @property
    def variance(self):
        return (Decimal(self.counted_qty or 0) - self.system_qty).quantize(Decimal('0.01'))

    @property
    def variance_value(self):
        cost = Decimal(self.variant.average_cost or 0) if self.variant_id else Decimal('0')
        return (self.variance * cost).quantize(Decimal('0.01'))
