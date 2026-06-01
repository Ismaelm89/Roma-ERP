"""Drop the legacy fabric_supplier and fabric_dyer FKs from JournalLine.
Data was already copied to the unified `supplier` FK by manufacturing 0004.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_journalline_supplier_alter_journalline_fabric_dyer_and_more'),
        ('manufacturing', '0005_schema_cleanup'),
    ]

    operations = [
        migrations.RemoveField(model_name='journalline', name='fabric_supplier'),
        migrations.RemoveField(model_name='journalline', name='fabric_dyer'),
    ]
