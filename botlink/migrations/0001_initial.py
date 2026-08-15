from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name='BotAuditLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('bot', models.CharField(choices=[('OPS', 'بوت العمليات'),
                                                  ('ADMIN', 'بوت المدير')],
                                         default='OPS', max_length=10, verbose_name='البوت')),
                ('telegram_user_id', models.BigIntegerField(db_index=True,
                                                            verbose_name='Telegram ID')),
                ('telegram_name', models.CharField(blank=True, max_length=120,
                                                   verbose_name='الاسم')),
                ('allowed', models.BooleanField(default=True, verbose_name='مصرّح له')),
                ('message', models.TextField(verbose_name='الرسالة')),
                ('tools_used', models.TextField(blank=True,
                                                verbose_name='الأدوات اللي اتنفّذت')),
                ('reply', models.TextField(blank=True, verbose_name='الرد')),
                ('tokens', models.PositiveIntegerField(default=0, verbose_name='التوكنز')),
                ('ok', models.BooleanField(default=True, verbose_name='تمّت')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True,
                                                    verbose_name='التاريخ')),
            ],
            options={
                'verbose_name': 'سجل بوت',
                'verbose_name_plural': 'سجل البوتات',
                'ordering': ['-created_at'],
            },
        ),
    ]
