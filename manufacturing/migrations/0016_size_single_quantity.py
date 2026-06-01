"""Drop ProductionSize.actual_quantity, rename planned_quantity → quantity.
The single 'quantity' is now both planned AND actual — if there's a piece
shortfall, the user reflects it via extra fabric (actual_qty_kg > planned_qty_kg).
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('manufacturing', '0015_remove_fabricmovement_dye_order_and_more'),
    ]

    operations = [
        migrations.RemoveField(model_name='productionsize', name='actual_quantity'),
        migrations.RenameField(
            model_name='productionsize',
            old_name='planned_quantity',
            new_name='quantity',
        ),
        migrations.AlterField(
            model_name='productionsize',
            name='quantity',
            field=models.PositiveIntegerField(
                verbose_name='الكمية (عدد قطع)',
                help_text='المخطط = الفعلي. لو في عجز في القطع، '
                          'يتعالج بزيادة استهلاك القماش (قص زيادة) — '
                          'مش بتغيير العدد هنا.',
            ),
        ),
    ]
