import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0017_item_shorts_fabric_color_alter_item_fabric_color'),
        ('sales', '0007_receipt_auto_generated_salesinvoice_cash_account_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='CustomerPrice',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('piece_price', models.DecimalField(
                    decimal_places=2, max_digits=12,
                    help_text='سعر القطعة للعميل ده. سعر الدستة = ده × عدد القطع في الدستة. '
                              'خصم التاجر بيتحسب فوقه.',
                    verbose_name='سعر القطعة الخاص')),
                ('active', models.BooleanField(default=True, verbose_name='نشط')),
                ('notes', models.CharField(blank=True, max_length=200,
                                           verbose_name='ملاحظات')),
                ('updated_at', models.DateTimeField(auto_now=True,
                                                    verbose_name='آخر تحديث')),
                ('customer', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='special_prices', to='sales.customer',
                    verbose_name='العميل')),
                ('variant', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='customer_prices', to='inventory.itemvariant',
                    verbose_name='المقاس (SKU)')),
            ],
            options={
                'verbose_name': 'سعر خاص بعميل',
                'verbose_name_plural': 'قوائم أسعار العملاء',
                'ordering': ['customer__code', 'variant__item__code',
                             'variant__size_order'],
                'unique_together': {('customer', 'variant')},
            },
        ),
    ]
