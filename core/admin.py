from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.urls import reverse

from .admin_mixins import LockAfterPostMixin
from .models import (
    Company, Account, JournalEntry, JournalLine,
    CashAccount, ExpenseCategory, ExpenseVoucher, FixedAsset,
)
from .services import (
    post_expense_voucher, cancel_expense_voucher,
    post_fixed_asset, CorePostingError,
)


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name_ar', 'tax_id', 'phone', 'currency_code', 'default_vat_rate')


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ('code', 'name_ar', 'account_type', 'parent', 'is_group', 'is_active')
    list_filter = ('account_type', 'is_group', 'is_active')
    search_fields = ('code', 'name_ar', 'name_en')
    list_select_related = ('parent',)


class JournalLineInline(admin.TabularInline):
    model = JournalLine
    extra = 0
    fields = ('account', 'debit', 'credit', 'description', 'customer', 'variant')
    autocomplete_fields = ('account', 'customer', 'variant')


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = ('id', 'date', 'reference', 'description', 'status',
                     'total_debit', 'total_credit', 'source_doc_type')
    list_filter = ('status', 'source_doc_type', 'date')
    search_fields = ('reference', 'description', 'source_doc_type')
    date_hierarchy = 'date'
    inlines = [JournalLineInline]
    readonly_fields = ('total_debit', 'total_credit', 'created_at', 'created_by')


# ============================================================
#  Treasury — cash accounts (item 5)
# ============================================================

@admin.register(CashAccount)
class CashAccountAdmin(admin.ModelAdmin):
    list_display = ('name', 'account_type', 'bank_name', 'account_number',
                    'gl_account', 'is_default', 'active')
    list_filter = ('account_type', 'active', 'is_default')
    search_fields = ('name', 'bank_name', 'account_number')
    readonly_fields = ('gl_account', 'created_at')
    fields = ('name', 'account_type', 'bank_name', 'account_number',
              'is_default', 'active', 'gl_account', 'created_at')


# ============================================================
#  Expense vouchers (item 11)
# ============================================================

@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ('name_ar', 'gl_account', 'active')
    list_filter = ('active',)
    search_fields = ('name_ar',)
    autocomplete_fields = ('gl_account',)


@admin.action(description='ترحيل سندات الصرف المحددة')
def action_post_vouchers(modeladmin, request, queryset):
    posted = 0
    for v in queryset:
        try:
            post_expense_voucher(v, user=request.user)
            posted += 1
        except CorePostingError as e:
            messages.error(request, f'{v.voucher_no}: {e}')
        except Exception as e:
            messages.error(request, f'{v.voucher_no}: خطأ غير متوقع — {e}')
    if posted:
        messages.success(request, f'تم ترحيل {posted} سند صرف.')


@admin.action(description='إلغاء سندات الصرف المحددة')
def action_cancel_vouchers(modeladmin, request, queryset):
    cancelled = 0
    for v in queryset:
        try:
            cancel_expense_voucher(v, user=request.user)
            cancelled += 1
        except CorePostingError as e:
            messages.error(request, f'{v.voucher_no}: {e}')
    if cancelled:
        messages.success(request, f'تم إلغاء {cancelled} سند صرف.')


@admin.register(ExpenseVoucher)
class ExpenseVoucherAdmin(LockAfterPostMixin, admin.ModelAdmin):
    lock_field = 'status'
    lock_values = ('POSTED', 'CANCELLED')
    unlock_always = ('notes',)
    list_display = ('voucher_no', 'date', 'category', 'description',
                    'amount', 'cash_account', 'status')
    list_filter = ('status', 'date', 'category', 'cash_account')
    search_fields = ('voucher_no', 'description', 'reference')
    autocomplete_fields = ('category', 'cash_account')
    date_hierarchy = 'date'
    actions = [action_post_vouchers, action_cancel_vouchers]
    readonly_fields = ('voucher_no', 'status', 'journal_entry', 'created_at', 'created_by')
    change_form_template = 'admin/core/expensevoucher/change_form.html'

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def change_view(self, request, object_id, form_url='', extra_context=None):
        extra_context = extra_context or {}
        obj = self.get_object(request, object_id)
        if obj:
            extra_context['show_post_button'] = obj.status == 'DRAFT'
            extra_context['show_cancel_button'] = obj.status == 'POSTED'
        return super().change_view(request, object_id, form_url, extra_context=extra_context)

    def response_change(self, request, obj):
        if '_post_voucher' in request.POST:
            try:
                post_expense_voucher(obj, user=request.user)
                messages.success(request, f'تم ترحيل سند الصرف {obj.voucher_no}.')
            except CorePostingError as e:
                messages.error(request, str(e))
            except Exception as e:
                messages.error(request, f'خطأ غير متوقع: {e}')
            return HttpResponseRedirect(request.path)
        if '_cancel_voucher' in request.POST:
            try:
                cancel_expense_voucher(obj, user=request.user)
                messages.success(request, f'تم إلغاء سند الصرف {obj.voucher_no}.')
            except CorePostingError as e:
                messages.error(request, str(e))
            return HttpResponseRedirect(request.path)
        return super().response_change(request, obj)

    def response_post_save_add(self, request, obj):
        if obj and obj.pk:
            return HttpResponseRedirect(
                reverse('admin:core_expensevoucher_change', args=[obj.pk]))
        return super().response_post_save_add(request, obj)

    def response_post_save_change(self, request, obj):
        if obj and obj.pk:
            return HttpResponseRedirect(
                reverse('admin:core_expensevoucher_change', args=[obj.pk]))
        return super().response_post_save_change(request, obj)


# ============================================================
#  Fixed assets register + purchase (item 10)
# ============================================================

@admin.action(description='ترحيل شراء الأصول المحددة')
def action_post_assets(modeladmin, request, queryset):
    posted = 0
    for a in queryset:
        try:
            post_fixed_asset(a, user=request.user)
            posted += 1
        except CorePostingError as e:
            messages.error(request, f'{a.asset_no}: {e}')
        except Exception as e:
            messages.error(request, f'{a.asset_no}: خطأ غير متوقع — {e}')
    if posted:
        messages.success(request, f'تم ترحيل {posted} أصل.')


@admin.register(FixedAsset)
class FixedAssetAdmin(LockAfterPostMixin, admin.ModelAdmin):
    lock_field = 'status'
    lock_values = ('POSTED', 'CANCELLED')
    unlock_always = ('notes', 'location', 'serial_number')
    list_display = ('asset_no', 'name', 'category', 'acquisition_date',
                    'cost', 'payment_method', 'status')
    list_filter = ('status', 'category', 'payment_method', 'acquisition_date')
    search_fields = ('asset_no', 'name', 'serial_number', 'location')
    autocomplete_fields = ('cash_account', 'supplier')
    date_hierarchy = 'acquisition_date'
    actions = [action_post_assets]
    readonly_fields = ('asset_no', 'status', 'journal_entry', 'created_at', 'created_by')
    change_form_template = 'admin/core/fixedasset/change_form.html'

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def change_view(self, request, object_id, form_url='', extra_context=None):
        extra_context = extra_context or {}
        obj = self.get_object(request, object_id)
        if obj:
            extra_context['show_post_button'] = obj.status == 'DRAFT'
        return super().change_view(request, object_id, form_url, extra_context=extra_context)

    def response_change(self, request, obj):
        if '_post_asset' in request.POST:
            try:
                post_fixed_asset(obj, user=request.user)
                messages.success(request, f'تم ترحيل شراء الأصل {obj.asset_no}.')
            except CorePostingError as e:
                messages.error(request, str(e))
            except Exception as e:
                messages.error(request, f'خطأ غير متوقع: {e}')
            return HttpResponseRedirect(request.path)
        return super().response_change(request, obj)

    def response_post_save_add(self, request, obj):
        if obj and obj.pk:
            return HttpResponseRedirect(
                reverse('admin:core_fixedasset_change', args=[obj.pk]))
        return super().response_post_save_add(request, obj)

    def response_post_save_change(self, request, obj):
        if obj and obj.pk:
            return HttpResponseRedirect(
                reverse('admin:core_fixedasset_change', args=[obj.pk]))
        return super().response_post_save_change(request, obj)
