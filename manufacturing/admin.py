"""Roma Manufacturing — Django admin (unified-supplier version)."""
from django import forms
from django.contrib import admin, messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html

from core.admin_mixins import StayOnPageMixin, LockAfterPostMixin, LockedInlineMixin
from core.templatetags.money_filters import fmt_money

from .models import (
    VendorType, Supplier, FabricType, FabricColor,
    FabricBatch, FabricMovement, SupplierPayment,
    FabricPurchaseInvoice, AccessoryPurchaseInvoice,
    ProductionOrder, ProductionSubModel, ProductionSize, FabricUsage,
    ProductionGroup, Accessory, AccessoryUsage, AccessoryPurchase, Size,
    ProductSizeRecipe, ProductSizeAccessory,
    ManufacturingWagePayment,
)
from .services import (
    post_fabric_purchase,
    post_fabric_purchase_invoice,
    post_supplier_payment,
    post_accessory_purchase,
    post_accessory_purchase_invoice,
    produce_production_order, cancel_production_order,
    apply_recipe_to_order, refresh_planned_fabric_usage,
    post_wage_payment, mfg_wages_accrued_balance,
    FabricPostingError,
)


def _balance_html(balance):
    """Color-code a vendor balance: red if we owe, green if overpaid."""
    if balance > 0:
        return format_html('<b style="color:#dc2626">{} مدين</b>', fmt_money(balance))
    if balance < 0:
        return format_html('<b style="color:#16a34a">{} (دفع زيادة)</b>', fmt_money(-balance))
    return format_html('<span style="color:#666">0</span>')


# ============================================================
#  Vendor types + unified supplier
# ============================================================

@admin.register(VendorType)
class VendorTypeAdmin(admin.ModelAdmin):
    list_display = ('code', 'name_ar', 'sort_order', 'supplier_count', 'active')
    list_editable = ('sort_order', 'active')
    search_fields = ('code', 'name_ar')

    def supplier_count(self, obj):
        return obj.suppliers.count()
    supplier_count.short_description = 'عدد الموردين'


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'vendor_type', 'phone', 'balance_col',
                    'pay_link', 'ledger_link', 'active')
    list_filter = ('vendor_type', 'active')
    search_fields = ('code', 'name', 'phone', 'tax_id')
    autocomplete_fields = ('vendor_type',)
    readonly_fields = ('code', 'created_at', 'balance_display')
    change_form_template = 'admin/manufacturing/supplier/change_form.html'
    fieldsets = (
        ('بيانات المورد', {
            'fields': ('code', 'name', 'vendor_type', 'phone', 'address', 'tax_id', 'active'),
            'description': 'نوع المورد إجباري — يحدد القوائم اللي هيظهر فيها '
                           '(مثلاً المصبغة بتظهر بس في أوامر التصبيغ).',
        }),
        ('الرصيد', {'fields': ('balance_display',)}),
        ('ملاحظات', {'fields': ('notes', 'created_at')}),
    )

    def balance_col(self, obj):
        return _balance_html(obj.current_balance)
    balance_col.short_description = 'الرصيد الحالي'

    def balance_display(self, obj):
        if not obj.pk:
            return '—'
        return _balance_html(obj.current_balance)
    balance_display.short_description = 'الرصيد الحالي (محسوب live)'

    def ledger_link(self, obj):
        if not obj.pk:
            return ''
        url = reverse('manufacturing:supplier_ledger', args=[obj.pk])
        return format_html('<a href="{}" target="_blank">كشف حساب</a>', url)
    ledger_link.short_description = ''

    def pay_link(self, obj):
        if not obj.pk:
            return ''
        url = reverse('admin:manufacturing_supplierpayment_add') + f'?supplier={obj.pk}'
        return format_html(
            '<a href="{}" style="background:#15803d;color:white;padding:3px 8px;'
            'border-radius:3px;text-decoration:none;font-weight:600;">💰 ادفع</a>',
            url,
        )
    pay_link.short_description = ''


# ============================================================
#  Fabric type + color
# ============================================================

@admin.register(FabricType)
class FabricTypeAdmin(admin.ModelAdmin):
    list_display = ('code', 'name_ar', 'description', 'active')
    list_filter = ('active',)
    search_fields = ('code', 'name_ar', 'description')
    readonly_fields = ('code', 'created_at')


@admin.register(FabricColor)
class FabricColorAdmin(admin.ModelAdmin):
    list_display = ('code', 'name_ar', 'is_raw', 'hex_swatch', 'active')
    list_filter = ('is_raw', 'active')
    search_fields = ('code', 'name_ar')
    readonly_fields = ('code', 'created_at')

    def hex_swatch(self, obj):
        if not obj.hex_code:
            return '—'
        return format_html(
            '<span style="display:inline-block;width:20px;height:20px;'
            'border:1px solid #999;background:{};vertical-align:middle"></span> '
            '<code>{}</code>',
            obj.hex_code, obj.hex_code,
        )
    hex_swatch.short_description = 'لون'


# ============================================================
#  Fabric batch (= "شراء قماش")
# ============================================================

class FabricMovementInline(admin.TabularInline):
    model = FabricMovement
    extra = 0
    can_delete = False
    fields = ('date', 'movement_type', 'quantity_kg', 'cost_per_kg_snapshot', 'notes')
    readonly_fields = fields
    ordering = ('-date', '-id')

    def has_add_permission(self, request, obj=None):
        return False


# شاشة "مشتريات القماش" المفردة اتشالت من القايمة. الشراء بقى عن طريق
# "فاتورة شراء قماش" (تقدر تعمل بند واحد = دفعة، أو كذا بند في فاتورة واحدة).
# الكلاس سايبينه للمرجع بس مش متسجّل (FabricBatch بقى بند داخل الفاتورة فقط).
class FabricBatchAdmin(StayOnPageMixin, LockAfterPostMixin, admin.ModelAdmin):
    lock_field = 'is_posted'
    unlock_always = ('notes',)
    list_display = ('batch_no', 'invoice', 'supplier', 'fabric_type', 'color', 'purchase_date',
                    'purchase_qty_kg', 'in_stock_qty_kg_col',
                    'cost_per_kg_col', 'is_posted')
    list_filter = ('is_posted', 'fabric_type', 'color', 'supplier')
    search_fields = ('batch_no', 'supplier__name', 'fabric_type__name_ar', 'color__name_ar')
    date_hierarchy = 'purchase_date'
    autocomplete_fields = ('supplier', 'fabric_type', 'color')
    readonly_fields = ('batch_no', 'in_stock_qty_kg',
                       'is_posted', 'purchase_total_display',
                       'cost_per_kg_display', 'created_at')
    fieldsets = (
        ('بيانات الشراء', {
            'fields': ('batch_no', 'supplier', 'fabric_type', 'color', 'purchase_date'),
        }),
        ('السعر والكمية', {
            'fields': ('purchase_qty_kg', 'purchase_unit_cost', 'purchase_payment_method',
                       'purchase_total_display'),
        }),
        ('الأرصدة الجارية', {
            'fields': ('in_stock_qty_kg', 'cost_per_kg_display', 'is_posted'),
        }),
        ('ملاحظات', {'fields': ('notes', 'created_at')}),
    )
    inlines = [FabricMovementInline]
    actions = ('action_post_purchase',)
    change_form_template = 'admin/manufacturing/fabricbatch/change_form.html'

    def in_stock_qty_kg_col(self, obj):
        return f'{fmt_money(obj.in_stock_qty_kg)} كجم'
    in_stock_qty_kg_col.short_description = 'بالمخزن'

    def _UNUSED_at_dyer(self, obj):
        if obj.at_dyer_qty_kg > 0:
            return format_html('<b>{} كجم</b>', obj.in_stock_qty_kg)
        return '—'

    def cost_per_kg_col(self, obj):
        return f'{fmt_money(obj.cost_per_kg)} جنيه/كجم'
    cost_per_kg_col.short_description = 'تكلفة الكيلو'

    def purchase_total_display(self, obj):
        return f'{fmt_money(obj.purchase_total)} جنيه'
    purchase_total_display.short_description = 'إجمالي الشراء'

    def cost_per_kg_display(self, obj):
        return f'{fmt_money(obj.cost_per_kg)} جنيه/كجم'
    cost_per_kg_display.short_description = 'تكلفة الكيلو الحالية'

    @admin.action(description='ترحيل المختار (إنشاء قيد محاسبي + حركة استلام)')
    def action_post_purchase(self, request, queryset):
        ok = err = 0
        for batch in queryset:
            try:
                post_fabric_purchase(batch, user=request.user)
                ok += 1
            except FabricPostingError as e:
                self.message_user(request, f'{batch.batch_no}: {e}', level=messages.ERROR)
                err += 1
        if ok:
            self.message_user(request, f'تم ترحيل {ok} عملية شراء بنجاح.', level=messages.SUCCESS)

    def response_add(self, request, obj, post_url_continue=None):
        if '_save_and_post' in request.POST:
            return self._post_and_redirect(request, obj)
        return super().response_add(request, obj, post_url_continue)

    def response_change(self, request, obj):
        if '_save_and_post' in request.POST:
            return self._post_and_redirect(request, obj)
        return super().response_change(request, obj)

    def _post_and_redirect(self, request, obj):
        if obj.is_posted:
            self.message_user(request, f'{obj.batch_no}: مرحّلة من قبل.', level=messages.WARNING)
        else:
            try:
                post_fabric_purchase(obj, user=request.user)
                self.message_user(request,
                                   f'تم ترحيل الشراء {obj.batch_no} — قيد محاسبي + رصيد {obj.in_stock_qty_kg} كجم.',
                                   level=messages.SUCCESS)
            except FabricPostingError as e:
                self.message_user(request, f'فشل الترحيل: {e}', level=messages.ERROR)
        return redirect(reverse('admin:manufacturing_fabricbatch_change', args=[obj.pk]))


# ============================================================
#  Multi-line fabric purchase invoice (header + FabricBatch lines)
# ============================================================

class FabricBatchLineInline(LockedInlineMixin, admin.TabularInline):
    """بنود فاتورة شراء القماش — كل بند = دفعة (نوع/لون/كمية/سعر)."""
    model = FabricBatch
    fk_name = 'invoice'
    extra = 1
    autocomplete_fields = ('fabric_type', 'color')
    fields = ('fabric_type', 'color', 'purchase_qty_kg', 'purchase_unit_cost',
              'line_total_display', 'batch_no', 'is_posted')
    readonly_fields = ('line_total_display', 'batch_no', 'is_posted')

    def line_total_display(self, obj):
        if not obj or not obj.pk:
            return '—'
        return f'{fmt_money(obj.purchase_total)} ج'
    line_total_display.short_description = 'إجمالي البند'


@admin.register(FabricPurchaseInvoice)
class FabricPurchaseInvoiceAdmin(StayOnPageMixin, LockAfterPostMixin, admin.ModelAdmin):
    lock_field = 'is_posted'
    unlock_always = ('notes',)
    list_display = ('invoice_no', 'supplier', 'date', 'payment_method',
                    'line_count_col', 'total_col', 'is_posted')
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
        ('السداد', {
            'fields': ('payment_method', 'cash_account'),
            'description': 'آجل: هيتسجّل على المورد. كاش/بنك: اختار الخزينة/البنك/المحفظة '
                           '(لو سبتها فاضية هيتحسب على النقدية/البنك العام).',
        }),
        ('الإجمالي', {'fields': ('total_display', 'is_posted', 'journal_entry')}),
        ('ملاحظات', {'fields': ('notes', 'created_at')}),
    )
    inlines = [FabricBatchLineInline]
    actions = ('action_post',)
    change_form_template = 'admin/manufacturing/fabricpurchaseinvoice/change_form.html'

    def line_count_col(self, obj):
        return obj.line_count
    line_count_col.short_description = 'عدد البنود'

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
        """انسخ بيانات الهيدر (مورد/تاريخ/سداد) على كل بند قبل الحفظ — البنود
        بتظهر للمستخدم بالأعمدة المهمة بس (نوع/لون/كمية/سعر)."""
        if formset.model is FabricBatch:
            inv = form.instance
            instances = formset.save(commit=False)
            for inst in instances:
                inst.invoice = inv
                inst.supplier = inv.supplier
                inst.purchase_date = inv.date
                inst.purchase_payment_method = inv.payment_method
                if not inst.created_by_id:
                    inst.created_by = request.user
                inst.save()
            for obj in formset.deleted_objects:
                obj.delete()
            formset.save_m2m()
        else:
            super().save_formset(request, form, formset, change)

    @admin.action(description='ترحيل المختار (قيد محاسبي واحد + استلام كل البنود)')
    def action_post(self, request, queryset):
        ok = 0
        for inv in queryset:
            try:
                post_fabric_purchase_invoice(inv, user=request.user)
                ok += 1
            except FabricPostingError as e:
                self.message_user(request, f'{inv.invoice_no}: {e}', level=messages.ERROR)
        if ok:
            self.message_user(request, f'تم ترحيل {ok} فاتورة.', level=messages.SUCCESS)

    def response_add(self, request, obj, post_url_continue=None):
        if '_save_and_post' in request.POST:
            return self._post_and_redirect(request, obj)
        return super().response_add(request, obj, post_url_continue)

    def response_change(self, request, obj):
        if '_save_and_post' in request.POST:
            return self._post_and_redirect(request, obj)
        return super().response_change(request, obj)

    def _post_and_redirect(self, request, obj):
        if obj.is_posted:
            self.message_user(request, f'{obj.invoice_no}: مرحّلة من قبل.', level=messages.WARNING)
        else:
            try:
                post_fabric_purchase_invoice(obj, user=request.user)
                self.message_user(
                    request,
                    f'تم ترحيل الفاتورة {obj.invoice_no} — {obj.line_count} بند بإجمالي '
                    f'{fmt_money(obj.total)} جنيه + قيد محاسبي واحد.',
                    level=messages.SUCCESS)
            except FabricPostingError as e:
                self.message_user(request, f'فشل الترحيل: {e}', level=messages.ERROR)
        return redirect(reverse('admin:manufacturing_fabricpurchaseinvoice_change', args=[obj.pk]))


# ============================================================
#  Dye order
# ============================================================

# ============================================================
#  Supplier payment
# ============================================================

@admin.register(SupplierPayment)
class SupplierPaymentAdmin(StayOnPageMixin, LockAfterPostMixin, admin.ModelAdmin):
    lock_field = 'status'
    lock_values = ('POSTED', 'CANCELLED')
    unlock_always = ('notes',)
    list_display = ('payment_no', 'date', 'party_col', 'method', 'cash_account', 'amount', 'status_col')
    list_filter = ('status', 'method', 'date', 'supplier__vendor_type', 'cash_account')
    search_fields = ('payment_no', 'reference', 'supplier__name')
    date_hierarchy = 'date'
    autocomplete_fields = ('supplier', 'cash_account')
    readonly_fields = ('payment_no', 'status', 'journal_entry', 'created_at')
    fieldsets = (
        ('بيانات السند', {'fields': ('payment_no', 'date', 'status')}),
        ('الجهة', {'fields': ('supplier',),
                    'description': 'اختار المورد من القائمة (مفيش فرق بين مورد قماش/مصبغة/إلخ — '
                                   'كلهم في نفس الـ master).'}),
        ('الدفع', {'fields': ('method', 'cash_account', 'amount', 'reference'),
                    'description': 'النقدية/البنك/المحفظة: اختار الحساب اللى دفعت منه. '
                                   'سيبه فاضي عشان يستخدم الصندوق/البنك الافتراضي.'}),
        ('ملاحظات', {'fields': ('notes', 'journal_entry', 'created_at')}),
    )
    actions = ('action_post',)
    change_form_template = 'admin/manufacturing/supplierpayment/change_form.html'

    def party_col(self, obj):
        return obj.party_label
    party_col.short_description = 'الجهة'

    def status_col(self, obj):
        colors = {'DRAFT': '#666', 'POSTED': '#16a34a', 'CANCELLED': '#dc2626'}
        return format_html('<b style="color:{}">{}</b>',
                            colors.get(obj.status, '#000'), obj.get_status_display())
    status_col.short_description = 'الحالة'

    @admin.action(description='ترحيل المختار (إنشاء قيد محاسبي وخصم من رصيد المورد)')
    def action_post(self, request, queryset):
        ok = err = 0
        for p in queryset:
            try:
                post_supplier_payment(p, user=request.user)
                ok += 1
            except FabricPostingError as e:
                self.message_user(request, f'{p.payment_no}: {e}', level=messages.ERROR)
                err += 1
        if ok:
            self.message_user(request, f'تم ترحيل {ok} سند.', level=messages.SUCCESS)

    def response_add(self, request, obj, post_url_continue=None):
        if '_save_and_post' in request.POST:
            return self._post_and_redirect(request, obj)
        return super().response_add(request, obj, post_url_continue)

    def response_change(self, request, obj):
        if '_save_and_post' in request.POST:
            return self._post_and_redirect(request, obj)
        return super().response_change(request, obj)

    def _post_and_redirect(self, request, obj):
        if obj.status != 'DRAFT':
            self.message_user(request, f'{obj.payment_no}: مرحّل من قبل.', level=messages.WARNING)
        else:
            try:
                post_supplier_payment(obj, user=request.user)
                self.message_user(request,
                                   f'تم ترحيل السند {obj.payment_no} — رصيد المورد اتحدث.',
                                   level=messages.SUCCESS)
            except FabricPostingError as e:
                self.message_user(request, f'فشل الترحيل: {e}', level=messages.ERROR)
        return redirect(reverse('admin:manufacturing_supplierpayment_change', args=[obj.pk]))


# ============================================================
#  Manufacturing wage payments (صرف مصنعيات) — Phase C
# ============================================================

@admin.register(ManufacturingWagePayment)
class ManufacturingWagePaymentAdmin(StayOnPageMixin, LockAfterPostMixin, admin.ModelAdmin):
    lock_field = 'status'
    lock_values = ('POSTED', 'CANCELLED')
    unlock_always = ('notes',)
    list_display = ('payment_no', 'date', 'payee', 'method', 'cash_account',
                    'amount', 'accrued_col', 'expense_col', 'status_col')
    list_filter = ('status', 'method', 'date', 'cash_account')
    search_fields = ('payment_no', 'reference', 'payee')
    date_hierarchy = 'date'
    autocomplete_fields = ('cash_account',)
    readonly_fields = ('payment_no', 'status', 'accrued_portion', 'expense_portion',
                       'journal_entry', 'accrued_balance_display', 'created_at')
    fieldsets = (
        ('بيانات السند', {'fields': ('payment_no', 'date', 'status')}),
        ('المصنعيات المستحقة', {
            'fields': ('accrued_balance_display',),
            'description': 'ده رصيد «مصنعيات مستحقة» في الميزانية دلوقتي (من أوامر الإنتاج). '
                           'الصرف بيخصم منه الأول؛ أي زيادة عن المستحق بتتسجّل «فرق مصنعيات» '
                           'في المصاريف. ولو دفعت أقل، الباقي يفضل مستحق في الميزانية.',
        }),
        ('الدفع', {'fields': ('payee', 'method', 'cash_account', 'amount', 'reference'),
                    'description': 'النقدية/البنك/المحفظة: اختار الحساب اللى دفعت منه. '
                                   'سيبه فاضي عشان يستخدم الصندوق/البنك الافتراضي.'}),
        ('التقسيم بعد الترحيل', {
            'fields': ('accrued_portion', 'expense_portion'),
            'description': 'بيتحسب تلقائياً وقت الترحيل.',
        }),
        ('ملاحظات', {'fields': ('notes', 'journal_entry', 'created_at')}),
    )
    actions = ('action_post',)
    change_form_template = 'admin/manufacturing/manufacturingwagepayment/change_form.html'

    def status_col(self, obj):
        colors = {'DRAFT': '#666', 'POSTED': '#16a34a', 'CANCELLED': '#dc2626'}
        return format_html('<b style="color:{}">{}</b>',
                            colors.get(obj.status, '#000'), obj.get_status_display())
    status_col.short_description = 'الحالة'

    def accrued_col(self, obj):
        return f'{fmt_money(obj.accrued_portion)} ج' if obj.status == 'POSTED' else '—'
    accrued_col.short_description = 'سُدّد من المستحق'

    def expense_col(self, obj):
        return f'{fmt_money(obj.expense_portion)} ج' if obj.status == 'POSTED' else '—'
    expense_col.short_description = 'زيادة (مصروف)'

    def accrued_balance_display(self, obj):
        bal = mfg_wages_accrued_balance()
        return format_html('<b style="color:#b45309;font-size:16px;">{} ج</b> مستحقة دلوقتي',
                           fmt_money(bal))
    accrued_balance_display.short_description = 'مصنعيات مستحقة حالياً'

    @admin.action(description='ترحيل المختار (قيد صرف مصنعيات)')
    def action_post(self, request, queryset):
        ok = err = 0
        for p in queryset:
            try:
                post_wage_payment(p, user=request.user)
                ok += 1
            except FabricPostingError as e:
                self.message_user(request, f'{p.payment_no}: {e}', level=messages.ERROR)
                err += 1
        if ok:
            self.message_user(request, f'تم ترحيل {ok} سند صرف مصنعيات.', level=messages.SUCCESS)

    def response_add(self, request, obj, post_url_continue=None):
        if '_save_and_post' in request.POST:
            return self._post_and_redirect(request, obj)
        return super().response_add(request, obj, post_url_continue)

    def response_change(self, request, obj):
        if '_save_and_post' in request.POST:
            return self._post_and_redirect(request, obj)
        return super().response_change(request, obj)

    def _post_and_redirect(self, request, obj):
        if obj.status != 'DRAFT':
            self.message_user(request, f'{obj.payment_no}: مرحّل من قبل.', level=messages.WARNING)
        else:
            try:
                post_wage_payment(obj, user=request.user)
                self.message_user(
                    request,
                    f'تم ترحيل {obj.payment_no} — سُدّد من المستحق {fmt_money(obj.accrued_portion)} ج، '
                    f'زيادة في المصاريف {fmt_money(obj.expense_portion)} ج.',
                    level=messages.SUCCESS)
            except FabricPostingError as e:
                self.message_user(request, f'فشل الترحيل: {e}', level=messages.ERROR)
        return redirect(reverse('admin:manufacturing_manufacturingwagepayment_change',
                                args=[obj.pk]))


# ============================================================
#  Production orders (Phase 2a)
# ============================================================

class ProductionSubModelInline(LockedInlineMixin, admin.StackedInline):
    """One block per sub-model with all the cut data.
    sub_model_no is auto-assigned on save — readonly here."""
    model = ProductionSubModel
    extra = 0
    readonly_fields = ('sub_model_no',)
    fields = (
        ('sub_model_no', 'fabric_description', 'ticket'),
        ('chest_type', 'chest_color', 'chest_notes'),
        ('back_type', 'back_color', 'back_notes'),
        ('sleeve_type', 'sleeve_color', 'sleeve_notes'),
        ('shorts_pattern', 'shorts_type', 'shorts_color', 'shorts_notes'),
        'notes',
    )


class ProductionSizeInline(LockedInlineMixin, admin.TabularInline):
    """One row per size with quantity + a per-row 'product notes' picker.
    The ملاحظات المنتج dropdown lists the notes already created inside THIS
    order, so the same notes can be reused on more than one size line.
    The ➕/✏️ icons still open the ProductionSubModel form in a popup to add
    a new note."""
    model = ProductionSize
    extra = 1
    fields = ('size', 'quantity', 'sub_model')
    autocomplete_fields = ('size',)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'sub_model':
            from django.db.models import Q
            order_id = None
            if getattr(request, 'resolver_match', None):
                order_id = request.resolver_match.kwargs.get('object_id')
            # Show this order's notes + any not-yet-adopted (popup-created) notes,
            # so a freshly added note still validates on save.
            if order_id:
                kwargs['queryset'] = ProductionSubModel.objects.filter(
                    Q(order_id=order_id) | Q(order__isnull=True)
                )
            else:
                kwargs['queryset'] = ProductionSubModel.objects.filter(order__isnull=True)
            kwargs['empty_label'] = '— بدون ملاحظات —'
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class FabricUsageInline(admin.TabularInline):
    """جدول «استهلاكات القماش» — للعرض فقط (مفيش إدخال يدوي). بيتعبّى تلقائياً:
      • وقت الحفظ (مرحلة الخطة): صفّ مخطط واحد محسوب من خامة المنتج الرئيسي
        ووصفته — قبل الهالك / بالهالك / متوسط سعر الكيلو (الدفعة لسه فاضية).
      • وقت «انتج»: بيتمسح ويتعاد إنشاؤه بصفّ لكل دفعة اتخصم منها فعلياً
        (FIFO) بتكلفة المتوسط.
    """
    model = FabricUsage
    extra = 0
    can_delete = False
    fields = ('fabric_type', 'batch', 'planned_qty_kg', 'actual_qty_kg',
              'cost_per_kg_snapshot', 'notes')
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


class ProductionGroupInline(LockedInlineMixin, admin.TabularInline):
    """مراحل التشغيل على الأمر — كل مرحلة (تشغيل / تشطيب / جودة / كوي) بمجموعة
    وكمية، زائد ملاحظات. الجدول بيتعرض 5 صفوف على طول (المملوء + الباقي فاضي)،
    والمستخدم يقدر يزوّد صفوف بنفسه لو احتاج. بيظهر في طباعة الخطة وبعد الإنتاج."""
    model = ProductionGroup
    extra = 5
    fields = ('sewing_group', 'sewing_qty', 'finishing_group', 'finishing_qty',
              'quality_group', 'quality_qty', 'ironing_group', 'ironing_qty', 'notes')

    def get_extra(self, request, obj=None, **kwargs):
        """نكمّل صفوف الإدخال لحد 5 على طول (المملوء + الباقي فاضي)، والمستخدم
        يقدر يضيف أكتر بزر «إضافة صف» لو احتاج. لو الأمر متقفل (مكتمل/ملغي)
        منعرضش صفوف زيادة."""
        if self._locked():
            return 0
        existing = obj.groups.count() if obj is not None else 0
        return max(0, 5 - existing)


class AccessoryUsageInline(LockedInlineMixin, admin.TabularInline):
    """One row per accessory consumed for this order.
    User just picks the accessory and the actual quantity — price and supplier
    come automatically from the Accessory master record."""
    model = AccessoryUsage
    extra = 0
    fields = ('accessory', 'actual_qty', 'notes')
    autocomplete_fields = ('accessory',)


class ProductionOrderForm(forms.ModelForm):
    """فورم أمر الإنتاج — المنتج الفرعي (الموديل) إلزامي، واسم الأمر بييجي منه
    تلقائياً (خانة الاسم اليدوية اتشالت)."""
    class Meta:
        model = ProductionOrder
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'item' in self.fields:
            self.fields['item'].required = True


@admin.register(ProductionOrder)
class ProductionOrderAdmin(StayOnPageMixin, LockAfterPostMixin, admin.ModelAdmin):
    form = ProductionOrderForm
    lock_field = 'status'
    lock_values = ('COMPLETED', 'CANCELLED')  # RELEASED still editable for actuals
    unlock_always = ('notes',)
    list_display = ('order_no', 'date', 'item', 'customer', 'status_col',
                    'pieces_col', 'fabric_kg_col', 'fabric_value_col')
    list_filter = ('status', 'date', 'item', 'customer')
    search_fields = ('order_no', 'title', 'item__code', 'item__name_ar',
                     'customer__name_ar', 'notes')
    date_hierarchy = 'date'
    autocomplete_fields = ('item', 'customer')
    readonly_fields = ('order_no', 'status', 'released_at', 'released_by',
                       'completed_at', 'completed_by',
                       'released_journal_entry', 'completed_journal_entry',
                       'model_image_display',
                       'pieces_display', 'fabric_display', 'cost_kpis_display',
                       'created_at')
    fieldsets = (
        ('بيانات الأمر', {
            'fields': ('order_no', 'date', 'item', 'model_image_display',
                       'customer', 'status', 'notes'),
            'description': 'اختار الموديل (المنتج الفرعي) من قائمة "الموديل (منتج فرعي)". '
                           'اسم الأمر بييجي تلقائياً من اسم الموديل، والخامة (نوع القماش) '
                           'من المنتج الرئيسي، ولون القماش اللي هيتخصم من المخزن من الموديل نفسه. '
                           'صورة الموديل بتظهر تحت بعد ما تحفظ.',
        }),
        # الإجماليات + سجل الترحيل بيتعرضوا في نهاية الصفحة (بعد الجداول) عن طريق الـ template
    )
    # جدول «استهلاكات القماش» (FabricUsageInline) للعرض فقط — بيتعبّى تلقائياً
    # وقت الحفظ بصفّ مخطط من الوصفة، وبيتعاد بناؤه بالخصم الفعلي وقت «انتج».
    inlines = [ProductionSizeInline, FabricUsageInline, ProductionGroupInline,
               AccessoryUsageInline]
    actions = ('action_load_recipe', 'action_produce', 'action_cancel')
    change_form_template = 'admin/manufacturing/productionorder/change_form.html'

    class Media:
        js = ('manufacturing/submodel_sync.js',)

    def status_col(self, obj):
        colors = {
            'DRAFT':     '#666',
            'RELEASED':  '#d97706',
            'COMPLETED': '#16a34a',
            'CANCELLED': '#dc2626',
        }
        return format_html('<b style="color:{}">{}</b>',
                            colors.get(obj.status, '#000'), obj.get_status_display())
    status_col.short_description = 'الحالة'

    def pieces_col(self, obj):
        return f'{fmt_money(obj.total_pieces, 0)} قطعة'
    pieces_col.short_description = 'القطع'

    def fabric_kg_col(self, obj):
        p = obj.total_planned_fabric_kg
        a = obj.total_actual_fabric_kg
        if a == p or a == 0:
            return f'{fmt_money(p)} كجم'
        return format_html('<span title="قبل الهالك / بالهالك">{} / <b>{}</b></span>',
                           fmt_money(p), fmt_money(a))
    fabric_kg_col.short_description = 'القماش'

    def fabric_value_col(self, obj):
        return f'{fmt_money(obj.total_fabric_value)} ج'
    fabric_value_col.short_description = 'قيمة القماش'

    def model_image_display(self, obj):
        """صورة الموديل (المنتج الفرعي) عشان المشرف يشوف الشكل وهو بيجهّز الأمر."""
        if not obj or not obj.pk:
            return format_html('<span style="color:#94a3b8;">اختار الموديل واحفظ عشان '
                               'تظهر الصورة.</span>')
        item = obj.item
        img = getattr(item, 'image', None) if item else None
        url = None
        if img:
            try:
                url = img.url
            except ValueError:
                url = None
        if url:
            return format_html(
                '<img src="{}" alt="{}" style="max-width:240px;max-height:240px;'
                'border:1px solid #cbd5e1;border-radius:8px;padding:4px;background:#fff;">',
                url, item.name_ar)
        return format_html('<span style="color:#94a3b8;">لا توجد صورة للموديل '
                           '(ضيفها من شاشة المنتج الفرعي).</span>')
    model_image_display.short_description = 'صورة الموديل'

    def pieces_display(self, obj):
        if not obj.pk:
            return '—'
        return format_html('<b>{}</b> قطعة', fmt_money(obj.total_pieces, 0))
    pieces_display.short_description = 'إجمالي القطع'

    def fabric_display(self, obj):
        if not obj.pk:
            return '—'
        color = obj.fabric_color
        color_txt = color.name_ar if color else 'كل الألوان (مفيش لون محدّد للموديل)'
        return format_html(
            'اللون المخصوم منه: <b>{}</b><br>'
            'قبل الهالك: <b>{}</b> كجم · بالهالك: <b>{}</b> كجم · قيمة: <b>{}</b> جنيه',
            color_txt,
            fmt_money(obj.total_planned_fabric_kg), fmt_money(obj.total_actual_fabric_kg),
            fmt_money(obj.total_fabric_value),
        )
    fabric_display.short_description = 'إجمالي القماش'

    def cost_kpis_display(self, obj):
        if not obj.pk:
            return '—'
        pieces = obj.total_actual_pieces or obj.total_planned_pieces
        cpp = obj.cost_per_piece if obj.total_actual_pieces else (
            (obj.total_cost / pieces).quantize(__import__('decimal').Decimal('0.0001'))
            if pieces else 0
        )
        return format_html(
            '<table style="background:#f8fafc;padding:6px;">'
            '<tr><td>قماش (فعلي):</td><td><b>{}</b> ج</td></tr>'
            '<tr><td>إكسسوارات (فعلي):</td><td><b>{}</b> ج</td></tr>'
            '<tr><td>مصنعية (من الوصفة):</td><td><b>{}</b> ج</td></tr>'
            '<tr style="border-top:2px solid #475569"><td>إجمالي التكلفة:</td><td><b>{}</b> ج</td></tr>'
            '<tr><td>تكلفة الوحدة:</td><td><b>{}</b> ج/قطعة</td></tr>'
            '</table>',
            fmt_money(obj.total_fabric_value),
            fmt_money(obj.total_actual_accessory_cost),
            fmt_money(obj.recipe_labor_cost),
            fmt_money(obj.total_cost),
            fmt_money(cpp, 4),
        )
    cost_kpis_display.short_description = 'KPIs تكلفة الإنتاج'

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        order = form.instance
        # Adopt popup-created product-notes into this order, so they show up in
        # the ملاحظات المنتج dropdown of every other size line in the same order.
        for sz in order.sizes.select_related('sub_model').all():
            sm = sz.sub_model
            if sm and sm.order_id is None:
                sm.order = order
                sm.save()  # also auto-assigns sub_model_no within the order
        # عبّي جدول «استهلاكات القماش» بصفّ مخطط من الوصفة عند كل حفظ (مرحلة الخطة).
        # وقت «انتج» الدالة produce بتمسحه وتعيد بناءه بالخصم الفعلي من الدفعات.
        refresh_planned_fabric_usage(order)
        # تأكد إن مجموع كل مرحلة (تشغيل/تشطيب/جودة/كوي) = إجمالي كميات المقاسات.
        target = order.total_pieces
        groups = list(order.groups.all())
        stages = (
            ('التشغيل', 'sewing_qty'),
            ('التشطيب', 'finishing_qty'),
            ('الجودة', 'quality_qty'),
            ('الكوي', 'ironing_qty'),
        )
        for label, attr in stages:
            stage_total = sum(getattr(g, attr) or 0 for g in groups)
            if stage_total and stage_total != target:
                diff = stage_total - target
                word = 'ناقص' if diff < 0 else 'زيادة'
                self.message_user(
                    request,
                    f'⚠️ تنبيه: مجموع كميات مرحلة {label} في مجموعات الشغل {stage_total} قطعة، '
                    f'لكن إجمالي كميات المقاسات {target} قطعة ({word} {abs(diff)}). '
                    f'راجع الكميات.',
                    level=messages.WARNING,
                )

    def _message_recipe_summary(self, request, order, summary):
        """يعرض ملخّص تحميل الوصفة (قماش + إكسسوارات) + أي تحذيرات."""
        parts = []
        if summary['fabric_applied']:
            parts.append(f'القماش (تلقائي وقت الإنتاج): قبل الهالك {summary["planned_kg"]} كجم '
                         f'/ بالهالك {summary["actual_kg"]} كجم')
        if summary['acc_created'] or summary['acc_updated']:
            parts.append(f'إكسسوارات: {summary["acc_created"]} جديد، {summary["acc_updated"]} محدّث')
        if summary['labor_cost']:
            parts.append(f'مصنعية متوقعة: {fmt_money(summary["labor_cost"])} ج')
        if parts:
            self.message_user(request, f'{order.order_no} — تم تحميل الوصفة · ' + ' · '.join(parts),
                              level=messages.SUCCESS)
        for w in summary['warnings']:
            self.message_user(request, f'{order.order_no}: {w}', level=messages.WARNING)

    @admin.action(description='تحميل المخطط من وصفة المنتج (قماش + إكسسوارات)')
    def action_load_recipe(self, request, queryset):
        ok = 0
        for o in queryset:
            try:
                summary = apply_recipe_to_order(o, user=request.user)
                self._message_recipe_summary(request, o, summary)
                ok += 1
            except FabricPostingError as e:
                self.message_user(request, f'{o.order_no}: {e}', level=messages.ERROR)
        if ok:
            self.message_user(request, f'تم تحميل الوصفة على {ok} أمر.', level=messages.SUCCESS)

    @admin.action(description='انتج المختار (خصم القماش + إضافة المنتج التام + كل القيود)')
    def action_produce(self, request, queryset):
        ok = err = 0
        for o in queryset:
            try:
                produce_production_order(o, user=request.user)
                ok += 1
            except FabricPostingError as e:
                self.message_user(request, f'{o.order_no}: {e}', level=messages.ERROR)
                err += 1
        if ok:
            self.message_user(request, f'تم إنتاج {ok} أمر.', level=messages.SUCCESS)

    @admin.action(description='إلغاء المختار (يعكس استهلاك القماش لو كان مرحّل)')
    def action_cancel(self, request, queryset):
        ok = err = 0
        for o in queryset:
            try:
                cancel_production_order(o, user=request.user)
                ok += 1
            except FabricPostingError as e:
                self.message_user(request, f'{o.order_no}: {e}', level=messages.ERROR)
                err += 1
        if ok:
            self.message_user(request, f'تم إلغاء {ok} أمر.', level=messages.SUCCESS)

    def response_add(self, request, obj, post_url_continue=None):
        if '_save_and_load_recipe' in request.POST:
            return self._load_recipe_and_redirect(request, obj)
        if '_save_and_produce' in request.POST:
            return self._produce_and_redirect(request, obj)
        return super().response_add(request, obj, post_url_continue)

    def response_change(self, request, obj):
        if '_save_and_load_recipe' in request.POST:
            return self._load_recipe_and_redirect(request, obj)
        if '_save_and_produce' in request.POST:
            return self._produce_and_redirect(request, obj)
        return super().response_change(request, obj)

    def _load_recipe_and_redirect(self, request, obj):
        try:
            summary = apply_recipe_to_order(obj, user=request.user)
            self._message_recipe_summary(request, obj, summary)
        except FabricPostingError as e:
            self.message_user(request, f'فشل تحميل الوصفة: {e}', level=messages.ERROR)
        return redirect(reverse('admin:manufacturing_productionorder_change', args=[obj.pk]))

    def _produce_and_redirect(self, request, obj):
        if obj.status != 'DRAFT':
            self.message_user(request, f'{obj.order_no}: مش في مرحلة خطة — تم الإنتاج قبل كده.',
                                level=messages.WARNING)
        else:
            try:
                produce_production_order(obj, user=request.user)
                self.message_user(
                    request,
                    f'تم إنتاج {obj.order_no} — قماش مخصوم {obj.total_actual_fabric_kg}كجم، '
                    f'تمت إضافة {obj.total_pieces} قطعة للمخزن '
                    f'بتكلفة وحدة {obj.cost_per_piece} جنيه/قطعة.',
                    level=messages.SUCCESS,
                )
            except FabricPostingError as e:
                self.message_user(request, f'فشل الإنتاج: {e}', level=messages.ERROR)
        return redirect(reverse('admin:manufacturing_productionorder_change', args=[obj.pk]))


# ============================================================
#  Masters: sizes + product notes + accessories (Phase 2c)
# ============================================================

@admin.register(Size)
class SizeAdmin(admin.ModelAdmin):
    list_display = ('code', 'sort_order', 'active')
    list_editable = ('sort_order', 'active')
    search_fields = ('code',)


@admin.register(ProductionSubModel)
class ProductionSubModelAdmin(admin.ModelAdmin):
    """ملاحظات المنتج / بيانات القص — تُدار غالباً عبر popup من بنود كميات المقاسات."""
    list_display = ('__str__', 'fabric_description', 'chest_color', 'back_color', 'ticket')
    search_fields = ('fabric_description', 'chest_color', 'back_color',
                     'sleeve_color', 'shorts_color', 'ticket', 'notes')
    fieldsets = (
        ('عام', {'fields': ('fabric_description', 'ticket', 'notes')}),
        ('الصدر', {'fields': ('chest_type', 'chest_color', 'chest_notes')}),
        ('الظهر', {'fields': ('back_type', 'back_color', 'back_notes')}),
        ('الكم', {'fields': ('sleeve_type', 'sleeve_color', 'sleeve_notes')}),
        ('الشورت', {'fields': ('shorts_pattern', 'shorts_type', 'shorts_color', 'shorts_notes')}),
    )

    def get_search_results(self, request, queryset, search_term):
        """ملاحظات المنتج بتتكتب جديدة لكل سطر مقاس عن طريق زرار ➕ —
        مش بنختار من قائمة قديمة، فبنرجّع نتيجة فاضية في الـ autocomplete."""
        return queryset.none(), False


@admin.register(Accessory)
class AccessoryAdmin(admin.ModelAdmin):
    list_display = ('code', 'name_ar', 'unit', 'current_stock', 'average_cost',
                    'default_unit_cost', 'buy_link', 'active')
    list_filter = ('active', 'unit')
    search_fields = ('code', 'name_ar', 'notes')
    readonly_fields = ('code', 'current_stock', 'average_cost', 'created_at')

    def buy_link(self, obj):
        if not obj.pk:
            return ''
        # الشراء بقى عن طريق فاتورة شراء الإكسسوارات (فاتورة واحدة = كذا صنف).
        url = reverse('admin:manufacturing_accessorypurchaseinvoice_add')
        return format_html(
            '<a href="{}" style="background:#15803d;color:white;padding:3px 8px;'
            'border-radius:3px;text-decoration:none;font-weight:600;" '
            'title="افتح فاتورة شراء جديدة وضيف الصنف ده كبند">🛒 فاتورة شراء</a>',
            url,
        )
    buy_link.short_description = ''


# ============================================================
#  Accessory purchasing (item 9)
# ============================================================

# شاشة "مشتريات الإكسسوارات" المفردة اتشالت من القايمة. الشراء بقى عن طريق
# "فاتورة شراء إكسسوارات" (بند واحد = صنف، أو كذا صنف في فاتورة واحدة).
# الكلاس سايبينه للمرجع بس مش متسجّل (AccessoryPurchase بقى بند داخل الفاتورة فقط).
class AccessoryPurchaseAdmin(StayOnPageMixin, LockAfterPostMixin, admin.ModelAdmin):
    lock_field = 'is_posted'
    unlock_always = ('notes',)
    list_display = ('purchase_no', 'invoice', 'date', 'accessory', 'quantity', 'unit_cost',
                    'total_cost_col', 'payment_method', 'cash_account', 'is_posted')
    list_filter = ('is_posted', 'payment_method', 'date', 'cash_account')
    search_fields = ('purchase_no', 'accessory__name_ar', 'accessory__code', 'notes')
    date_hierarchy = 'date'
    autocomplete_fields = ('accessory', 'supplier', 'cash_account')
    readonly_fields = ('purchase_no', 'is_posted', 'journal_entry',
                       'total_cost_display', 'created_at')
    fieldsets = (
        ('بيانات الشراء', {'fields': ('purchase_no', 'date', 'accessory')}),
        ('الكمية والسعر', {'fields': ('quantity', 'unit_cost', 'total_cost_display')}),
        ('الدفع', {'fields': ('payment_method', 'cash_account', 'supplier'),
                    'description': 'مدفوع: اختار النقدية/البنك/المحفظة. '
                                   'آجل: اختار المورد (هيتسجّل في رصيده).'}),
        ('ملاحظات', {'fields': ('notes', 'is_posted', 'journal_entry', 'created_at')}),
    )
    actions = ('action_post',)
    change_form_template = 'admin/manufacturing/accessorypurchase/change_form.html'

    def total_cost_col(self, obj):
        return f'{fmt_money(obj.total_cost)} ج'
    total_cost_col.short_description = 'الإجمالي'

    def total_cost_display(self, obj):
        if not obj.pk:
            return '—'
        return f'{fmt_money(obj.total_cost)} جنيه'
    total_cost_display.short_description = 'إجمالي الشراء'

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    @admin.action(description='ترحيل المختار (قيد محاسبي + زيادة رصيد الإكسسوار)')
    def action_post(self, request, queryset):
        ok = 0
        for p in queryset:
            try:
                post_accessory_purchase(p, user=request.user)
                ok += 1
            except FabricPostingError as e:
                self.message_user(request, f'{p.purchase_no}: {e}', level=messages.ERROR)
        if ok:
            self.message_user(request, f'تم ترحيل {ok} عملية شراء.', level=messages.SUCCESS)

    def response_add(self, request, obj, post_url_continue=None):
        if '_save_and_post' in request.POST:
            return self._post_and_redirect(request, obj)
        return super().response_add(request, obj, post_url_continue)

    def response_change(self, request, obj):
        if '_save_and_post' in request.POST:
            return self._post_and_redirect(request, obj)
        return super().response_change(request, obj)

    def _post_and_redirect(self, request, obj):
        if obj.is_posted:
            self.message_user(request, f'{obj.purchase_no}: مرحّل من قبل.', level=messages.WARNING)
        else:
            try:
                post_accessory_purchase(obj, user=request.user)
                self.message_user(
                    request,
                    f'تم ترحيل الشراء {obj.purchase_no} — رصيد {obj.accessory.name_ar} اتحدث.',
                    level=messages.SUCCESS)
            except FabricPostingError as e:
                self.message_user(request, f'فشل الترحيل: {e}', level=messages.ERROR)
        return redirect(reverse('admin:manufacturing_accessorypurchase_change', args=[obj.pk]))


# ============================================================
#  Multi-line accessory purchase invoice (header + AccessoryPurchase lines)
# ============================================================

class AccessoryPurchaseLineInline(LockedInlineMixin, admin.TabularInline):
    """بنود فاتورة شراء الإكسسوارات — كل بند = صنف/كمية/سعر."""
    model = AccessoryPurchase
    fk_name = 'invoice'
    extra = 1
    autocomplete_fields = ('accessory',)
    fields = ('accessory', 'quantity', 'unit_cost',
              'line_total_display', 'purchase_no', 'is_posted')
    readonly_fields = ('line_total_display', 'purchase_no', 'is_posted')

    def line_total_display(self, obj):
        if not obj or not obj.pk:
            return '—'
        return f'{fmt_money(obj.total_cost)} ج'
    line_total_display.short_description = 'إجمالي البند'


@admin.register(AccessoryPurchaseInvoice)
class AccessoryPurchaseInvoiceAdmin(StayOnPageMixin, LockAfterPostMixin, admin.ModelAdmin):
    lock_field = 'is_posted'
    unlock_always = ('notes',)
    list_display = ('invoice_no', 'supplier', 'date', 'payment_method',
                    'line_count_col', 'total_col', 'is_posted')
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
    inlines = [AccessoryPurchaseLineInline]
    actions = ('action_post',)
    change_form_template = 'admin/manufacturing/accessorypurchaseinvoice/change_form.html'

    def line_count_col(self, obj):
        return obj.line_count
    line_count_col.short_description = 'عدد البنود'

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
        """انسخ بيانات الهيدر (مورد/تاريخ/دفع) على كل بند قبل الحفظ."""
        if formset.model is AccessoryPurchase:
            inv = form.instance
            instances = formset.save(commit=False)
            for inst in instances:
                inst.invoice = inv
                inst.date = inv.date
                inst.supplier = inv.supplier
                inst.payment_method = inv.payment_method
                inst.cash_account = inv.cash_account
                if not inst.created_by_id:
                    inst.created_by = request.user
                inst.save()
            for obj in formset.deleted_objects:
                obj.delete()
            formset.save_m2m()
        else:
            super().save_formset(request, form, formset, change)

    @admin.action(description='ترحيل المختار (قيد محاسبي واحد + زيادة أرصدة الأصناف)')
    def action_post(self, request, queryset):
        ok = 0
        for inv in queryset:
            try:
                post_accessory_purchase_invoice(inv, user=request.user)
                ok += 1
            except FabricPostingError as e:
                self.message_user(request, f'{inv.invoice_no}: {e}', level=messages.ERROR)
        if ok:
            self.message_user(request, f'تم ترحيل {ok} فاتورة.', level=messages.SUCCESS)

    def response_add(self, request, obj, post_url_continue=None):
        if '_save_and_post' in request.POST:
            return self._post_and_redirect(request, obj)
        return super().response_add(request, obj, post_url_continue)

    def response_change(self, request, obj):
        if '_save_and_post' in request.POST:
            return self._post_and_redirect(request, obj)
        return super().response_change(request, obj)

    def _post_and_redirect(self, request, obj):
        if obj.is_posted:
            self.message_user(request, f'{obj.invoice_no}: مرحّلة من قبل.', level=messages.WARNING)
        else:
            try:
                post_accessory_purchase_invoice(obj, user=request.user)
                self.message_user(
                    request,
                    f'تم ترحيل الفاتورة {obj.invoice_no} — {obj.line_count} بند بإجمالي '
                    f'{fmt_money(obj.total)} جنيه + قيد محاسبي واحد.',
                    level=messages.SUCCESS)
            except FabricPostingError as e:
                self.message_user(request, f'فشل الترحيل: {e}', level=messages.ERROR)
        return redirect(reverse('admin:manufacturing_accessorypurchaseinvoice_change', args=[obj.pk]))


# ============================================================
#  Fabric movement (read-only log)
# ============================================================

@admin.register(FabricMovement)
class FabricMovementAdmin(admin.ModelAdmin):
    list_display = ('id', 'batch', 'date', 'movement_type', 'quantity_kg',
                    'cost_per_kg_snapshot', 'notes')
    list_filter = ('movement_type', 'date')
    search_fields = ('batch__batch_no', 'notes')
    date_hierarchy = 'date'
    readonly_fields = ('batch', 'date', 'movement_type', 'quantity_kg', 'cost_per_kg_snapshot',
                       'document_type', 'document_id', 'notes', 'created_by',
                       'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# ============================================================
#  Product recipe / BOM per size (Phase 3)
# ============================================================

class ProductSizeAccessoryInline(admin.TabularInline):
    """إكسسوارات وصفة المقاس — الكمية للقطعة الواحدة."""
    model = ProductSizeAccessory
    extra = 1
    fields = ('accessory', 'qty_per_piece')
    autocomplete_fields = ('accessory',)


@admin.register(ProductSizeRecipe)
class ProductSizeRecipeAdmin(StayOnPageMixin, admin.ModelAdmin):
    list_display = ('product', 'size', 'fabric_qty_kg', 'labor_cost',
                    'selling_price', 'reorder_level', 'accessories_count')
    # تعديل سعر البيع (والتكلفة/حد الطلب) مباشرة من القائمة عشان تقدر تدخل أسعار
    # كل الوصفات بسرعة — السعر ده هو اللي بيظهر في فاتورة البيع.
    list_editable = ('fabric_qty_kg', 'labor_cost', 'selling_price', 'reorder_level')
    list_filter = ('product', 'size')
    search_fields = ('product__code', 'product__name_ar', 'size__code')
    autocomplete_fields = ('product', 'size')
    inlines = [ProductSizeAccessoryInline]
    fields = ('product', 'size', 'fabric_qty_kg', 'labor_cost',
              'selling_price', 'reorder_level', 'notes')

    def accessories_count(self, obj):
        return obj.accessories.count()
    accessories_count.short_description = 'عدد الإكسسوارات'
