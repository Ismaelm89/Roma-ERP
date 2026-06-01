from django.apps import AppConfig


class InventoryConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'inventory'

    def ready(self):
        # Re-sync sub-products whenever a main product's size recipe changes.
        from django.db.models.signals import post_save, post_delete
        from manufacturing.models import ProductSizeRecipe
        from . import signals
        post_save.connect(signals.recipe_changed, sender=ProductSizeRecipe,
                          dispatch_uid='inventory_recipe_changed_save')
        post_delete.connect(signals.recipe_changed, sender=ProductSizeRecipe,
                            dispatch_uid='inventory_recipe_changed_delete')
