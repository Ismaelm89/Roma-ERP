/* Roma ERP — swap the comma and the period on every input field.
 *
 *   Typing ","  inserts "."   and   typing "."  inserts ","   (a true swap),
 *   in every text box and textarea across the admin.
 *
 * Number inputs (prices, quantities) are converted to text inputs first so the
 * swap works there too; on form submit their value is normalised back to a
 * dot-decimal number (any "," → ".") so Django's numeric validation passes.
 * Either key therefore always produces a valid decimal point in a number field.
 */
(function () {
    'use strict';

    var NUMERIC_FLAG = 'data-roma-numeric';

    // Convert an <input type=number> into a text input we fully control.
    function convertNumberInput(el) {
        if (el.tagName !== 'INPUT') return;
        if (el.type !== 'number') return;
        el.setAttribute(NUMERIC_FLAG, '1');
        el.setAttribute('inputmode', 'decimal');
        el.type = 'text';
    }

    function convertAll(root) {
        var nodes = (root || document).querySelectorAll('input[type=number]');
        for (var i = 0; i < nodes.length; i++) convertNumberInput(nodes[i]);
    }

    // Which fields take part in the swap?
    function isSwappable(el) {
        if (!el) return false;
        if (el.tagName === 'TEXTAREA') return true;
        if (el.tagName !== 'INPUT') return false;
        var t = (el.getAttribute('type') || 'text').toLowerCase();
        var textTypes = ['text', 'search', 'tel', 'url', 'email', 'password', ''];
        return textTypes.indexOf(t) !== -1 || el.hasAttribute(NUMERIC_FLAG);
    }

    // Convert lazily on focus so dynamically added inline rows are covered too.
    document.addEventListener('focusin', function (e) {
        convertNumberInput(e.target);
    }, true);

    document.addEventListener('DOMContentLoaded', function () {
        convertAll(document);
    });

    // The actual swap.
    document.addEventListener('keydown', function (e) {
        if (e.ctrlKey || e.altKey || e.metaKey) return;
        if (e.key !== ',' && e.key !== '.') return;
        var el = e.target;
        // Make sure a freshly focused number input is already a text input.
        convertNumberInput(el);
        if (!isSwappable(el)) return;
        if (typeof el.selectionStart !== 'number') return;

        e.preventDefault();
        var swapped = (e.key === ',') ? '.' : ',';
        var start = el.selectionStart;
        var end = el.selectionEnd;
        var v = el.value;
        el.value = v.slice(0, start) + swapped + v.slice(end);
        var pos = start + 1;
        el.setSelectionRange(pos, pos);
        el.dispatchEvent(new Event('input', { bubbles: true }));
    }, true);

    // On submit, give Django a dot-decimal value for the numeric fields.
    document.addEventListener('submit', function (e) {
        var form = e.target;
        if (!form || !form.querySelectorAll) return;
        var nodes = form.querySelectorAll('input[' + NUMERIC_FLAG + ']');
        for (var i = 0; i < nodes.length; i++) {
            var el = nodes[i];
            if (el.value && el.value.indexOf(',') !== -1) {
                el.value = el.value.replace(/,/g, '.');
            }
        }
    }, true);
})();
