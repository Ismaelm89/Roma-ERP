# -*- coding: utf-8 -*-
"""Log into the running Roma ERP admin and capture screenshots of each screen
for the training guide. Saves PNGs into docs/images/.

Optional arg: a substring filter, e.g.  python _capture_screens.py ob-
captures only the screens whose name contains that substring (the login step
is always performed). With no arg, captures everything."""
import os
import sys
from playwright.sync_api import sync_playwright

FILTER = sys.argv[1] if len(sys.argv) > 1 else ""

BASE = "http://127.0.0.1:8001"
USER = "admin"
PWD = "roma2026"
OUTDIR = r"C:\Users\MahmoudIsmael\Desktop\Roma-ERP\docs\images"
os.makedirs(OUTDIR, exist_ok=True)

# (filename, path, full_page)
SHOTS = [
    ("00-login",            "/admin/login/?next=/admin/", False),
    ("01-dashboard",        "/admin/", True),
    ("02-kpi-dashboard",    "/", True),
    ("08-products-list",    "/admin/inventory/product/", True),
    ("09-product-add",      "/admin/inventory/product/add/", True),
    ("10-items-list",       "/admin/inventory/item/", True),
    ("11-item-add",         "/admin/inventory/item/add/", True),
    ("12-skus-list",        "/admin/inventory/itemvariant/", True),
    ("13-stockmoves",       "/admin/inventory/stockmovement/", True),
    ("20-customers-list",   "/admin/sales/customer/", True),
    ("21-customer-add",     "/admin/sales/customer/add/", True),
    ("22-invoices-list",    "/admin/sales/salesinvoice/", True),
    ("23-invoice-add",      "/admin/sales/salesinvoice/add/", True),
    ("24-receipt-add",      "/admin/sales/receipt/add/", True),
    ("25-return-add",       "/admin/sales/salesreturn/add/", True),
    # post-posting invoice + print sheets (one consistent example)
    ("26-invoice-posted",   "/admin/sales/salesinvoice/4/change/", True),
    ("27-invoice-print",    "/sales/invoice/4/print/", True),
    # treasury / expenses / fixed assets (new screens)
    ("28-cashaccounts",     "/admin/core/cashaccount/", True),
    ("29-expense-add",      "/admin/core/expensevoucher/add/", True),
    ("2a-fixedasset-add",   "/admin/core/fixedasset/add/", True),
    ("30-vendortype-add",   "/admin/manufacturing/vendortype/add/", True),
    ("31-suppliers-list",   "/admin/manufacturing/supplier/", True),
    ("32-fabricbatch-add",  "/admin/manufacturing/fabricbatch/add/", True),
    ("33-supplierpay-add",  "/admin/manufacturing/supplierpayment/add/", True),
    ("34-accessorypur-add", "/admin/manufacturing/accessorypurchase/add/", True),
    ("40-fabriccolor-add",  "/admin/manufacturing/fabriccolor/add/", True),
    ("41-fabrictype-add",   "/admin/manufacturing/fabrictype/add/", True),
    ("42-prodorder-add",    "/admin/manufacturing/productionorder/add/", True),
    ("47-prodorder-print",  "/manufacturing/production/43/print/", True),
    ("43-accessory-add",    "/admin/manufacturing/accessory/add/", True),
    ("44-size-add",         "/admin/manufacturing/size/add/", True),
    ("45-fabricmoves",      "/admin/manufacturing/fabricmovement/", True),
    ("46-submodels-list",   "/admin/manufacturing/productionsubmodel/", True),
    # opening balances screens (training guide for the one-time setup)
    ("ob-09-dashboard",     "/", True),
    ("ob-00-hub",           "/opening/", True),
    ("ob-01-customers",     "/opening/customers/", True),
    ("ob-02-suppliers",     "/opening/suppliers/", True),
    ("ob-03-inventory",     "/opening/inventory/", True),
    ("ob-04-fabric",        "/opening/fabric/", True),
    ("ob-05-assets",        "/opening/assets/", True),
    ("ob-06-cash",          "/opening/cash/", True),
    ("ob-07-finalize",      "/opening/finalize/", True),
]

# --- authenticate without a password by minting a Django session for the
#     local superuser and injecting its cookie into the browser. This is robust
#     to the admin username/password changing on the dev box. ---
import django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()
from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.auth import (
    get_user_model, SESSION_KEY, BACKEND_SESSION_KEY, HASH_SESSION_KEY,
)

_user = get_user_model().objects.filter(is_superuser=True).order_by("id").first()
if _user is None:
    raise SystemExit("No superuser found to capture screenshots with.")
_s = SessionStore()
_s[SESSION_KEY] = str(_user.pk)
_s[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"
_s[HASH_SESSION_KEY] = _user.get_session_auth_hash()
_s.create()
SESSION_COOKIE = _s.session_key

results = []
with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1280, "height": 900},
                              device_scale_factor=2, locale="ar-EG")

    # capture the empty login form (unauthenticated) before injecting the cookie
    if not FILTER or FILTER in "00-login":
        lp = ctx.new_page()
        lp.goto(BASE + "/admin/login/?next=/admin/", wait_until="networkidle")
        lp.screenshot(path=os.path.join(OUTDIR, "00-login.png"))
        results.append("00-login")
        lp.close()

    # authenticate by injecting the session cookie
    ctx.add_cookies([{
        "name": settings.SESSION_COOKIE_NAME,
        "value": SESSION_COOKIE,
        "domain": "127.0.0.1",
        "path": "/",
    }])
    page = ctx.new_page()

    for name, path, full in SHOTS:
        if name == "00-login":
            continue
        if FILTER and FILTER not in name:
            continue
        try:
            page.goto(BASE + path, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(400)
            page.screenshot(path=os.path.join(OUTDIR, name + ".png"),
                            full_page=full)
            results.append(name)
        except Exception as e:
            results.append(name + " FAILED: " + str(e)[:120])

    browser.close()

print("CAPTURED:")
for r in results:
    print(" -", r)
