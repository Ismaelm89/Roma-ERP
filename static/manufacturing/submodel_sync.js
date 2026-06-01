/* Roma ERP — reuse "ملاحظات المنتج" across size lines in the SAME order.
 *
 * Django's +/✏️ popup only adds the new note to the dropdown that opened it.
 * This script mirrors every note option onto ALL the size-line dropdowns
 * (select[name$="-sub_model"]) on the production-order form, so a note typed
 * on one line can be picked on any other line — before saving the order.
 *
 * It also scopes the choices to the CURRENT order only: on load, any note
 * option that isn't actually selected on a saved row of this order is removed
 * (those are leftover notes from other/abandoned orders). A brand-new order
 * therefore starts with NO note choices; options appear only as you create
 * them inside the order you have open.
 */
(function () {
    'use strict';

    function waitForJQ(cb, attempts) {
        attempts = attempts || 0;
        var $ = (window.django && window.django.jQuery) || window.jQuery;
        if ($) { cb($); return; }
        if (attempts > 50) return;
        setTimeout(function () { waitForJQ(cb, attempts + 1); }, 100);
    }

    waitForJQ(function ($) {
        var SELECTOR = 'select[name$="-sub_model"]';

        // Strip out notes that don't belong to THIS order: keep only the ones
        // currently selected on a row (saved members of this order). Everything
        // else rendered by the server (orphan notes from other orders) is removed.
        function pruneForeignNotes() {
            var keep = {};
            $(SELECTOR).each(function () {
                var v = this.value;
                if (v) keep[v] = true;
            });
            $(SELECTOR).find('option').each(function () {
                if (this.value && !keep[this.value]) {
                    $(this).remove();
                }
            });
        }

        // Build a map { value: label } of every note still present on any row.
        function collectOptions() {
            var map = {};
            $(SELECTOR).find('option').each(function () {
                if (this.value) map[this.value] = $(this).text();
            });
            return map;
        }

        // Make sure every row's dropdown offers every known note,
        // without disturbing each row's own current selection.
        function syncAll() {
            var map = collectOptions();
            $(SELECTOR).each(function () {
                var $sel = $(this);
                var current = $sel.val();
                Object.keys(map).forEach(function (val) {
                    if ($sel.find('option[value="' + val + '"]').length === 0) {
                        $sel.append($('<option></option>').val(val).text(map[val]));
                    }
                });
                $sel.val(current);
            });
        }

        // A note created via popup (or any manual change) fires 'change';
        // propagate it to the other rows immediately.
        $(document).on('change', SELECTOR, syncAll);

        // New inline row added — give it all the notes already created.
        $(document).on('formset:added', syncAll);

        // Initial load: drop foreign notes first, then share this order's own.
        $(function () {
            pruneForeignNotes();
            syncAll();
        });
    });
})();
