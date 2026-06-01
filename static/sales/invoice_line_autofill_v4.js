/* Auto-fill unit_price when an Item OR Variant is picked on a Sales Invoice
   or Sales Return line.  Uses event delegation on `document` so it works for
   the initial line AND for every line added later via "Add another". */
(function () {
    'use strict';

    function waitForJQ(cb, attempts) {
        attempts = attempts || 0;
        var $ = (window.django && window.django.jQuery) || window.jQuery;
        if ($) { cb($); return; }
        if (attempts > 50) {
            console.warn('[Roma] jQuery not available after 5s — autofill disabled');
            return;
        }
        setTimeout(function () { waitForJQ(cb, attempts + 1); }, 100);
    }

    waitForJQ(function ($) {
        console.log('[Roma] autofill JS loaded (jQuery ' + $.fn.jquery + ')');

        function findRow($field) {
            var $row = $field.closest('tr');
            if ($row.length === 0) $row = $field.closest('.form-row, fieldset, .module');
            return $row;
        }

        // الخانة بتبقى "ملك المستخدم" أول ما يكتب فيها سعر بإيده — وقتها مننكتبش فوقها أبداً.
        function isUserPriced($price) {
            return $price.data('userEdited') === true;
        }

        function fetchAndApply(itemId, variantId, $row) {
            var $price = $row.find('input[name$="-unit_price"]').first();
            if ($price.length === 0) return;
            // لو المستخدم كتب السعر بنفسه، بلاش نجيب سعر الوصفة فوقه.
            if (isUserPriced($price)) return;
            var url = '/sales/item/' + itemId + '/price/';
            if (variantId) url += '?variant=' + variantId;
            $.getJSON(url)
                .done(function (data) {
                    console.log('[Roma] price endpoint →', data);
                    // إعادة فحص بعد رجوع الطلب (async): لو المستخدم كتب سعر في الوقت ده،
                    // منكتبش فوقه — ده كان بيحصل بسبب السباق (race) ويمسح السعر اليدوي.
                    if (isUserPriced($price)) return;
                    // نعبّي بس لما الوصفة فيها سعر فعلي (> 0). صفر (مفيش سعر) منكتبش بيه
                    // فوق سعر المستخدم اليدوي.
                    if (data && data.unit_price && parseFloat(data.unit_price) > 0) {
                        $price.val(data.unit_price);
                        $price.trigger('change');
                    }
                })
                .fail(function (xhr) {
                    console.error('[Roma] price endpoint failed:', xhr.status, xhr.statusText);
                });
        }

        function onItemChange(el) {
            var $row = findRow($(el));
            var itemId = $(el).val();
            console.log('[Roma] item changed → id=' + itemId);
            if (!itemId) return;
            var $variant = $row.find('select[name$="-variant"]');
            var variantId = $variant.length ? $variant.val() : '';
            fetchAndApply(itemId, variantId, $row);
        }

        function onVariantChange(el) {
            var $row = findRow($(el));
            var variantId = $(el).val();
            var itemId = $row.find('select[name$="-item"]').val();
            console.log('[Roma] variant changed → id=' + variantId);
            if (!itemId) return;
            fetchAndApply(itemId, variantId, $row);
        }

        $(document).on('change', 'select[name$="-item"]', function () { onItemChange(this); });
        $(document).on('select2:select', 'select[name$="-item"]', function () { onItemChange(this); });
        $(document).on('change', 'select[name$="-variant"]', function () { onVariantChange(this); });
        $(document).on('select2:select', 'select[name$="-variant"]', function () { onVariantChange(this); });

        // أول ما المستخدم يكتب في خانة السعر بإيده، نعلّمها "ملك المستخدم" فميتكتبش فوقها تلقائياً.
        // ولو فضّاها بإيده تاني، نفكّ القفل عشان يقدر يرجّع سعر المنتج لو اختار مقاس.
        $(document).on('input', 'input[name$="-unit_price"]', function () {
            var v = parseFloat($(this).val());
            $(this).data('userEdited', !isNaN(v) && v > 0);
        });

        // عند فتح/إعادة تحميل الصفحة: أي سعر متعبّي ومتسجّل (> 0) — يعني السعر اللي المستخدم
        // حفظه — نعلّمه "ملك المستخدم" فوراً. كده لما domain_filters تعيد بناء قوائم المقاسات
        // وتطلّق أحداث change تاني، الأوتوفِل ميكتبش سعر المنتج فوق السعر المحفوظ.
        function lockExistingPrices() {
            $('input[name$="-unit_price"]').each(function () {
                var v = parseFloat($(this).val());
                if (!isNaN(v) && v > 0) {
                    $(this).data('userEdited', true);
                }
            });
        }
        // لازم نستنى الـ DOM يجهز عشان خانات السعر تكون موجودة. وبما إن السكريبت ده
        // بيتحمّل قبل domain_filters_v4.js، فهاندلر الـ DOM-ready بتاعه بيتنفّذ الأول،
        // يعني بنقفل الأسعار المحفوظة قبل ما domain_filters تعيد إطلاق أحداث الـ change.
        $(function () { lockExistingPrices(); });

        console.log('[Roma] delegation bound (item + variant + price-lock + existing-lock)');
    });
})();
