/* ترقيم تلقائي لعمود «رقم المرحلة» في جدول مراحل التشغيل على أمر الإنتاج.
   - الصفوف بتترقّم 1..N بالترتيب على طول (والمستخدم مش بيكتب الرقم بإيده).
   - أي صف جديد بزر «أضف صف تشغيل آخر» بياخد الرقم التالي فوراً.
   - الخانة ضيّقة وفي النص عشان تبقى على قد الرقم. */
(function () {
    'use strict';

    function renumber() {
        var rows = document.querySelectorAll(
            '#operation_rows-group tr.form-row:not(.empty-form)');
        var n = 0;
        rows.forEach(function (tr) {
            var inp = tr.querySelector('input[name$="-stage_no"]');
            if (!inp) return;
            n += 1;
            inp.value = n;
            inp.readOnly = true;          // الرقم بيتحسب تلقائياً — مش بيتكتب باليد
            inp.tabIndex = -1;            // الـ Tab يعدّي عليه من غير وقفة
            inp.style.width = '46px';
            inp.style.minWidth = '46px';
            inp.style.textAlign = 'center';
            inp.style.background = '#f3f4f6';
        });
    }

    if (document.readyState !== 'loading') renumber();
    else document.addEventListener('DOMContentLoaded', renumber);

    // أي إضافة/حذف صف في أي inline → نعيد الترقيم (رخيصة فمفيش داعي للفلترة).
    document.addEventListener('formset:added', renumber);
    document.addEventListener('formset:removed', renumber);
})();
