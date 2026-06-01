"""Seed the two manufacturing-wage accounts into existing databases:
  - 2320000  مصنعيات مستحقة      (liability — labor capitalized into inventory, not yet paid)
  - 5370000  فرق مصنعيات          (expense — over-spend above accrued wages)
Idempotent: get_or_create, so re-running / fresh installs are safe.
NOTE: 5370000 (not 5360000) — 5360000 is reserved for a user-created
"مصروفات بنكية" account in some live databases. Migration 0008 backfills
5370000 into databases that already applied this migration.
"""
from django.db import migrations


NEW_ACCOUNTS = [
    # code, name_ar, name_en, account_type, parent_code
    ('2320000', 'مصنعيات مستحقة', 'Accrued Mfg Wages', 'LIABILITY', '2100000'),
    ('5370000', 'فرق مصنعيات (زيادة عن المستحق)', 'Mfg Wage Variance', 'EXPENSE', '5300000'),
]


def seed(apps, schema_editor):
    Account = apps.get_model('core', 'Account')
    for code, name_ar, name_en, acct_type, parent_code in NEW_ACCOUNTS:
        parent = Account.objects.filter(code=parent_code).first()
        Account.objects.get_or_create(
            code=code,
            defaults=dict(name_ar=name_ar, name_en=name_en, account_type=acct_type,
                          parent=parent, is_group=False, is_active=True),
        )


def unseed(apps, schema_editor):
    # Only remove if no journal lines reference them (account FK is PROTECT).
    Account = apps.get_model('core', 'Account')
    for code, *_ in NEW_ACCOUNTS:
        acct = Account.objects.filter(code=code).first()
        if acct and not acct.lines.exists():
            acct.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_cashaccount_expensecategory_expensevoucher_and_more'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
