/* Roma ERP — معاينة فورية لصورة المنتج الفرعي قبل الحفظ.
 * أول ما تختار ملف صورة من خانة «الصورة»، بتظهر في خانة «معاينة» على طول
 * (من غير ما تحفظ) عشان تتأكد إنها الصورة الصح. */
(function () {
    'use strict';
    function init() {
        var input = document.getElementById('id_image');
        if (!input) return;
        input.addEventListener('change', function () {
            var file = input.files && input.files[0];
            var box = document.querySelector('.field-image_preview .readonly')
                   || document.querySelector('.field-image_preview div div')
                   || document.querySelector('.field-image_preview');
            if (!box) return;
            if (!file) return;
            if (!/^image\//.test(file.type)) {
                box.innerHTML = '<span style="color:#b91c1c;">الملف ده مش صورة.</span>';
                return;
            }
            var reader = new FileReader();
            reader.onload = function (e) {
                box.innerHTML =
                    '<img src="' + e.target.result + '" style="max-width:200px;max-height:200px;'
                    + 'border:1px solid #ddd;border-radius:6px;display:block;">'
                    + '<div style="color:#0a7a3f;font-size:12px;margin-top:4px;">'
                    + 'معاينة قبل الحفظ — اضغط «احفظ» عشان الصورة تتخزن.</div>';
            };
            reader.readAsDataURL(file);
        });
    }
    if (document.readyState !== 'loading') init();
    else document.addEventListener('DOMContentLoaded', init);
})();
