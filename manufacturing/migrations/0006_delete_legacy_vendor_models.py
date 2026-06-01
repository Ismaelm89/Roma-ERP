"""Drop the legacy FabricSupplier and FabricDyer tables.
Their data was already copied to the unified Supplier model in migration 0004.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('manufacturing', '0005_schema_cleanup'),
        ('core', '0005_drop_legacy_vendor_fks'),
    ]

    operations = [
        migrations.DeleteModel(name='FabricSupplier'),
        migrations.DeleteModel(name='FabricDyer'),
    ]
