# -*- coding: utf-8 -*-
"""Keep sub-products (Item) in sync with their MAIN product's recipe.

The main product (inventory.Product) is the single source of truth for sizes,
per-size selling price and dozen size. When its size recipe changes — a size is
added/removed via the inline, or a price/labor row is edited — we refresh every
sub-product's SKUs + prices so the cache never drifts.

Connected in InventoryConfig.ready().
"""


def recipe_changed(sender, instance, **kwargs):
    """A ProductSizeRecipe row was saved or deleted → re-sync its product's
    sub-products. Imported lazily to avoid import-time model cycles."""
    from .models import sync_variants_from_recipe
    product_id = getattr(instance, 'product_id', None)
    if not product_id:
        return
    product = instance.product
    for item in product.sub_products.all():
        sync_variants_from_recipe(item)
