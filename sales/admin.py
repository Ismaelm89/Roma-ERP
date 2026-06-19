from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html

from core.admin_mixins import LockAfterPostMixin, LockedInlineMixin
from core.templatetags.money_filters import fmt_money

from .models import (
    Customer, SalesInvoice, SalesInvoiceLine,
    Receipt, ReceiptAllocation,
    SalesReturn, SalesReturnLine,
)
from .services import (
    post_sales_invoice, cancel_sales_invoice,
    post_receipt, cancel_receipt,
    post_sales_return, cancel_sales_return,
    PostingError,
)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('code', 'name_ar', 'phone', 'governorate', 'payment_terms_days',
                     'credit_limit', 'balance_col', 'ledger_link', 'active')
    list_filter = ('active', 'governorate')
    search_fields = ('code', 'name_ar', 'name_en', 'tax_id', 'phone')
    readonly_fields = ('code',)  # auto-assigned C0001, C0002 ...

    def ledger_link(self, obj):
        url = reverse('sales:customer_ledger', args=[obj.pk])
        return format_html('<a href="{}" target="_blank">كشف حساب</a>', url)
    ledger_link.short_description = 'كشف حساب'

    def balance_col(self, obj):
        bal = obj.current_balance
        color = '#b00' if bal > 0 else ('green' if bal < 0 else 'inherit')
        return format_html('<span style="color: {}; font-variant-numeric: tabular-nums;">{}</span>',
                            color, fmt_money(bal))
    balance_col.short_description = 'الرصيد الحالي'


class SalesInvoiceLineInline(LockedInlineMixin, admin.TabularInline):
    model = SalesInvoiceLine
    extra = 1
    # Pick the product (by name), the size, the sale unit (piece/dozen/carton),
    # then the count; price auto-fills (piece price × pieces-per-unit). The size
    # dropdown is narrowed to the chosen product's sizes by domain_filters_v4.js.
    fields = ('item', 'variant', 'sale_unit', 'quantity', 'unit_price', 'line_total')
    autocomplete_fields = ('item',)
    readonly_fields = ('line_total',)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'item':
            kwargs['empty_label'] = '— اختار المنتج —'
        if db_field.name == 'variant':
            kwargs['empty_label'] = '— اختار المقاس —'
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.action(description='ترحيل الفواتير المحددة')
def action_post_invoices(modeladmin, request, queryset):
    posted = 0
    for inv in queryset:
        try:
            post_sales_invoice(inv, user=request.user)
            posted += 1
        except PostingError as e:
            messages.error(request, f'{inv.invoice_no}: {e}')
        except Exception as e:
            messages.error(request, f'{inv.invoice_no}: خطأ غير متوقع — {e}')
    if posted:
        messages.success(request, f'تم ترحيل {posted} فاتورة.')


@admin.action(description='إلغاء الفواتير المحددة (عكس القيد والمخزون)')
def action_cancel_invoices(modeladmin, request, queryset):
    cancelled = 0
    for inv in queryset:
        try:
            cancel_sales_invoice(inv, user=request.user)
            cancelled += 1
        except PostingError as e:
            messages.error(request, f'{inv.invoice_no}: {e}')
    if cancelled:
        messages.success(request, f'تم إلغاء {cancelled} فاتورة.')


@admin.action(description='🖨️ طباعة صورة للفواتير المحددة (صفحة لكل فاتورة)')
def action_print_copies(modeladmin, request, queryset):
    ids = ','.join(str(pk) for pk in queryset.values_list('pk', flat=True))
    return HttpResponseRedirect(f'/sales/invoices/bulk-print-copies/?ids={ids}')


@admin.register(SalesInvoice)
class SalesInvoiceAdmin(LockAfterPostMixin, admin.ModelAdmin):
    lock_field = 'status'
    lock_values = ('POSTED', 'CANCELLED')
    unlock_always = ('notes',)
    list_display = ('invoice_no', 'date', 'customer', 'doc_discount_percent', 'grand_total',
                     'profit_col', 'paid_amount_col', 'balance_due_col', 'status', 'print_link')
    list_filter = ('status', 'date')
    search_fields = ('invoice_no', 'customer__code', 'customer__name_ar', 'notes')
    autocomplete_fields = ('customer',)
    inlines = [SalesInvoiceLineInline]
    date_hierarchy = 'date'
    actions = [action_post_invoices, action_cancel_invoices, action_print_copies]
    fields = ('invoice_no', 'date', 'customer', 'notes',
              'doc_discount_percent', 'doc_discount_amount',
              'cash_payment_percent', 'installment_frequency',
              'subtotal', 'grand_total',
              'total_cogs_display', 'profit_display',
              'status', 'posted_at', 'posted_by', 'journal_entry',
              'created_at', 'created_by')
    readonly_fields = ('invoice_no', 'subtotal', 'grand_total',
                       'doc_discount_amount', 'total_cogs_display', 'profit_display',
                       'status', 'posted_at', 'posted_by', 'journal_entry',
                       'created_at', 'created_by')

    def total_cogs_display(self, obj):
        if not obj or not obj.pk:
            return '—'
        return f'{fmt_money(obj.total_cogs)} ج'
    total_cogs_display.short_description = 'تكلفة البضاعة المباعة'

    def profit_display(self, obj):
        if not obj or not obj.pk:
            return '—'
        p = obj.profit
        color = '#15803d' if p >= 0 else '#b91c1c'
        label = 'ربح' if p >= 0 else 'خسارة'
        return format_html('<b style="color:{};font-size:14px;">{} ج ({}) · هامش {}%</b>',
                           color, fmt_money(p), label, obj.profit_margin_pct)
    profit_display.short_description = 'الربح / الخسارة'

    def profit_col(self, obj):
        p = obj.profit
        color = '#15803d' if p >= 0 else '#b91c1c'
        return format_html('<b style="color:{}">{}</b>', color, fmt_money(p))
    profit_col.short_description = 'ربح/خسارة'

    class Media:
        js = ('sales/invoice_line_autofill_v4.js', 'sales/domain_filters_v4.js')

    change_form_template = 'admin/sales/salesinvoice/change_form.html'

    def change_view(self, request, object_id, form_url='', extra_context=None):
        extra_context = extra_context or {}
        obj = self.get_object(request, object_id)
        if obj:
            base = reverse('sales:print_invoice', args=[obj.pk])
            extra_context['show_post_button'] = obj.status == 'DRAFT'
            extra_context['show_cancel_button'] = obj.status == 'POSTED'
            extra_context['print_url_original'] = base + '?copy=original'
            extra_context['print_url_copy'] = base + '?copy=copy'
            # "Create return" shortcut — only when invoice is posted
            if obj.status == 'POSTED':
                extra_context['create_return_url'] = reverse(
                    'sales:create_return_from_invoice', args=[obj.pk]
                )
        return super().change_view(request, object_id, form_url, extra_context=extra_context)

    def response_change(self, request, obj):
        if '_post_invoice' in request.POST:
            try:
                post_sales_invoice(obj, user=request.user)
                messages.success(request, f'تم ترحيل الفاتورة {obj.invoice_no}.')
            except PostingError as e:
                messages.error(request, str(e))
            except Exception as e:
                messages.error(request, f'خطأ غير متوقع: {e}')
            return HttpResponseRedirect(request.path)
        if '_cancel_invoice' in request.POST:
            try:
                cancel_sales_invoice(obj, user=request.user)
                messages.success(request, f'تم إلغاء الفاتورة {obj.invoice_no}.')
            except PostingError as e:
                messages.error(request, str(e))
            return HttpResponseRedirect(request.path)
        return super().response_change(request, obj)

    # Keep the user on the invoice page after Save — they decide when to leave.
    def response_post_save_add(self, request, obj):
        if obj and obj.pk:
            return HttpResponseRedirect(
                reverse('admin:sales_salesinvoice_change', args=[obj.pk])
            )
        return super().response_post_save_add(request, obj)

    def response_post_save_change(self, request, obj):
        if obj and obj.pk:
            return HttpResponseRedirect(
                reverse('admin:sales_salesinvoice_change', args=[obj.pk])
            )
        return super().response_post_save_change(request, obj)

    def paid_amount_col(self, obj):
        return obj.paid_amount
    paid_amount_col.short_description = 'المدفوع'

    def balance_due_col(self, obj):
        return obj.balance_due
    balance_due_col.short_description = 'المتبقي'

    def print_link(self, obj):
        url = reverse('sales:print_invoice', args=[obj.pk])
        return format_html('<a href="{}" target="_blank">🖨️ طباعة</a>', url)
    print_link.short_description = 'طباعة'

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        """After lines are saved, recalc line totals + invoice totals so the
        admin preview shows accurate numbers without needing to post first."""
        super().save_related(request, form, formsets, change)
        invoice = form.instance
        if invoice.status == 'DRAFT':
            # احذف البنود المكررة بالظبط (نفس المقاس + الوحدة + السعر + الكمية) — حماية
            # من أي تكرار بيحصل بالغلط وقت الإدخال؛ بنسيب أقدم نسخة ونمسح الباقي.
            seen = set()
            dup_ids = []
            for line in invoice.lines.order_by('id'):
                key = (line.variant_id, line.sale_unit,
                       str(line.unit_price), str(line.quantity))
                if key in seen:
                    dup_ids.append(line.id)
                else:
                    seen.add(key)
            if dup_ids:
                invoice.lines.filter(id__in=dup_ids).delete()
                messages.warning(request, f'تم حذف {len(dup_ids)} بند مكرر تلقائياً.')
            for line in invoice.lines.all():
                line.recalc()
                line.save(update_fields=['line_total'])
            invoice.recalc_totals()


class ReceiptAllocationInline(LockedInlineMixin, admin.TabularInline):
    model = ReceiptAllocation
    extra = 1
    # `invoice` is plain <select> — JS filters it to receipt.customer's POSTED invoices.

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'invoice':
            # Default queryset: only POSTED invoices (JS narrows further by customer)
            from .models import SalesInvoice
            kwargs['queryset'] = SalesInvoice.objects.filter(status='POSTED').order_by('-date')
            kwargs['empty_label'] = '— اختر فاتورة —'
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.action(description='ترحيل سندات القبض المحددة')
def action_post_receipts(modeladmin, request, queryset):
    posted = 0
    for r in queryset:
        try:
            post_receipt(r, user=request.user)
            posted += 1
        except PostingError as e:
            messages.error(request, f'{r.receipt_no}: {e}')
        except Exception as e:
            messages.error(request, f'{r.receipt_no}: خطأ غير متوقع — {e}')
    if posted:
        messages.success(request, f'تم ترحيل {posted} سند قبض.')


@admin.action(description='إلغاء سندات القبض المحددة')
def action_cancel_receipts(modeladmin, request, queryset):
    cancelled = 0
    for r in queryset:
        try:
            cancel_receipt(r, user=request.user)
            cancelled += 1
        except PostingError as e:
            messages.error(request, f'{r.receipt_no}: {e}')
    if cancelled:
        messages.success(request, f'تم إلغاء {cancelled} سند قبض.')


class SalesReturnLineInline(LockedInlineMixin, admin.TabularInline):
    model = SalesReturnLine
    extra = 1
    fields = ('item', 'variant', 'quantity', 'unit_price', 'line_total')
    autocomplete_fields = ('item',)
    readonly_fields = ('line_total',)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'item':
            kwargs['empty_label'] = '— اختار المنتج —'
        if db_field.name == 'variant':
            kwargs['empty_label'] = '— اختار المقاس —'
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.action(description='ترحيل المرتجعات المحددة')
def action_post_returns(modeladmin, request, queryset):
    posted = 0
    for r in queryset:
        try:
            post_sales_return(r, user=request.user)
            posted += 1
        except PostingError as e:
            messages.error(request, f'{r.return_no}: {e}')
        except Exception as e:
            messages.error(request, f'{r.return_no}: خطأ غير متوقع — {e}')
    if posted:
        messages.success(request, f'تم ترحيل {posted} مرتجع.')


@admin.action(description='إلغاء المرتجعات المحددة')
def action_cancel_returns(modeladmin, request, queryset):
    cancelled = 0
    for r in queryset:
        try:
            cancel_sales_return(r, user=request.user)
            cancelled += 1
        except PostingError as e:
            messages.error(request, f'{r.return_no}: {e}')
    if cancelled:
        messages.success(request, f'تم إلغاء {cancelled} مرتجع.')


@admin.register(SalesReturn)
class SalesReturnAdmin(LockAfterPostMixin, admin.ModelAdmin):
    lock_field = 'status'
    lock_values = ('POSTED', 'CANCELLED')
    unlock_always = ('notes',)
    list_display = ('return_no', 'date', 'customer', 'original_invoice',
                     'grand_total', 'status')
    list_filter = ('status', 'date')
    search_fields = ('return_no', 'customer__code', 'customer__name_ar',
                      'original_invoice__invoice_no', 'reason')
    # original_invoice is a plain <select>; JS filters it by the chosen customer.
    autocomplete_fields = ('customer',)
    inlines = [SalesReturnLineInline]
    date_hierarchy = 'date'
    actions = [action_post_returns, action_cancel_returns]
    fields = ('return_no', 'date', 'customer', 'original_invoice',
              'reason', 'notes',
              'subtotal', 'grand_total',
              'status', 'posted_at', 'posted_by', 'journal_entry',
              'created_at', 'created_by')
    readonly_fields = ('return_no', 'subtotal', 'grand_total',
                       'status', 'posted_at', 'posted_by', 'journal_entry',
                       'created_at', 'created_by')

    class Media:
        js = ('sales/invoice_line_autofill_v4.js', 'sales/domain_filters_v4.js')

    change_form_template = 'admin/sales/salesreturn/change_form.html'

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'original_invoice':
            kwargs['queryset'] = SalesInvoice.objects.filter(status='POSTED').order_by('-date')
            kwargs['empty_label'] = '— اختر الفاتورة الأصلية (اختياري) —'
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def change_view(self, request, object_id, form_url='', extra_context=None):
        extra_context = extra_context or {}
        obj = self.get_object(request, object_id)
        if obj:
            base = reverse('sales:print_return', args=[obj.pk])
            extra_context['show_post_button'] = obj.status == 'DRAFT'
            extra_context['show_cancel_button'] = obj.status == 'POSTED'
            extra_context['print_url_original'] = base + '?copy=original'
            extra_context['print_url_copy'] = base + '?copy=copy'
            # Show the "copy lines from invoice" button only when:
            #   - status is DRAFT (still editable)
            #   - there's an original_invoice picked
            #   - there are no lines yet (avoid duplicating)
            extra_context['show_copy_button'] = (
                obj.status == 'DRAFT'
                and obj.original_invoice_id is not None
                and not obj.lines.exists()
            )
        return super().change_view(request, object_id, form_url, extra_context=extra_context)

    def response_change(self, request, obj):
        if '_post_return' in request.POST:
            try:
                post_sales_return(obj, user=request.user)
                messages.success(request, f'تم ترحيل المرتجع {obj.return_no}.')
            except PostingError as e:
                messages.error(request, str(e))
            except Exception as e:
                messages.error(request, f'خطأ غير متوقع: {e}')
            return HttpResponseRedirect(request.path)
        if '_cancel_return' in request.POST:
            try:
                cancel_sales_return(obj, user=request.user)
                messages.success(request, f'تم إلغاء المرتجع {obj.return_no}.')
            except PostingError as e:
                messages.error(request, str(e))
            return HttpResponseRedirect(request.path)
        if '_copy_from_invoice' in request.POST:
            self._copy_lines_from_invoice(request, obj)
            return HttpResponseRedirect(request.path)
        return super().response_change(request, obj)

    def _copy_lines_from_invoice(self, request, obj):
        """Copy every line from obj.original_invoice into obj as return lines.
        Used for the 'مرتجع كلي' workflow. Skipped if obj has lines already."""
        if not obj.original_invoice_id:
            messages.error(request, 'لم يتم اختيار الفاتورة الأصلية.')
            return
        if obj.status != 'DRAFT':
            messages.error(request, 'لا يمكن نسخ البنود لمرتجع مرحّل.')
            return
        if obj.lines.exists():
            messages.error(request, 'المرتجع فيه بنود بالفعل — احذفها أولاً ثم انسخ.')
            return

        copied = 0
        for inv_line in obj.original_invoice.lines.select_related('item', 'variant').all():
            SalesReturnLine.objects.create(
                return_doc=obj,
                item=inv_line.item,
                variant=inv_line.variant,  # preserves piece vs bundle
                quantity=inv_line.quantity,
                unit_price=inv_line.unit_price,
            )
            copied += 1

        # Recompute totals
        for line in obj.lines.all():
            line.recalc()
            line.save(update_fields=['line_total'])
        obj.recalc_totals()

        messages.success(request,
            f'تم نسخ {copied} بند من الفاتورة {obj.original_invoice.invoice_no} '
            f'كمرتجع كلي. تقدر تحذف أي بند مش عايز ترجعه قبل الترحيل.'
        )

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        ret = form.instance
        if ret.status == 'DRAFT':
            for line in ret.lines.all():
                line.recalc()
                line.save(update_fields=['line_total'])
            ret.recalc_totals()

    def response_post_save_add(self, request, obj):
        if obj and obj.pk:
            return HttpResponseRedirect(reverse('admin:sales_salesreturn_change', args=[obj.pk]))
        return super().response_post_save_add(request, obj)

    def response_post_save_change(self, request, obj):
        if obj and obj.pk:
            return HttpResponseRedirect(reverse('admin:sales_salesreturn_change', args=[obj.pk]))
        return super().response_post_save_change(request, obj)


@admin.register(Receipt)
class ReceiptAdmin(LockAfterPostMixin, admin.ModelAdmin):
    lock_field = 'status'
    lock_values = ('POSTED', 'CANCELLED')
    unlock_always = ('notes',)
    list_display = ('receipt_no', 'date', 'customer', 'method', 'cash_account', 'amount', 'status')
    list_filter = ('method', 'status', 'date', 'cash_account')
    search_fields = ('receipt_no', 'customer__code', 'customer__name_ar', 'reference')
    autocomplete_fields = ('customer',)
    inlines = [ReceiptAllocationInline]
    date_hierarchy = 'date'
    actions = [action_post_receipts, action_cancel_receipts]
    readonly_fields = ('receipt_no', 'status', 'posted_at', 'journal_entry', 'created_at', 'created_by')

    class Media:
        js = ('sales/domain_filters_v4.js',)

    change_form_template = 'admin/sales/receipt/change_form.html'

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def change_view(self, request, object_id, form_url='', extra_context=None):
        extra_context = extra_context or {}
        obj = self.get_object(request, object_id)
        if obj:
            base = reverse('sales:print_receipt', args=[obj.pk])
            extra_context['show_post_button'] = obj.status == 'DRAFT'
            extra_context['show_cancel_button'] = obj.status == 'POSTED'
            extra_context['print_url_original'] = base + '?copy=original'
            extra_context['print_url_copy'] = base + '?copy=copy'
        return super().change_view(request, object_id, form_url, extra_context=extra_context)

    def response_change(self, request, obj):
        if '_post_receipt' in request.POST:
            try:
                post_receipt(obj, user=request.user)
                messages.success(request, f'تم ترحيل سند القبض {obj.receipt_no}.')
            except PostingError as e:
                messages.error(request, str(e))
            return HttpResponseRedirect(request.path)
        if '_cancel_receipt' in request.POST:
            try:
                cancel_receipt(obj, user=request.user)
                messages.success(request, f'تم إلغاء سند القبض {obj.receipt_no}.')
            except PostingError as e:
                messages.error(request, str(e))
            return HttpResponseRedirect(request.path)
        return super().response_change(request, obj)

    # Stay on the receipt page after Save.
    def response_post_save_add(self, request, obj):
        if obj and obj.pk:
            return HttpResponseRedirect(
                reverse('admin:sales_receipt_change', args=[obj.pk])
            )
        return super().response_post_save_add(request, obj)

    def response_post_save_change(self, request, obj):
        if obj and obj.pk:
            return HttpResponseRedirect(
                reverse('admin:sales_receipt_change', args=[obj.pk])
            )
        return super().response_post_save_change(request, obj)
