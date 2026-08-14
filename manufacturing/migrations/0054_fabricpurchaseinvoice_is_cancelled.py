from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('manufacturing', '0053_uninvoicedproductionorder'),
    ]

    operations = [
        migrations.AddField(
            model_name='fabricpurchaseinvoice',
            name='is_cancelled',
            field=models.BooleanField(default=False, editable=False, verbose_name='ملغاة'),
        ),
    ]
