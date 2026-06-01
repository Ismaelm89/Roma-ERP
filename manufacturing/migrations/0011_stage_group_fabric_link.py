"""Phase 2 follow-up:
  - ProductionOrderStage.worker_name → group_name (rename)
  - FabricUsage.stage FK to ProductionOrderStage (so fabric inputs sit
    under the cutting stage tree-style).
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('manufacturing', '0010_seed_default_work_stages'),
    ]

    operations = [
        # 1. Rename worker_name → group_name
        migrations.RenameField(
            model_name='productionorderstage',
            old_name='worker_name',
            new_name='group_name',
        ),
        migrations.AlterField(
            model_name='productionorderstage',
            name='group_name',
            field=models.CharField(
                blank=True, max_length=200,
                verbose_name='اسم المجموعة',
                help_text='مجموعة الصنايعية اللي شغّالة في المرحلة دي '
                          '(مثال: مجموعة أحمد)',
            ),
        ),
        # 2. Add stage FK on FabricUsage
        migrations.AddField(
            model_name='fabricusage',
            name='stage',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='fabric_usages',
                to='manufacturing.productionorderstage',
                verbose_name='المرحلة',
                help_text='سيب الخانة فاضية = القماش بيدخل مرحلة القص تلقائياً',
            ),
        ),
        # 3. Update help_text on qty_in for context
        migrations.AlterField(
            model_name='productionorderstage',
            name='qty_in',
            field=models.PositiveIntegerField(
                default=0,
                verbose_name='كمية الدخول',
                help_text='عدد القطع اللي دخلت المرحلة دي '
                          '(لمرحلة القص: مش الكميات، انت بتدخل القماش بدلاً منها)',
            ),
        ),
    ]
