"""Custom admin sidebar grouping.

Django groups admin models by app. The business wants a different layout that
splits the manufacturing app into a PURCHASE section and a factory-management
section, with an explicit order inside each group. We override the default
site's get_app_list to build that layout. Any model not listed here (e.g. the
auth Users/Groups) is appended after the custom sections, untouched.
"""
from types import MethodType

from django.contrib import admin

# (section title, [(app_label, ModelClassName), ...]) — order matters everywhere.
SIDEBAR = [
    ('CORE', [
        ('core', 'Company'),
        ('core', 'Account'),
        ('core', 'JournalEntry'),
    ]),
    ('INVENTORY', [
        ('inventory', 'Product'),
        ('inventory', 'Item'),
        ('inventory', 'ItemVariant'),
        ('inventory', 'StockMovement'),
        ('inventory', 'StockTake'),
        ('manufacturing', 'FabricStockTake'),
        ('manufacturing', 'AccessoryStockTake'),
    ]),
    ('SALES', [
        ('sales', 'Customer'),
        ('sales', 'Receipt'),
        ('sales', 'SalesInvoice'),
        ('sales', 'SalesReturn'),
        ('manufacturing', 'UninvoicedProductionOrder'),
    ]),
    ('الخزينة والمصروفات', [
        ('core', 'CashAccount'),
        ('core', 'ExpenseVoucher'),
        ('core', 'ExpenseCategory'),
        ('core', 'FixedAsset'),
    ]),
    ('PURCHASE', [
        ('manufacturing', 'VendorType'),
        ('manufacturing', 'Supplier'),
        # فواتير الشراء حلّت محل المشتريات المفردة القديمة (FabricBatch/AccessoryPurchase)
        # وبقت في نفس مكانها تحت PURCHASE.
        ('manufacturing', 'FabricPurchaseInvoice'),
        ('manufacturing', 'AccessoryPurchaseInvoice'),
        ('inventory', 'FinishedGoodsPurchaseInvoice'),
        ('manufacturing', 'SupplierPayment'),
    ]),
    ('إدارة المصنع', [
        ('manufacturing', 'FabricColor'),
        ('manufacturing', 'FabricType'),
        ('manufacturing', 'ProductionOrder'),
        ('manufacturing', 'Accessory'),
        ('manufacturing', 'Size'),
        ('manufacturing', 'FabricMovement'),
        ('manufacturing', 'ProductionSubModel'),
        ('manufacturing', 'ManufacturingWagePayment'),
        ('manufacturing', 'ManufacturingWageAdjustment'),
        ('manufacturing', 'ProductSizeRecipe'),
    ]),
]

# روابط مخصّصة تحت أقسام معيّنة: {section_title: [(label, url), ...]}
EXTRA_LINKS = {}

_original_get_app_list = None


def _ordered_get_app_list(self, request, app_label=None):
    # App index pages (/admin/<app>/) need the default per-app behaviour.
    if app_label:
        return _original_get_app_list(request, app_label)

    app_dict = self._build_app_dict(request)
    index = {}
    for label, app in app_dict.items():
        for model in app['models']:
            index[(label, model['object_name'])] = model

    used = set()
    app_list = []
    for section_title, members in SIDEBAR:
        models = []
        for key in members:
            model = index.get(key)
            if model is not None:
                models.append(model)
                used.add(key)
        for label, url in EXTRA_LINKS.get(section_title, []):
            models.append({'name': label, 'object_name': label, 'perms': {'view': True},
                           'admin_url': url, 'add_url': None, 'view_only': True})
        if models:
            app_list.append({
                'name': section_title,
                'app_label': section_title,
                'app_url': '',
                'has_module_perms': True,
                'models': models,
            })

    # Anything not placed above (auth, etc.) keeps its own group, appended last.
    for label, app in app_dict.items():
        leftover = [m for m in app['models'] if (label, m['object_name']) not in used]
        if leftover:
            app_list.append({**app, 'models': leftover})

    return app_list


def install():
    """Swap in the custom get_app_list on the default admin site (idempotent)."""
    global _original_get_app_list
    if _original_get_app_list is None:
        _original_get_app_list = admin.site.get_app_list
    admin.site.get_app_list = MethodType(_ordered_get_app_list, admin.site)
