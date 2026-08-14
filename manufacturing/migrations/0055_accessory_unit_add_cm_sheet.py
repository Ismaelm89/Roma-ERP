from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('manufacturing', '0054_fabricpurchaseinvoice_is_cancelled'),
    ]

    operations = [
        migrations.AlterField(
            model_name='accessory',
            name='unit',
            field=models.CharField(
                choices=[('قطعة', 'قطعة'), ('متر', 'متر'), ('سم', 'سم'), ('كيلو', 'كيلو'),
                         ('لفة', 'لفة'), ('فرخ', 'فرخ'), ('طقم', 'طقم'), ('علبة', 'علبة'),
                         ('دستة', 'دستة'), ('بكرة', 'بكرة')],
                default='قطعة', max_length=20, verbose_name='وحدة الاستهلاك'),
        ),
        migrations.AlterField(
            model_name='accessory',
            name='purchase_unit',
            field=models.CharField(
                choices=[('قطعة', 'قطعة'), ('متر', 'متر'), ('سم', 'سم'), ('كيلو', 'كيلو'),
                         ('لفة', 'لفة'), ('فرخ', 'فرخ'), ('طقم', 'طقم'), ('علبة', 'علبة'),
                         ('دستة', 'دستة'), ('بكرة', 'بكرة')],
                default='قطعة', max_length=20, verbose_name='وحدة الشراء'),
        ),
    ]
