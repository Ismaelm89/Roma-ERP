"""Make the default auto-seeded stages exactly: قص (1), تشغيل (2), مكوى وتكييس (3).
Removes قص/تخزين from earlier seeds and demotes طباعة out of the defaults.
Idempotent + safe on fresh installs."""
from django.db import migrations


def forward(apps, schema_editor):
    WorkStage = apps.get_model('manufacturing', 'WorkStage')

    WorkStage.objects.update_or_create(
        name='قص', defaults={'sort_order': 1, 'is_default': True, 'active': True})
    WorkStage.objects.update_or_create(
        name='تشغيل', defaults={'sort_order': 2, 'is_default': True, 'active': True})
    WorkStage.objects.update_or_create(
        name='مكوى وتكييس', defaults={'sort_order': 3, 'is_default': True, 'active': True})

    # Demote / disable stages that are no longer auto-seeded
    WorkStage.objects.filter(name='طباعة').update(is_default=False)
    WorkStage.objects.filter(name='تخزين').delete()


def backward(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('manufacturing', '0018_cuttinggroup_ironinggroup_sewinggroup'),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
