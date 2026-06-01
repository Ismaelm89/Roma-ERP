"""Phase 2b changes:
  - ProductionOrder: add item FK (auto-create on save if blank)
  - ProductionSubModel: sub_model_no becomes blank=True (auto-assigned)
  - ProductionSize: rename quantity → planned_quantity, add actual_quantity (default 0)
  - FabricUsage:   rename quantity_kg → planned_qty_kg, add actual_qty_kg (default 0)

Safe because the test PO data was wiped just before this migration.
"""
import django.db.models.deletion
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0001_initial'),
        ('manufacturing', '0007_productionorder_fabricusage_productionsize_and_more'),
    ]

    operations = [
        # 1. ProductionOrder.item FK
        migrations.AddField(
            model_name='productionorder',
            name='item',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='production_orders',
                to='inventory.item',
                verbose_name='الموديل (صنف)',
                help_text='اختار صنف موجود لو الموديل ده اتعمل قبل كده. '
                          'سيب الخانة فاضية لو موديل جديد — هيتعمل تلقائياً '
                          'باسم/كود الموديل الجديد.',
            ),
        ),

        # 2. ProductionSubModel.sub_model_no: blank=True (auto-assigned)
        migrations.AlterField(
            model_name='productionsubmodel',
            name='sub_model_no',
            field=models.PositiveSmallIntegerField(
                blank=True,
                verbose_name='رقم الموديل الفرعي',
                help_text='يتولد تلقائياً (1, 2, 3, ...)',
            ),
        ),

        # 3. ProductionSize: rename quantity → planned_quantity, add actual_quantity
        migrations.RenameField(
            model_name='productionsize',
            old_name='quantity',
            new_name='planned_quantity',
        ),
        migrations.AlterField(
            model_name='productionsize',
            name='planned_quantity',
            field=models.PositiveIntegerField(
                verbose_name='المخطط (عدد قطع)',
                help_text='الكمية المطلوب إنتاجها — تتطبع على ورقة العمل',
            ),
        ),
        migrations.AddField(
            model_name='productionsize',
            name='actual_quantity',
            field=models.PositiveIntegerField(
                default=0,
                verbose_name='الفعلي (عدد قطع)',
                help_text='الكمية اللي اتنتجت فعلياً — تتعبا بعد ما الإنتاج يخلص',
            ),
        ),

        # 4. FabricUsage: rename quantity_kg → planned_qty_kg, add actual_qty_kg
        migrations.RenameField(
            model_name='fabricusage',
            old_name='quantity_kg',
            new_name='planned_qty_kg',
        ),
        migrations.AlterField(
            model_name='fabricusage',
            name='planned_qty_kg',
            field=models.DecimalField(
                max_digits=12, decimal_places=3,
                verbose_name='المخطط (كيلو)',
                help_text='الكمية المخططة من الدفعة دي',
            ),
        ),
        migrations.AddField(
            model_name='fabricusage',
            name='actual_qty_kg',
            field=models.DecimalField(
                max_digits=12, decimal_places=3, default=Decimal('0'),
                verbose_name='الفعلي (كيلو)',
                help_text='الكمية اللي اتصرفت فعلياً (افتراضياً = المخطط)',
            ),
        ),
    ]
