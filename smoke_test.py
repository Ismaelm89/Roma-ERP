r"""Manual end-to-end smoke test — run with:
    .\.venv\Scripts\python.exe smoke_test.py

Creates test data, exercises posting logic, prints results. Idempotent-ish
(cleans up its own rows on each run).
"""
import os, sys, time, django
from decimal import Decimal
from datetime import date

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

# Unique suffix so each run uses fresh codes — avoids clashing with real data.
SFX = str(int(time.time()))[-6:]

from django.contrib.auth import get_user_model
from django.test import Client

from core.models import Account, JournalEntry, JournalLine, Company
from core.account_codes import SYSTEM_ACCOUNTS
from inventory.models import Item, ItemVariant, StockMovement
from inventory.services import post_opening_balance
from sales.models import Customer, SalesInvoice, SalesInvoiceLine, Receipt, ReceiptAllocation
from sales.services import post_sales_invoice, post_receipt


def section(s):
    print(f'\n== {s}')


# No cleanup needed — every run uses a unique SFX suffix for all codes.
section('cleanup')
print(f'  using unique suffix: {SFX}')

# ---------------- ensure company exists
section('company')
co, _ = Company.objects.get_or_create(
    pk=1, defaults=dict(name_ar='روما للملابس', name_en='Roma',
                          tax_id='100-200-300', address='القاهرة، مصر',
                          phone='+20 100 000 0000', default_vat_rate=Decimal('14.00')),
)
print(f'  {co.name_ar}')

User = get_user_model()
admin = User.objects.get(username='admin')

# ---------------- item + variant + opening stock
section('item + variants')
item = Item.objects.create(
    code=f'SMK-{SFX}', name_ar='بيجاما تجريبية', name_en='Smoke Pajama',
    category='pajama set',
)
v_m = ItemVariant.objects.create(item=item, size='M', selling_price=Decimal('250.00'))
v_l = ItemVariant.objects.create(item=item, size='L', selling_price=Decimal('250.00'))
print(f'  {v_m.sku_code}, {v_l.sku_code}')

section('opening stock')
# Pieces-level opening (dozen_size defaults to 12).
for variant, qty, cost in [(v_m, 1200, Decimal('120.0000')),
                            (v_l, 600,  Decimal('125.0000'))]:
    post_opening_balance(variant=variant, quantity=qty, unit_cost=cost,
                          date=date.today(), user=admin, notes='SMOKE-OPENING')
v_m.refresh_from_db(); v_l.refresh_from_db()
print(f'  {v_m.sku_code}: stock={v_m.current_stock}, WAC={v_m.average_cost}')
print(f'  {v_l.sku_code}: stock={v_l.current_stock}, WAC={v_l.average_cost}')

# ---------------- customer
section('customer')
cust = Customer.objects.create(
    code=f'SMK{SFX}', name_ar='عميل اختبار', name_en='Smoke Customer',
    governorate='القاهرة', payment_terms_days=30,
    credit_limit=Decimal('100000'),
)
print(f'  {cust}')

# ---------------- invoice (draft)
section('invoice')
inv = SalesInvoice.objects.create(
    invoice_no=f'SMK-INV-{SFX}', date=date.today(), customer=cust,
    notes='smoke test invoice', created_by=admin,
)
# Dozen sale: 2 dozens of M (= 24 pcs) + 1 dozen of L (= 12 pcs). dozen_size=12.
SalesInvoiceLine.objects.create(invoice=inv, variant=v_m,
                                  quantity=Decimal('2'),
                                  unit_price=Decimal('3000.00'))  # سعر الدستة
SalesInvoiceLine.objects.create(invoice=inv, variant=v_l,
                                  quantity=Decimal('1'),
                                  unit_price=Decimal('3120.00'))

# ---------------- post invoice
section('post invoice')
je = post_sales_invoice(inv, user=admin)
inv.refresh_from_db()
v_m.refresh_from_db(); v_l.refresh_from_db()
print(f'  invoice status: {inv.status}, grand_total={inv.grand_total}')
print(f'  journal id={je.id}, total_debit={je.total_debit}, total_credit={je.total_credit}')
print(f'  v_m stock after: {v_m.current_stock} (was 1200, sold 2 dz=24, expect 1176)')
print(f'  v_l stock after: {v_l.current_stock} (was 600, sold 1 dz=12, expect 588)')
assert je.total_debit == je.total_credit, 'JOURNAL UNBALANCED'
assert v_m.current_stock == Decimal('1176.00'), f'unexpected v_m stock {v_m.current_stock}'
assert v_l.current_stock == Decimal('588.00'), f'unexpected v_l stock {v_l.current_stock}'

# ---------------- receipt — partial
section('receipt')
r = Receipt.objects.create(
    receipt_no=f'SMK-R-{SFX}', date=date.today(), customer=cust,
    method='CASH', amount=Decimal('1500.00'), created_by=admin,
)
ReceiptAllocation.objects.create(receipt=r, invoice=inv, amount=Decimal('1500.00'))
post_receipt(r, user=admin)
r.refresh_from_db()
inv.refresh_from_db()
print(f'  receipt status: {r.status}, paid_amount={inv.paid_amount}, balance_due={inv.balance_due}')

# ---------------- HTTP smoke
section('http')
c = Client(); c.force_login(admin)
for url in ['/admin/',
            '/sales/aging/',
            f'/sales/customer/{cust.pk}/ledger/',
            f'/sales/invoice/{inv.pk}/print/']:
    r = c.get(url)
    print(f'  {r.status_code}  {url}')

# ---------------- AR sub-ledger reconciliation
section('AR reconciliation')
ar_code = SYSTEM_ACCOUNTS['AR']
from django.db.models import Sum

# 1. This customer's AR ledger should equal this invoice's balance_due
cust_ar = JournalLine.objects.filter(
    customer=cust, account__code=ar_code, entry__status='POSTED'
).aggregate(d=Sum('debit'), c=Sum('credit'))
cust_balance = (cust_ar['d'] or Decimal('0')) - (cust_ar['c'] or Decimal('0'))
print(f'  SMOKE001 AR ledger:  {cust_balance}  (expected: {inv.balance_due})')
assert cust_balance == inv.balance_due, 'SMOKE001 AR ledger != balance_due'

# 2. Spec §11 reconciliation: AR sub-ledger total (sum of every customer's
#    AR) must equal the AR GL account balance (sum across all journal lines
#    on the AR account regardless of customer tag).
all_ar = JournalLine.objects.filter(account__code=ar_code, entry__status='POSTED')
gl_ar = (all_ar.aggregate(d=Sum('debit'))['d'] or Decimal('0')) - \
        (all_ar.aggregate(c=Sum('credit'))['c'] or Decimal('0'))
sub_ar = (all_ar.filter(customer__isnull=False).aggregate(d=Sum('debit'))['d'] or Decimal('0')) - \
         (all_ar.filter(customer__isnull=False).aggregate(c=Sum('credit'))['c'] or Decimal('0'))
print(f'  AR GL account:       {gl_ar}')
print(f'  AR sub-ledger total: {sub_ar}')
assert gl_ar == sub_ar, 'AR sub-ledger total != AR GL balance'

# 3. Inventory check — scoped to THIS run's smoke item only (global comparison
#    is meaningless once real user data + prior runs accumulate).
#    Opening: 1200×120 + 600×125 = 219,000. Sold 24 M-pcs + 12 L-pcs at WAC.
#    Remaining physical value should equal opening − COGS of this item.
v_m.refresh_from_db(); v_l.refresh_from_db()
item_phys = (Decimal(v_m.current_stock) * Decimal(v_m.average_cost)
             + Decimal(v_l.current_stock) * Decimal(v_l.average_cost)).quantize(Decimal('0.01'))
opening_val = (Decimal('1200') * Decimal('120') + Decimal('600') * Decimal('125'))
expected_remaining = (opening_val - total_cogs_check).quantize(Decimal('0.01')) \
    if (total_cogs_check := (Decimal('24') * Decimal('120') + Decimal('12') * Decimal('125'))) else opening_val
print(f'  smoke item physical value:  {item_phys}')
print(f'  expected (opening − COGS):   {expected_remaining}')
assert item_phys == expected_remaining, f'smoke item inventory mismatch: {item_phys} != {expected_remaining}'

print('\nALL CHECKS PASSED.')
