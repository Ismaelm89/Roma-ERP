"""Data migration:
  1. Seed 4 default VendorTypes (extensible — user can add more from admin).
  2. Copy every FabricSupplier → Supplier (vendor_type=مورد قماش).
  3. Copy every FabricDyer     → Supplier (vendor_type=مصبغة).
  4. Re-point FabricBatch.supplier_new, DyeOrder.dyer_new, SupplierPayment.supplier,
     and JournalLine.supplier to the new Supplier rows via an in-memory ID map.
"""
from django.db import migrations


DEFAULT_VENDOR_TYPES = [
    # (code, name_ar, sort_order)
    ('FABRIC_SUPPLIER', 'مورد قماش', 1),
    ('DYER',            'مصبغة',     2),
    ('ACCESSORIES',     'إكسسوارات', 3),
    ('MACHINERY',       'مكن',       4),
]


def forward(apps, schema_editor):
    VendorType    = apps.get_model('manufacturing', 'VendorType')
    Supplier      = apps.get_model('manufacturing', 'Supplier')
    FabricSupplier = apps.get_model('manufacturing', 'FabricSupplier')
    FabricDyer     = apps.get_model('manufacturing', 'FabricDyer')
    FabricBatch    = apps.get_model('manufacturing', 'FabricBatch')
    DyeOrder       = apps.get_model('manufacturing', 'DyeOrder')
    SupplierPayment = apps.get_model('manufacturing', 'SupplierPayment')
    JournalLine    = apps.get_model('core', 'JournalLine')

    # 1. Seed vendor types
    type_by_code = {}
    for code, name_ar, sort_order in DEFAULT_VENDOR_TYPES:
        vt, _ = VendorType.objects.get_or_create(
            code=code,
            defaults={'name_ar': name_ar, 'sort_order': sort_order, 'active': True},
        )
        type_by_code[code] = vt

    fabric_vt = type_by_code['FABRIC_SUPPLIER']
    dyer_vt   = type_by_code['DYER']

    # 2. Copy FabricSupplier → Supplier
    # Use a deterministic code: keep original FabricSupplier.code so the user
    # still recognises it. They can rename later.
    supplier_map = {}  # {old_fabric_supplier_id: new_supplier_id}
    for fs in FabricSupplier.objects.all().order_by('id'):
        new_sup = Supplier.objects.create(
            code=fs.code,
            name=fs.name,
            vendor_type=fabric_vt,
            phone=fs.phone,
            address=fs.address,
            tax_id=fs.tax_id,
            notes=fs.notes,
            active=fs.active,
        )
        supplier_map[fs.id] = new_sup.id

    # 3. Copy FabricDyer → Supplier
    dyer_map = {}  # {old_fabric_dyer_id: new_supplier_id}
    for fd in FabricDyer.objects.all().order_by('id'):
        new_sup = Supplier.objects.create(
            code=fd.code,
            name=fd.name,
            vendor_type=dyer_vt,
            phone=fd.phone,
            address=fd.address,
            notes=fd.notes,
            active=fd.active,
        )
        dyer_map[fd.id] = new_sup.id

    # 4. Re-point FabricBatch.supplier_new
    for batch in FabricBatch.objects.all():
        if batch.supplier_id and batch.supplier_id in supplier_map:
            batch.supplier_new_id = supplier_map[batch.supplier_id]
            batch.save(update_fields=['supplier_new'])

    # 5. Re-point DyeOrder.dyer_new
    for dye in DyeOrder.objects.all():
        if dye.dyer_id and dye.dyer_id in dyer_map:
            dye.dyer_new_id = dyer_map[dye.dyer_id]
            dye.save(update_fields=['dyer_new'])

    # 6. Re-point SupplierPayment.supplier
    for sp in SupplierPayment.objects.all():
        if sp.fabric_supplier_id and sp.fabric_supplier_id in supplier_map:
            sp.supplier_id = supplier_map[sp.fabric_supplier_id]
        elif sp.fabric_dyer_id and sp.fabric_dyer_id in dyer_map:
            sp.supplier_id = dyer_map[sp.fabric_dyer_id]
        if sp.supplier_id:
            sp.save(update_fields=['supplier'])

    # 7. Re-point JournalLine.supplier
    for jl in JournalLine.objects.filter(fabric_supplier__isnull=False):
        if jl.fabric_supplier_id in supplier_map:
            jl.supplier_id = supplier_map[jl.fabric_supplier_id]
            jl.save(update_fields=['supplier'])
    for jl in JournalLine.objects.filter(fabric_dyer__isnull=False):
        if jl.fabric_dyer_id in dyer_map:
            jl.supplier_id = dyer_map[jl.fabric_dyer_id]
            jl.save(update_fields=['supplier'])


def backward(apps, schema_editor):
    # Reverse: drop generated Suppliers/VendorTypes. We DON'T restore the legacy
    # FK columns — those still exist until the next migration drops them, so
    # the user can rollback safely.
    Supplier   = apps.get_model('manufacturing', 'Supplier')
    VendorType = apps.get_model('manufacturing', 'VendorType')
    Supplier.objects.all().delete()
    VendorType.objects.filter(code__in=[t[0] for t in DEFAULT_VENDOR_TYPES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('manufacturing', '0003_supplier_vendortype_alter_fabricbatch_options_and_more'),
        ('core', '0004_journalline_supplier_alter_journalline_fabric_dyer_and_more'),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
