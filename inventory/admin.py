from django import forms
from django.contrib import admin, messages
from django.urls import reverse
from django.utils.html import format_html

from core.admin_mixins import StayOnPageMixin, LockAfterPostMixin
from core.templatetags.money_filters import fmt_money

from manufacturing.models import ProductSizeRecipe

from .models import (Item, ItemVariant, Product, StockMovement,
                     FinishedGoodsPurchaseInvoice, FinishedGoodsPurchaseLine)
from .services import (post_finished_goods_purchase_invoice,
                       FinishedGoodsPostingError)


class ItemVariantForm(forms.ModelForm):
    """Renders `size` as a dropdown sourced from the manufacturing Size master,
    while keeping it a plain CharField in the DB (so sales code is untouched)."""
    class Meta:
        model = ItemVariant
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # لو المقاس معروض «للقراءة فقط» (منتج مُصنّع) بيكون مستبعَد من الفورم —
        # ساعتها ما نضيفوش تاني كحقل مطلوب، وإلا الحفظ بيفشل بـ«المقاس مطلوب».
        if 'size' not in self.fields:
            return
        from manufacturing.models import Size
        codes = list(Size.objects.filter(active=True)
                     .order_by('sort_order', 'code').values_list('code', flat=True))
        current = self.instance.size if (self.instance and self.instance.pk) else None
        if current and current not in codes:
            codes.append(current)  # keep legacy/unknown size selectable
        choices = [('', '— اختار مقاس —')] + [(c, c) for c in codes]
        self.fields['size'] = forms.ChoiceField(choices=choices, label='المقاس',
                                                 required=True)


class ItemVariantInline(admin.TabularInline):
    """SKUs (المقاسات).

    تابع لمنتج رئيسي «تصنيع»: للعرض فقط — المقاسات والسعر بييجوا من وصفة المنتج الرئيسي.
    تابع لمنتج رئيسي «تام» (أو من غير رئيسي): قابل للإضافة والتعديل — تكتب المقاس وسعر البيع
    بإيدك، والتكلفة بتتحدّد من فاتورة شراء المنتجات التامة (متوسط مرجّح)."""
    model = ItemVariant
    form = ItemVariantForm
    extra = 0
    # full read-only set (manufactured item) vs editable set (finished/trading item)
    _ALL = ('size', 'sku_code', 'selling_price', 'dozen_price_col',
            'current_stock', 'average_cost', 'barcode', 'reorder_level')
    _COMPUTED = ('sku_code', 'dozen_price_col', 'current_stock', 'average_cost')
    fields = _ALL

    @staticmethod
    def _is_trading(obj):
        # Editable when the item is FINISHED/trading: a new item, an item with no
        # main product, or an item whose main product is FINISHED (bought ready).
        # Read-only only when the main product is MANUFACTURING (sizes come from
        # its recipe).
        if obj is None or obj.product_id is None:
            return True
        return obj.product.product_type == 'FINISHED'

    def has_add_permission(self, request, obj=None):
        return self._is_trading(obj)

    def has_delete_permission(self, request, obj=None):
        return self._is_trading(obj)

    def get_readonly_fields(self, request, obj=None):
        return self._COMPUTED if self._is_trading(obj) else self._ALL

    def dozen_price_col(self, obj):
        if obj and obj.pk and obj.selling_price:
            dz = obj.item.dozen_size or 12
            return f'{fmt_money(obj.selling_price * dz)} ج / الدستة ({dz})'
        return '—'
    dozen_price_col.short_description = 'سعر الدستة'


class ProductSizeRecipeInline(admin.TabularInline):
    """وصفة المنتج لكل مقاس: كمية القماش + المصنعية + السعر + حد إعادة الطلب.
    نسبة الهالك بقت على المنتج كله (مش لكل مقاس) — موجودة فوق في بيانات المنتج.
    الإكسسوارات بتتدار من صفحة الوصفة نفسها (رابط 'إكسسوارات المقاس')."""
    model = ProductSizeRecipe
    extra = 1
    fields = ('size', 'fabric_qty_kg', 'labor_cost', 'selling_price',
              'reorder_level', 'accessories_link', 'notes')
    readonly_fields = ('accessories_link',)
    autocomplete_fields = ('size',)

    def accessories_link(self, obj):
        if not obj or not obj.pk:
            return format_html('<span style="color:#999;font-size:11px;">احفظ الأول عشان '
                               'تضيف إكسسوارات</span>')
        url = reverse('admin:manufacturing_productsizerecipe_change', args=[obj.pk])
        return format_html('<a href="{}">إكسسوارات ({})</a>', url, obj.accessories.count())
    accessories_link.short_description = 'إكسسوارات المقاس'


@admin.register(Product)
class ProductAdmin(StayOnPageMixin, admin.ModelAdmin):
    list_display = ('code', 'name_ar', 'product_type', 'wholesale_unit', 'fabric_type',
                    'sub_products_count', 'recipe_sizes_count', 'active')
    list_display_links = ('code', 'name_ar')
    list_filter = ('product_type', 'active', 'fabric_type', 'category')
    search_fields = ('code', 'name_ar', 'name_en')
    readonly_fields = ('code',)
    autocomplete_fields = ('fabric_type',)
    inlines = [ProductSizeRecipeInline]
    fieldsets = (
        ('بيانات المنتج', {
            'fields': ('code', 'name_ar', 'name_en', 'product_type', 'category',
                       'notes', 'active'),
            'description': 'اختار «نوع المنتج»: «تصنيع» له وصفة وبيتصنّع؛ «تام» بيتشترى جاهز '
                           '— ولو اخترت «تام» هيتعمل منتج فرعي تلقائي بنفس الاسم تبيع منه.',
        }),
        ('وحدة الجملة', {
            'fields': ('wholesale_unit', 'wholesale_unit_size'),
            'description': 'وحدة البيع بالجملة (دستة/كرتونة) + عدد القطع فيها — بتظهر في '
                           'الفاتورة جنب «قطعة».',
        }),
        ('وصفة التصنيع (للمنتج التصنيع فقط)', {
            'fields': ('fabric_type', 'waste_pct', 'accessory_waste_pct'),
            'description': 'نوع القماش ونسبتي الهالك — بتتطبّق على منتجات التصنيع وبتغذّي '
                           'جدول الوصفة لكل مقاس تحت. سيبها فاضية للمنتج التام.',
        }),
    )

    def get_inline_instances(self, request, obj=None):
        # وصفة المقاسات تظهر لمنتجات التصنيع بس (المنتج التام مالوش وصفة).
        if obj is not None and obj.product_type == 'FINISHED':
            return []
        return super().get_inline_instances(request, obj)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        product = form.instance
        # منتج تام: اعمل منتج فرعي تلقائي بنفس الاسم (لو لسه مفيش) عشان تبيع منه.
        if product.product_type == 'FINISHED' and not product.sub_products.exists():
            Item.objects.create(product=product, name_ar=product.name_ar,
                                category=product.category)
            messages.info(request,
                          f'اتعمل منتج فرعي تلقائي «{product.name_ar}» — ضيف مقاساته وأسعاره منه.')

    def sub_products_count(self, obj):
        return obj.sub_products.count()
    sub_products_count.short_description = 'منتجات فرعية'

    def recipe_sizes_count(self, obj):
        return obj.size_recipes.count()
    recipe_sizes_count.short_description = 'مقاسات بوصفة'


@admin.register(Item)
class ItemAdmin(StayOnPageMixin, admin.ModelAdmin):
    list_display = ('image_thumb', 'code', 'product', 'name_ar', 'variants_count',
                    'dozen_size', 'active')
    list_display_links = ('code', 'name_ar')
    list_filter = ('active', 'product')
    search_fields = ('code', 'name_ar', 'name_en')
    autocomplete_fields = ('product',)
    inlines = [ItemVariantInline]
    readonly_fields = ('code', 'image_preview', 'inherited_summary', 'sub_type_note')
    fieldsets = (
        ('بيانات المنتج الفرعي', {
            'fields': ('product', 'sub_type_note', 'inherited_summary', 'code', 'name_ar',
                       'fabric_color', 'active'),
            'description': 'المنتج الفرعي = اسم بيعي + صورة + لون القماش. اختار «المنتج الرئيسي» '
                           'وهو هيجيب المقاسات والأسعار والوصفة (قماش/إكسسوارات/مصنعية) '
                           'تلقائياً — المقاسات بتظهر تحت كـ SKUs للعرض فقط. '
                           'و«لون القماش المستخدم» مهم: ده اللون اللي بيتخصم من مخزون '
                           'القماش وقت الإنتاج (المخزون متخزّن باللون).',
        }),
        ('الصورة', {
            'fields': ('image', 'image_preview'),
            'description': 'الصورة بتظهر في تقارير المنتجات والمبيعات.',
        }),
    )

    def inherited_summary(self, obj):
        """عرض مختصر لكل اللي بييجي من المنتج الرئيسي (للتوضيح، مش قابل للتعديل هنا)."""
        if not obj or not obj.product_id:
            return format_html('<span style="color:#999;">اختار المنتج الرئيسي واحفظ — '
                               'المقاسات والأسعار هتتولّد منه تلقائياً.</span>')
        p = obj.product
        sizes = p.size_recipes.count()
        fabric = p.fabric_type.name_ar if p.fabric_type_id else '—'
        return format_html(
            '<div style="font-size:12px;line-height:1.8;">'
            'نوع القماش/الخامة: <b>{}</b><br>'
            'عدد القطع في الدستة: <b>{}</b><br>'
            'مقاسات بوصفة (SKUs هتتولّد): <b>{}</b>'
            '</div>', fabric, p.dozen_size, sizes)
    inherited_summary.short_description = 'بيتورّث من المنتج الرئيسي'

    def sub_type_note(self, obj):
        """كل المنتجات الفرعية «منتج تام» (طبقة البيع) — للتوضيح فقط."""
        kind = ('تابع لمنتج رئيسي «تصنيع» — مقاساته وأسعاره بتيجي من الوصفة.'
                if obj and obj.product_id and obj.product.product_type == 'MANUFACTURING'
                else 'تام بيتشترى جاهز — تكتب مقاساته وسعره بإيدك.')
        return format_html(
            '<span style="background:#e7f5ec;color:#15803d;font-weight:700;'
            'padding:2px 8px;border-radius:4px;">منتج تام (قابل للبيع)</span>'
            '<span style="color:#666;font-size:11px;margin-right:6px;">— {}</span>', kind)
    sub_type_note.short_description = 'النوع'

    def variants_count(self, obj):
        return obj.variants.count()
    variants_count.short_description = 'مقاسات (SKUs)'

    def image_thumb(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="height:40px;width:40px;'
                                'object-fit:cover;border-radius:4px;">', obj.image.url)
        return format_html('<span style="color:#999;font-size:11px;">بدون صورة</span>')
    image_thumb.short_description = 'صورة'

    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="max-width:200px;max-height:200px;'
                                'border:1px solid #ddd;border-radius:6px;">', obj.image.url)
        return format_html('<span style="color:#999;">لسه ما اترفعتش صورة — '
                            'ارفع واحدة من خانة "الصورة" فوق.</span>')
    image_preview.short_description = 'معاينة'


@admin.register(ItemVariant)
class ItemVariantAdmin(admin.ModelAdmin):
    form = ItemVariantForm
    list_display = ('sku_code', 'item', 'size', 'selling_price', 'dozen_price_col',
                    'current_stock', 'average_cost', 'reorder_level')
    list_filter = ('size',)
    search_fields = ('sku_code', 'item__code', 'item__name_ar', 'barcode')
    autocomplete_fields = ('item',)
    # selling_price is owned by the main product's per-size recipe (read-only here).
    readonly_fields = ('sku_code', 'selling_price', 'current_stock', 'average_cost')

    def dozen_price_col(self, obj):
        if obj.selling_price:
            dz = obj.item.dozen_size or 12
            return f'{fmt_money(obj.selling_price * dz)} ج ({dz})'
        return '—'
    dozen_price_col.short_description = 'سعر الدستة'


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ('id', 'date', 'variant', 'movement_type', 'quantity', 'unit_cost',
                     'document_type', 'document_id')
    list_filter = ('movement_type', 'document_type', 'date')
    search_fields = ('variant__sku_code', 'document_type', 'notes')
    autocomplete_fields = ('variant',)
    date_hierarchy = 'date'
    readonly_fields = ('created_at', 'created_by')


# ============================================================
#  Finished-goods (trading) purchase invoice
# ============================================================
class FinishedGoodsPurchaseLineInline(admin.TabularInline):
    model = FinishedGoodsPurchaseLine
    extra = 1
    autocomplete_fields = ('variant',)
    fields = ('variant', 'quantity', 'unit_cost', 'line_total_display', 'is_posted')
    readonly_fields = ('line_total_display', 'is_posted')

    def line_total_display(self, obj):
        if not obj or not obj.pk:
            return '—'
        return f'{fmt_money(obj.total_cost)} ج'
    line_total_display.short_description = 'إجمالي البند'


@admin.register(FinishedGoodsPurchaseInvoice)
class FinishedGoodsPurchaseInvoiceAdmin(StayOnPageMixin, LockAfterPostMixin, admin.ModelAdmin):
    lock_field = 'is_posted'
    unlock_always = ('notes',)
    list_display = ('invoice_no', 'supplier', 'date', 'payment_method',
                    'total_col', 'is_posted')
    list_filter = ('is_posted', 'payment_method', 'date', 'supplier')
    search_fields = ('invoice_no', 'supplier_ref', 'supplier__name', 'notes')
    date_hierarchy = 'date'
    autocomplete_fields = ('supplier', 'cash_account')
    readonly_fields = ('invoice_no', 'is_posted', 'journal_entry',
                       'total_display', 'created_at')
    fieldsets = (
        ('بيانات الفاتورة', {
            'fields': ('invoice_no', 'supplier', 'supplier_ref', 'date'),
        }),
        ('الدفع', {
            'fields': ('payment_method', 'cash_account'),
            'description': 'مدفوع: اختار الخزينة/البنك/المحفظة. آجل: اختار المورد '
                           '(هيتسجّل في رصيده).',
        }),
        ('الإجمالي', {'fields': ('total_display', 'is_posted', 'journal_entry')}),
        ('ملاحظات', {'fields': ('notes', 'created_at')}),
    )
    inlines = [FinishedGoodsPurchaseLineInline]
    actions = ('action_post',)

    def total_col(self, obj):
        return f'{fmt_money(obj.total)} ج'
    total_col.short_description = 'الإجمالي'

    def total_display(self, obj):
        if not obj.pk:
            return '—'
        return f'{fmt_money(obj.total)} جنيه'
    total_display.short_description = 'إجمالي الفاتورة'

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        if formset.model is FinishedGoodsPurchaseLine:
            inv = form.instance
            instances = formset.save(commit=False)
            for inst in instances:
                inst.invoice = inv
                inst.save()
            for obj in formset.deleted_objects:
                obj.delete()
            formset.save_m2m()
        else:
            super().save_formset(request, form, formset, change)

    @admin.action(description='ترحيل المختار (قيد محاسبي واحد + زيادة أرصدة المنتجات)')
    def action_post(self, request, queryset):
        ok = 0
        for inv in queryset:
            try:
                post_finished_goods_purchase_invoice(inv, user=request.user)
                ok += 1
            except FinishedGoodsPostingError as e:
                self.message_user(request, f'{inv.invoice_no}: {e}', level=messages.ERROR)
        if ok:
            self.message_user(request, f'تم ترحيل {ok} فاتورة.', level=messages.SUCCESS)
