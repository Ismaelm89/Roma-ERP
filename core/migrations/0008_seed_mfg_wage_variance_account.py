"""Backfill the manufacturing wage-variance expense account at 5370000.

Migration 0007 originally tried to seed this account at code 5360000, but some
live databases already use 5360000 for a user-created "مصروفات بنكية" account,
so the get_or_create matched that row and the variance account was never made.
We relocated it to the free code 5370000 (see account_codes.py / seed_coa.py);
this migration creates it for databases that already applied 0007.

Idempotent: get_or_create, so fresh installs (where 0007 already made 5370000)
and re-runs are safe.
"""
from django.db import migrations


VARIANCE_ACCOUNT = (
    # code, name_ar, name_en, account_type, parent_code
    '5370000', 'فرق مصنعيات (زيادة عن المستحق)', 'Mfg Wage Variance', 'EXPENSE', '5300000',
)


def seed(apps, schema_editor):
    Account = apps.get_model('core', 'Account')
    code, name_ar, name_en, acct_type, parent_code = VARIANCE_ACCOUNT
    parent = Account.objects.filter(code=parent_code).first()
    Account.objects.get_or_create(
        code=code,
        defaults=dict(name_ar=name_ar, name_en=name_en, account_type=acct_type,
                      parent=parent, is_group=False, is_active=True),
    )


def unseed(apps, schema_editor):
    # Only remove if no journal lines reference it (account FK is PROTECT).
    Account = apps.get_model('core', 'Account')
    acct = Account.objects.filter(code=VARIANCE_ACCOUNT[0]).first()
    if acct and not acct.lines.exists():
        acct.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_seed_mfg_wage_accounts'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
