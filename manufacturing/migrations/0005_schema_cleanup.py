"""Schema cleanup after data migration:
  - Drop legacy FabricSupplier / FabricDyer FKs from FabricBatch, DyeOrder, SupplierPayment.
  - Rename `supplier_new` → `supplier` on FabricBatch.
  - Rename `dyer_new` → `dyer` on DyeOrder.
  - Make the new FKs non-null.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('manufacturing', '0004_migrate_vendors_to_supplier'),
    ]

    operations = [
        # 1. Drop legacy FK to FabricSupplier on FabricBatch
        migrations.RemoveField(model_name='fabricbatch', name='supplier'),
        # 2. Rename supplier_new → supplier
        migrations.RenameField(model_name='fabricbatch', old_name='supplier_new', new_name='supplier'),
        # 3. Make non-null + filtered choices
        migrations.AlterField(
            model_name='fabricbatch',
            name='supplier',
            field=models.ForeignKey(
                help_text='اختار مورد من نوع "مورد قماش"',
                limit_choices_to={'vendor_type__code': 'FABRIC_SUPPLIER'},
                on_delete=django.db.models.deletion.PROTECT,
                related_name='fabric_batches',
                to='manufacturing.supplier',
                verbose_name='المورد',
            ),
        ),

        # 4. DyeOrder: drop legacy FK, rename, make non-null
        migrations.RemoveField(model_name='dyeorder', name='dyer'),
        migrations.RenameField(model_name='dyeorder', old_name='dyer_new', new_name='dyer'),
        migrations.AlterField(
            model_name='dyeorder',
            name='dyer',
            field=models.ForeignKey(
                help_text='اختار مورد من نوع "مصبغة"',
                limit_choices_to={'vendor_type__code': 'DYER'},
                on_delete=django.db.models.deletion.PROTECT,
                related_name='dye_orders',
                to='manufacturing.supplier',
                verbose_name='المصبغة',
            ),
        ),

        # 5. SupplierPayment: drop both legacy FKs, make `supplier` non-null
        migrations.RemoveField(model_name='supplierpayment', name='fabric_supplier'),
        migrations.RemoveField(model_name='supplierpayment', name='fabric_dyer'),
        migrations.AlterField(
            model_name='supplierpayment',
            name='supplier',
            field=models.ForeignKey(
                help_text='اختار المورد اللي بتدفعله (من أي نوع)',
                on_delete=django.db.models.deletion.PROTECT,
                related_name='payments',
                to='manufacturing.supplier',
                verbose_name='المورد',
            ),
        ),
    ]
