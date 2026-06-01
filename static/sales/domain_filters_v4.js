/* Roma ERP — dependent-dropdown filters for the admin.
 *
 *   1. SalesInvoice / SalesReturn lines:
 *      Pick the product (item) first, then the size dropdown is repopulated
 *      with ONLY that product's sizes (variants).
 *
 *   2. Receipt allocations + SalesReturn original_invoice:
 *      When the customer changes, the invoice dropdown is repopulated with
 *      ONLY that customer's POSTED invoices.
 */
(function () {
    'use strict';

    var SIZE_PLACEHOLDER = '— اختار المقاس —';

    function waitForJQ(cb, attempts) {
        attempts = attempts || 0;
        var $ = (window.django && window.django.jQuery) || window.jQuery;
        if ($) { cb($); return; }
        if (attempts > 50) {
            console.warn('[Roma] jQuery not available — domain filters disabled');
            return;
        }
        setTimeout(function () { waitForJQ(cb, attempts + 1); }, 100);
    }

    waitForJQ(function ($) {
        console.log('[Roma] domain filters loading');

        function findRow($field) {
            var $row = $field.closest('tr');
            if ($row.length === 0) $row = $field.closest('.form-row, fieldset, .module');
            return $row;
        }

        // ============================================================
        // SIZE FILTER — per-line: product → that product's sizes only
        // ============================================================

        function resetSize($variant) {
            $variant.empty().append($('<option value="">' + SIZE_PLACEHOLDER + '</option>'));
        }

        function loadVariantsForRow($row, itemId) {
            var $variant = $row.find('select[name$="-variant"]');
            if (!$variant.length) return;
            var prevValue = $variant.val();

            if (!itemId) {
                resetSize($variant);
                return;
            }

            $.getJSON('/sales/item/' + itemId + '/variants/')
                .done(function (data) {
                    resetSize($variant);
                    $.each(data.variants, function (_, v) {
                        $variant.append(
                            $('<option></option>')
                                .val(v.id)
                                .text('مقاس ' + v.size + '  (متاح: ' + v.current_stock + ')')
                        );
                    });
                    // Keep the previous value if it still belongs to this product
                    if (prevValue && data.variants.some(function (v) { return String(v.id) === String(prevValue); })) {
                        $variant.val(prevValue);
                    } else {
                        $variant.val('');
                    }
                })
                .fail(function (xhr) {
                    console.warn('[Roma] variants endpoint failed:', xhr.status);
                });
        }

        function initVariantFiltersFor($scope) {
            $scope.find('select[name$="-item"]').each(function () {
                var $itemField = $(this);
                var $row = findRow($itemField);
                var itemId = $itemField.val();
                if (itemId) {
                    loadVariantsForRow($row, itemId);
                } else {
                    // No product chosen yet — keep the size dropdown clean.
                    var $variant = $row.find('select[name$="-variant"]');
                    if ($variant.length) resetSize($variant);
                }
            });
        }

        $(document).on('change', 'select[name$="-item"]', function () {
            loadVariantsForRow(findRow($(this)), $(this).val());
        });
        $(document).on('select2:select', 'select[name$="-item"]', function () {
            loadVariantsForRow(findRow($(this)), $(this).val());
        });

        // ============================================================
        // INVOICE FILTER — customer → that customer's POSTED invoices
        // ============================================================

        function loadInvoicesForCustomer(customerId) {
            var $allocSelects = $('select[name^="allocations-"][name$="-invoice"]');
            var $originalInvoice = $('select#id_original_invoice');
            var $targets = $allocSelects.add($originalInvoice);
            if (!$targets.length) return;

            if (!customerId) {
                $targets.each(function () {
                    $(this).empty().append($('<option value="">— اختر العميل أولاً —</option>'));
                });
                return;
            }

            $.getJSON('/sales/customer/' + customerId + '/invoices/')
                .done(function (data) {
                    $targets.each(function () {
                        var $sel = $(this);
                        var prevValue = $sel.val();
                        $sel.empty().append($('<option value="">— اختر فاتورة —</option>'));
                        $.each(data.invoices, function (_, inv) {
                            var label = inv.invoice_no + ' — ' + inv.grand_total + ' EGP '
                                      + '(متبقي: ' + inv.balance_due + ')';
                            $sel.append($('<option></option>').val(inv.id).text(label));
                        });
                        if (prevValue && data.invoices.some(function (i) { return String(i.id) === String(prevValue); })) {
                            $sel.val(prevValue);
                        }
                    });
                })
                .fail(function (xhr) {
                    console.warn('[Roma] invoices endpoint failed:', xhr.status);
                });
        }

        function initInvoiceFilter() {
            var $customer = $('#salesinvoice_form select[name="customer"], #receipt_form select[name="customer"], #salesreturn_form select[name="customer"]').first();
            if (!$customer.length) {
                $customer = $('select#id_customer').first();
            }
            if ($customer.length && $customer.val()) {
                loadInvoicesForCustomer($customer.val());
            }
        }

        $(document).on('change', 'select[name="customer"]', function () {
            loadInvoicesForCustomer($(this).val());
        });
        $(document).on('select2:select', 'select[name="customer"]', function () {
            loadInvoicesForCustomer($(this).val());
        });

        // ============================================================
        // Initial page load + dynamically added rows
        // ============================================================

        $(document).on('formset:added', function () {
            initVariantFiltersFor($('body'));
            var $customer = $('select#id_customer').first();
            if ($customer.length && $customer.val()) {
                loadInvoicesForCustomer($customer.val());
            }
        });

        $(function () {
            initVariantFiltersFor($('body'));
            initInvoiceFilter();
        });

        console.log('[Roma] domain filters ready');
    });
})();
