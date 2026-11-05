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

        // عدد القطع في وحدة البيع المختارة في الصف (قطعة=1، وحدة الجملة=حجم وحدة جملة المنتج).
        function unitFactor($row) {
            var unit = $row.find('select[name$="-sale_unit"]').val() || 'PIECE';
            if (unit === 'WHOLESALE') return parseFloat($row.data('wholesaleSize')) || 0;
            return 1;
        }

        // يعيد تسمية خيار «وحدة الجملة» في القائمة لاسم وحدة المنتج الفعلي (دستة/كرتونة).
        function relabelWholesale($row) {
            var lbl = $row.data('wholesaleLabel');
            if (!lbl) return;
            $row.find('select[name$="-sale_unit"] option[value="WHOLESALE"]')
                .text('وحدة الجملة (' + lbl + ')');
        }

        // يحسب سعر الوحدة = سعر القطعة × عدد القطع في الوحدة، ويكتبه في الخانة.
        // force=true معناه المستخدم غيّر الوحدة بنفسه — وقتها نعيد الحساب حتى لو كان
        // كاتب سعر قبل كده (لأن تغيير الوحدة معناه سعر جديد).
        function applyUnitPrice($row, force) {
            var $price = $row.find('input[name$="-unit_price"]').first();
            if ($price.length === 0) return;
            if (!force && isUserPriced($price)) return;
            var piece = parseFloat($row.data('piecePrice'));
            if (isNaN(piece) || piece <= 0) return;
            var factor = unitFactor($row);
            if (factor <= 0) return;  // كرتونة من غير عدد قطع — مفيش سعر
            var val = (piece * factor).toFixed(2);
            $price.val(val);
            $price.data('userEdited', false);  // ده سعر تلقائي مش يدوي
            $price.trigger('change');
        }

        function fetchAndApply(itemId, variantId, $row) {
            var $price = $row.find('input[name$="-unit_price"]').first();
            if ($price.length === 0) return;
            var url = '/sales/item/' + itemId + '/price/';
            if (variantId) url += '?variant=' + variantId;
            $.getJSON(url)
                .done(function (data) {
                    console.log('[Roma] price endpoint →', data);
                    if (!data) return;
                    // خزّن سعر القطعة + وحدة جملة المنتج على الصف عشان نحسب فوراً عند تغيير الوحدة.
                    $row.data('piecePrice', data.piece_price || data.unit_price);
                    $row.data('wholesaleSize', data.wholesale_unit_size || 0);
                    $row.data('wholesaleLabel', data.wholesale_unit_label || 'دستة');
                    relabelWholesale($row);
                    applyUnitPrice($row, false);
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

        // لما المستخدم يغيّر وحدة البيع (قطعة/دستة/كرتونة) → نعيد حساب السعر على حسب الوحدة.
        $(document).on('change', 'select[name$="-sale_unit"]', function () {
            var $row = findRow($(this));
            // لو لسه ما جبناش سعر القطعة لهذا الصف (مثلاً فتحنا فاتورة قديمة)، نجيبه الأول.
            if ($row.data('piecePrice') === undefined) {
                var itemId = $row.find('select[name$="-item"]').val();
                var variantId = $row.find('select[name$="-variant"]').val();
                if (itemId && variantId) { fetchAndApply(itemId, variantId, $row); return; }
            }
            applyUnitPrice($row, true);
        });

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

        // ============================================================
        // خانة حذف السطر — نوضّحها (أحمر + كلمة «حذف») عشان المستخدم يلاقيها بسهولة.
        // البند بيتمسح فعلياً لما تعلّم الخانة وتدوس «حفظ» (للفواتير المسودة بس).
        // ============================================================
        function labelDeleteBoxes() {
            $('input[type="checkbox"][name$="-DELETE"]').each(function () {
                var $box = $(this);
                if ($box.data('romaDelLabeled')) return;
                $box.data('romaDelLabeled', true);
                if ($box.next('.roma-del-lbl').length === 0) {
                    $box.after('<span class="roma-del-lbl" style="color:#b71c1c;'
                        + 'font-weight:700;font-size:11px;margin-right:4px;white-space:nowrap;">'
                        + '🗑 حذف</span>');
                }
            });
        }
        $(function () { labelDeleteBoxes(); });
        $(document).on('formset:added', function () { labelDeleteBoxes(); });

        console.log('[Roma] delegation bound (item + variant + price-lock + existing-lock)');
    });
})();
