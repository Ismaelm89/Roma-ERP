"""Change FabricUsage.stage on_delete from PROTECT to SET_NULL so deleting
a PO (CASCADE through stages) doesn't conflict with fabric usages."""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('manufacturing', '0011_stage_group_fabric_link'),
    ]

    operations = [
        migrations.AlterField(
            model_name='fabricusage',
            name='stage',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='fabric_usages',
                to='manufacturing.productionorderstage',
                verbose_name='المرحلة',
                help_text='سيب الخانة فاضية = القماش بيدخل مرحلة القص تلقائياً',
            ),
        ),
    ]
