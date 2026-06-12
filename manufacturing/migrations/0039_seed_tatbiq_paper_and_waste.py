# Data migration — تعديلات يونيو 2026 (بتتطبّق تلقائياً محلياً وعلى السيرفر):
#   1) إضافة إكسسوار «ورقة تطبيق» بسعر 1 جنيه (لو مش موجود).
#   2) ربطه بكل وصفات مقاسات المنتجات PRD-0002..0005 و0008..0010 بمعدل قطعة/قطعة.
#   3) نسبة هالك القماش (على المنتج) = 5% لكل المنتجات.
#   (نسبة هالك الإكسسوارات 5% اتظبطت بالـ default في 0038_accessory_waste_pct.)
import re
from decimal import Decimal

from django.db import migrations

TARGET_PRODUCTS = ['PRD-0002', 'PRD-0003', 'PRD-0004', 'PRD-0005',
                   'PRD-0008', 'PRD-0009', 'PRD-0010']
ACC_NAME = 'ورقة تطبيق'


def _next_acc_code(Accessory):
    pat = re.compile(r'^ACC-(\d+)$')
    max_n = 0
    for code in Accessory.objects.values_list('code', flat=True):
        m = pat.match(str(code or ''))
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f'ACC-{str(max_n + 1).zfill(4)}'


def forwards(apps, schema_editor):
    Accessory = apps.get_model('manufacturing', 'Accessory')
    Recipe = apps.get_model('manufacturing', 'ProductSizeRecipe')
    RecipeAcc = apps.get_model('manufacturing', 'ProductSizeAccessory')
    Product = apps.get_model('inventory', 'Product')

    # 1) إكسسوار «ورقة تطبيق» — سعر استرشادي 1 جنيه، بالقطعة، هالك 5%.
    acc = Accessory.objects.filter(name_ar=ACC_NAME).first()
    if acc is None:
        acc = Accessory.objects.create(
            code=_next_acc_code(Accessory), name_ar=ACC_NAME, unit='قطعة',
            default_unit_cost=Decimal('1'), waste_pct=Decimal('5'), active=True,
        )

    # 2) قطعة واحدة لكل قطعة في كل وصفات مقاسات المنتجات المستهدفة (idempotent).
    for recipe in Recipe.objects.filter(product__code__in=TARGET_PRODUCTS):
        RecipeAcc.objects.get_or_create(
            recipe=recipe, accessory=acc,
            defaults={'qty_per_piece': Decimal('1')},
        )

    # 3) هالك القماش 5% على كل المنتجات.
    Product.objects.update(waste_pct=Decimal('5'))


class Migration(migrations.Migration):

    dependencies = [
        ('manufacturing', '0038_accessory_waste_pct'),
        ('inventory', '0007_item_fabric_color'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
