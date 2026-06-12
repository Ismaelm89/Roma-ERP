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
    code = models.CharField('كود المنتج', max_length=20, unique=True, blank=True,
                            help_text='سيب الخانة فاضية وهيتولّد تلقائياً (PRD-0001, PRD-0002 ...)')
    name_ar = models.CharField('اسم المنتج', max_length=200)
    name_en = models.CharField('Name (English)', max_length=200, blank=True)
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
        super().save(*args, **kwargs)
        # The main product is the authoritative source of the dozen size + the
        # per-size recipe (sizes + selling price). Propagate to every sub-product
        # so their cached dozen size + SKUs stay in sync.
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
                                               'الخصم يبقى من نفس اللون الصح.')
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
    reorder_level = models.DecimalField('حد إعادة الطلب (بالدستة)', max_digits=12, decimal_places=2,
                                         default=Decimal('0'),
                                         help_text='لما الرصيد ينزل عن العدد ده من الدستات، '
                                                   'يبقى وقت تطلب تاني.')
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
            if new_stock > 0:
                v.average_cost = ((old_stock * old_cost) + (qty * Decimal(self.unit_cost))) / new_stock
            v.current_stock = new_stock
        else:
            v.current_stock = v.current_stock - qty
        v.save(update_fields=['current_stock', 'average_cost'])
