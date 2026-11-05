from django.db import migrations, models


class Migration(migrations.Migration):
    """تسجيل وحدات «سم» و«فرخ» في وحدة الشراء كمان (choices بس — مفيش تغيير في الداتابيز)."""

    dependencies = [
        ('manufacturing', '0055_accessory_unit_add_cm_sheet'),
    ]

    operations = [
        migrations.AlterField(
            model_name='accessory',
            name='purchase_unit',
            field=models.CharField(choices=[('قطعة', 'قطعة'), ('متر', 'متر'), ('سم', 'سم'), ('كيلو', 'كيلو'), ('لفة', 'لفة'), ('فرخ', 'فرخ'), ('طقم', 'طقم'), ('علبة', 'علبة'), ('دستة', 'دستة'), ('بكرة', 'بكرة')], default='قطعة', help_text='الوحدة اللي بتشتري بيها من المورد', max_length=20, verbose_name='وحدة الشراء'),
        ),
        migrations.AlterField(
            model_name='accessory',
            name='unit',
            field=models.CharField(choices=[('قطعة', 'قطعة'), ('متر', 'متر'), ('سم', 'سم'), ('كيلو', 'كيلو'), ('لفة', 'لفة'), ('فرخ', 'فرخ'), ('طقم', 'طقم'), ('علبة', 'علبة'), ('دستة', 'دستة'), ('بكرة', 'بكرة')], default='قطعة', help_text='الوحدة اللي بتستهلك بيها في الإنتاج (المخزون والتكلفة محسوبين بيها)', max_length=20, verbose_name='وحدة الاستهلاك'),
        ),
    ]
