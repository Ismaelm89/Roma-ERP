from django import forms
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from core.admin_mixins import StayOnPageMixin
from core.templatetags.money_filters import fmt_money

from manufacturing.models import ProductSizeRecipe

from .models import Item, ItemVariant, Product, StockMovement


class ItemVariantForm(forms.ModelForm):
    """Renders `size` as a dropdown sourced from the manufacturing Size master,
    while keeping it a plain CharField in the DB (so sales code is untouched)."""
    class Meta:
        model = ItemVariant
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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
    """SKUs (المقاسات) — للعرض فقط. بتتولّد تلقائياً من وصفة المنتج الرئيسي،
    والسعر بييجي من الوصفة برضه. التعديل بيتم على وصفة المنتج الرئيسي."""
    model = ItemVariant
    extra = 0
    can_delete = False
    fields = ('size', 'sku_code', 'selling_price', 'dozen_price_col',
              'current_stock', 'average_cost', 'barcode', 'reorder_level')
    readonly_fields = ('size', 'sku_code', 'selling_price', 'dozen_price_col',
                       'current_stock', 'average_cost', 'barcode', 'reorder_level')

    def has_add_permission(self, request, obj=None):
        return False

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
    list_display = ('code', 'name_ar', 'fabric_type', 'dozen_size', 'sub_products_count',
                    'recipe_sizes_count', 'active')
    list_display_links = ('code', 'name_ar')
    list_filter = ('active', 'fabric_type', 'category')
    search_fields = ('code', 'name_ar', 'name_en')
    readonly_fields = ('code',)
    autocomplete_fields = ('fabric_type',)
    inlines = [ProductSizeRecipeInline]
    fieldsets = (
        ('بيانات المنتج', {
            'fields': ('code', 'name_ar', 'name_en', 'category', 'fabric_type',
                       'dozen_size', 'waste_pct', 'notes', 'active'),
            'description': 'المنتج الرئيسي بيحدد كل حاجة: المقاسات، نوع القماش/الخامة، '
                           'عدد القطع في الدستة، نسبة الهالك على المنتج كله، واستهلاك '
                           'القماش/الإكسسوارات/المصنعية والسعر لكل مقاس (في جدول الوصفة تحت). '
                           'المنتجات الفرعية بتاخد كل ده تلقائياً.',
        }),
    )

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
    readonly_fields = ('code', 'image_preview', 'inherited_summary')
    fieldsets = (
        ('بيانات المنتج الفرعي', {
            'fields': ('product', 'inherited_summary', 'code', 'name_ar',
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
