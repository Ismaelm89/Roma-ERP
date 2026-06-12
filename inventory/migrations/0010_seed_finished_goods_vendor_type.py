from django.db import migrations


def add_finished_goods_vendor_type(apps, schema_editor):
    VendorType = apps.get_model('manufacturing', 'VendorType')
    VendorType.objects.get_or_create(
        code='FINISHED_GOODS',
        defaults={'name_ar': 'مورد منتجات تامة (تجارة)', 'sort_order': 5, 'active': True},
    )


def remove_finished_goods_vendor_type(apps, schema_editor):
    VendorType = apps.get_model('manufacturing', 'VendorType')
    VendorType.objects.filter(code='FINISHED_GOODS').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0009_finishedgoodspurchaseinvoice_and_more'),
        ('manufacturing', '0042_accessory_conversion_note_accessory_purchase_unit_and_more'),
    ]

    operations = [
        migrations.RunPython(add_finished_goods_vendor_type,
                             remove_finished_goods_vendor_type),
    ]
