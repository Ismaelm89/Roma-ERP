r"""End-to-end smoke test for Phase 2a — production orders.

Scenario:
  1. Reuse smoke fabric supplier + batch from fabric_smoke_test (run that first).
  2. Create a small production order with:
       - 2 sub-models (each with chest/back/sleeve/shorts cut data)
       - 6 size rows (sub_model 1: S/M/L, sub_model 2: M/L/XL)
       - 1 fabric usage = 20 kg from the smoke batch
  3. Release.
  4. Assert:
       - Smoke batch.in_stock dropped by 20 kg
       - Order status = RELEASED
       - JE posted DR WIP / CR Fabric Inventory = 20 × cost_per_kg
       - ISSUE_TO_PRODUCTION FabricMovement created
  5. Cancel.
  6. Assert: kg restored, status=CANCELLED, reverse JE posted.
"""
import os, django
from decimal import Decimal
from datetime import date

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.db.models import ProtectedError

from core.models import JournalEntry, JournalLine
from core.account_codes import SYSTEM_ACCOUNTS
from manufacturing.models import (
    VendorType, Supplier, FabricType, FabricColor,
    FabricBatch, FabricMovement,
    ProductionOrder, ProductionSubModel, ProductionSize, FabricUsage,
    Accessory, AccessoryUsage, Size,
)
from manufacturing.services import (
    post_fabric_purchase,
    release_production_order, cancel_production_order, complete_production_order,
)


def section(s):
    print(f'\n== {s}')


# ---------------- cleanup
section('cleanup')
for ref_pref in ('PO-SMOKE', 'إلغاء PO-SMOKE'):
    JournalEntry.objects.filter(reference__startswith=ref_pref).delete()
JournalEntry.objects.filter(reference__contains='PO-SMOKE').delete()
ProductionOrder.objects.filter(order_no__startswith='PO-SMOKE').delete()
FabricMovement.objects.filter(notes__contains='PO-SMOKE').delete()
JournalEntry.objects.filter(reference='FB-PSMOKE-1').delete()
FabricMovement.objects.filter(batch__batch_no='FB-PSMOKE-1').delete()
# Also wipe any FabricUsage still pointing at this batch (from user-created POs)
FabricUsage.objects.filter(batch__batch_no='FB-PSMOKE-1').delete()
try:
    FabricBatch.objects.filter(batch_no='FB-PSMOKE-1').delete()
except ProtectedError:
    print('  skip FB-PSMOKE-1 delete (still referenced)')
# Accessory used in this test
AccessoryUsage.objects.filter(notes__icontains='SMOKE').delete()
AccessoryUsage.objects.filter(accessory__code__startswith='ACC-SMOKE').delete()
try:
    Accessory.objects.filter(code__startswith='ACC-SMOKE').delete()
except ProtectedError:
    print('  skip Accessory delete (still referenced — fine)')
# Test items + variants from completion (best-effort — skip if user reused)
from inventory.models import Item, StockMovement
from django.db.models import ProtectedError
try:
    Item.objects.filter(name_ar='بيجاما اختبار صيفي 2026').delete()
except ProtectedError:
    print('  skip Item delete (still referenced — fine)')
print('  ok')


User = get_user_model()
admin = User.objects.get(username='admin')

# ---------------- masters (idempotent)
section('masters')
vt_fabric = VendorType.objects.get(code='FABRIC_SUPPLIER')
sup, _ = Supplier.objects.get_or_create(
    code='SUP-F-PSMOKE',
    defaults={'name': 'مورد إنتاج اختبار', 'vendor_type': vt_fabric},
)
ft, _ = FabricType.objects.get_or_create(
    code='FT-PSMOKE', defaults={'name_ar': 'تريكو إنتاج (اختبار)'},
)
raw, _ = FabricColor.objects.get_or_create(
    code='FC-PSMOKE-R', defaults={'name_ar': 'خام إنتاج (اختبار)', 'is_raw': True},
)
print(f'  {sup}, {ft}, {raw}')


# ---------------- fabric batch (so we have something to consume)
section('fabric batch — 100 kg @ 50 EGP/kg')
batch = FabricBatch.objects.create(
    batch_no='FB-PSMOKE-1',
    supplier=sup, fabric_type=ft, color=raw,
    purchase_date=date.today(),
    purchase_qty_kg=Decimal('100.000'),
    purchase_unit_cost=Decimal('50.0000'),
    purchase_payment_method='CREDIT',
    created_by=admin,
)
post_fabric_purchase(batch, user=admin)
batch.refresh_from_db()
print(f'  {batch} cost_per_kg={batch.cost_per_kg}, in_stock={batch.in_stock_qty_kg}kg')
assert batch.cost_per_kg == Decimal('50.0000')
assert batch.in_stock_qty_kg == Decimal('100.000')


# ---------------- production order
section('production order')
order = ProductionOrder.objects.create(
    order_no='PO-SMOKE-1', date=date.today(),
    title='بيجاما اختبار صيفي 2026',
    created_by=admin,
)
print(f'  {order}')

# Sub-models — sub_model_no auto-assigned
subs = []
for chest, back in [('أبيض', 'أحمر'), ('أزرق', 'أصفر')]:
    sm = ProductionSubModel.objects.create(
        order=order,
        fabric_description='تريكو قطني',
        chest_type='سادة', chest_color=chest,
        back_type='سادة', back_color=back,
        sleeve_type='سادة', sleeve_color=chest,
        shorts_pattern='كابلس', shorts_type='سادة', shorts_color=chest,
    )
    subs.append(sm)
sub_nos = [s.sub_model_no for s in subs]
assert sub_nos == [1, 2], f'unexpected sub_model_no list: {sub_nos}'
print(f'  sub_model_no auto-assigned: {sub_nos}')

# Sizes (6 rows): sub_model 1 × S/M/L, sub_model 2 × M/L/XL
size_S = Size.objects.get(code='S')
size_M = Size.objects.get(code='M')
size_L = Size.objects.get(code='L')
size_XL = Size.objects.get(code='XL')
size_data = [
    (subs[0], size_S, 5), (subs[0], size_M, 10), (subs[0], size_L, 7),
    (subs[1], size_M, 12), (subs[1], size_L, 8), (subs[1], size_XL, 4),
]
for sub, sz, qty in size_data:
    ProductionSize.objects.create(order=order, sub_model=sub, size=sz, quantity=qty)

# Fabric usage: 20 kg planned (no stage FK anymore — directly under the PO)
fu = FabricUsage.objects.create(order=order, batch=batch,
                                  planned_qty_kg=Decimal('20.000'), notes='تجربة')
print(f'  fabric usage created: {fu.planned_qty_kg} kg from {fu.batch.batch_no}')

# Accessory usage: 50 buttons @ 0.50 each = 25 EGP
acc, _ = Accessory.objects.get_or_create(
    code='ACC-SMOKE1',
    defaults={'name_ar': 'زرار اختبار', 'unit': 'قطعة',
              'default_unit_cost': Decimal('0.5000')},
)
# Accessory usage: just accessory + actual_qty (cost + supplier come from Accessory)
AccessoryUsage.objects.create(order=order, accessory=acc,
                                actual_qty=Decimal('50'),
                                notes='SMOKE')

order.refresh_from_db()
print(f'  total_pieces = {order.total_pieces} (expected 46)')
print(f'  total_planned_fabric_kg = {order.total_planned_fabric_kg}')
print(f'  item auto-created: {order.item} (code={order.item.code})')
assert order.total_pieces == 46
assert order.total_planned_fabric_kg == Decimal('20.000')
assert order.item is not None
assert order.item.name_ar == order.title


# ---------------- release
# Expected: fabric 1000 (20×50) + accessory 25 (50×0.5) = 1025 total WIP debit
section('release')
je = release_production_order(order, user=admin)
order.refresh_from_db()
batch.refresh_from_db()
print(f'  status={order.status}, je={je.id}, D={je.total_debit} C={je.total_credit}')
print(f'  batch.in_stock = {batch.in_stock_qty_kg} (expected 80.000)')

assert order.status == 'RELEASED'
# At release: only fabric is posted (1000). Accessories post at completion now.
assert je.total_debit == je.total_credit == Decimal('1000.00'), \
    f'expected 1000 at release (no accessories yet), got {je.total_debit}'
assert batch.in_stock_qty_kg == Decimal('80.000')

# Verify the JE lines
wip_code = SYSTEM_ACCOUNTS['WIP']
fab_code = SYSTEM_ACCOUNTS['FABRIC_INVENTORY']
cash_code = SYSTEM_ACCOUNTS['CASH']
dr_wip = JournalLine.objects.filter(entry=je, account__code=wip_code).aggregate(s=Sum('debit'))['s']
cr_fab = JournalLine.objects.filter(entry=je, account__code=fab_code).aggregate(s=Sum('credit'))['s']
print(f'  DR WIP = {dr_wip}  /  CR Fabric = {cr_fab}')
assert dr_wip == Decimal('1000.00')
assert cr_fab == Decimal('1000.00')

# Movement
mv = FabricMovement.objects.filter(
    batch=batch, movement_type='ISSUE_TO_PRODUCTION',
    document_type='ProductionOrder', document_id=order.id,
).first()
assert mv is not None and mv.quantity_kg == Decimal('20.000')


# ---------------- complete (final closing)
# No actual_quantity step anymore — quantity is the single source of truth.
section('complete (final closing)')
order.refresh_from_db()
print(f'  total_pieces = {order.total_pieces}')
print(f'  total_cost = {order.total_cost} (1000 fabric + 25 accessories)')
print(f'  cost_per_piece = {order.cost_per_piece} (1025 / 46)')

je_complete = complete_production_order(order, user=admin)
order.refresh_from_db()
print(f'  status={order.status}, je={je_complete.id}, D={je_complete.total_debit} C={je_complete.total_credit}')
assert order.status == 'COMPLETED'
# Completion JE = accessory_cost (DR WIP/CR Cash = 25)
#               + transfer (DR Inv 1025 / CR WIP 1025)
# Total D = 25 + 1025 = 1050
assert je_complete.total_debit == je_complete.total_credit == Decimal('1050.00')

# Verify finished-goods inventory got the pieces
from inventory.models import ItemVariant
variants = ItemVariant.objects.filter(item=order.item)
print(f'  ItemVariants created: {variants.count()}')
total_in_stock = sum(v.current_stock for v in variants)
print(f'  total pieces in inventory = {total_in_stock} (expected 46)')
assert total_in_stock == 46

# WIP should now be zero for this order's JEs (release + complete cancel out)
po_jes = JournalEntry.objects.filter(source_doc_type='ProductionOrder', source_doc_id=order.id)
wip_balance = (JournalLine.objects.filter(entry__in=po_jes, account__code=wip_code)
                .aggregate(d=Sum('debit'), c=Sum('credit')))
wip_net = (wip_balance['d'] or 0) - (wip_balance['c'] or 0)
print(f'  WIP net for this order: {wip_net} (expected 0 — release adds, complete removes)')
assert wip_net == 0


print('\nALL PRODUCTION SMOKE CHECKS PASSED (Phase 2c/d).')
