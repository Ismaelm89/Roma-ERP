/* فاتورة شراء منتجات تامة: يعيد تسمية خيار «وحدة الجملة» في خانة وحدة الشراء
   لاسم وحدة الجملة الفعلي للمنتج (دستة/كرتونة) حسب الصنف المختار. */
(function () {
    'use strict';
    function waitJQ(cb, n) {
        n = n || 0;
        var $ = (window.django && window.django.jQuery) || window.jQuery;
        if ($) { cb($); return; }
        if (n > 50) return;
        setTimeout(function () { waitJQ(cb, n + 1); }, 100);
    }
    waitJQ(function ($) {
        function row($el) {
            var $r = $el.closest('tr');
            if (!$r.length) $r = $el.closest('.form-row, fieldset');
            return $r;
        }
        function relabel($row) {
            var w = $row.find('select[name$="-variant"] option:selected').attr('data-wholesale');
            var $u = $row.find('select[name$="-purchase_unit"] option[value="WHOLESALE"]');
            if (w && $u.length) { $u.text('وحدة الجملة (' + w + ')'); }
        }
        function relabelAll() {
            $('select[name$="-variant"]').each(function () { relabel(row($(this))); });
        }
        $(document).on('change', 'select[name$="-variant"]', function () { relabel(row($(this))); });
        $(document).on('formset:added', relabelAll);
        $(function () { relabelAll(); });
    });
})();
