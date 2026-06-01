# -*- coding: utf-8 -*-
"""Backfill ProductSizeRecipe.selling_price from existing SKU prices.

Phase E moves the per-size selling price onto the MAIN product's recipe. To keep
current prices intact during the switch, seed each recipe's selling_price from the
highest non-zero price found on its product's sub-product SKUs for that same size.
Recipes that already carry a price are left untouched. Fully reversible (no-op).
"""
from django.db import migrations


def backfill_recipe_prices(apps, schema_editor):
    ProductSizeRecipe = apps.get_model('manufacturing', 'ProductSizeRecipe')
    ItemVariant = apps.get_model('inventory', 'ItemVariant')
    for recipe in ProductSizeRecipe.objects.select_related('product', 'size').all():
        if recipe.selling_price and recipe.selling_price > 0:
            continue  # already priced — don't overwrite
        size_code = recipe.size.code
        prices = list(ItemVariant.objects
                      .filter(item__product_id=recipe.product_id, size=size_code,
                              selling_price__gt=0)
                      .values_list('selling_price', flat=True))
        if prices:
            recipe.selling_price = max(prices)
            recipe.save(update_fields=['selling_price'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('manufacturing', '0031_productsizerecipe_selling_price'),
        ('inventory', '0004_product_alter_item_options_alter_itemvariant_item_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_recipe_prices, noop_reverse),
    ]
