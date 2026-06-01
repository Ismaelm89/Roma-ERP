"""Seed the 5 default work stages used to auto-populate every new PO:
   قص → طباعة → تشغيل → مكوى وتكييس → تخزين.
User can edit / add / remove from admin afterwards.
"""
from django.db import migrations


DEFAULTS = [
    ('قص', 1),
    ('طباعة', 2),
    ('تشغيل', 3),
    ('مكوى وتكييس', 4),
    ('تخزين', 5),
]


def forward(apps, schema_editor):
    WorkStage = apps.get_model('manufacturing', 'WorkStage')
    for name, order in DEFAULTS:
        WorkStage.objects.get_or_create(
            name=name,
            defaults={'sort_order': order, 'is_default': True, 'active': True},
        )


def backward(apps, schema_editor):
    WorkStage = apps.get_model('manufacturing', 'WorkStage')
    WorkStage.objects.filter(name__in=[n for n, _ in DEFAULTS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('manufacturing', '0009_accessory_workstage_alter_productionorder_title_and_more'),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
