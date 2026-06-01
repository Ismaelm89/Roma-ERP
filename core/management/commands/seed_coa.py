"""Seed a minimal Egyptian-style Chart of Accounts for Roma.
Idempotent — re-running only adds missing accounts.

Usage:
    python manage.py seed_coa
"""
from django.core.management.base import BaseCommand
from core.models import Account, CashAccount, ExpenseCategory


COA = [
    # code, name_ar, name_en, type, parent_code, is_group
    ('1000000', 'الأصول',              'Assets',              'ASSET',     None,       True),
    ('1100000', 'الأصول المتداولة',     'Current Assets',      'ASSET',     '1000000',  True),
    ('1110000', 'الصندوق',              'Cash on Hand',        'ASSET',     '1100000',  False),
    ('1120000', 'البنك',                'Bank',                'ASSET',     '1100000',  False),
    ('1210000', 'العملاء',              'Accounts Receivable', 'ASSET',     '1100000',  False),
    ('1310000', 'المخزون',              'Inventory',           'ASSET',     '1100000',  False),
    ('1320000', 'إنتاج تحت التشغيل',    'Work In Progress',    'ASSET',     '1100000',  False),
    ('1330000', 'مخزون الأقمشة',         'Fabric Inventory',    'ASSET',     '1100000',  False),
    ('1340000', 'مخزون الإكسسوارات',     'Accessory Inventory', 'ASSET',     '1100000',  False),
    ('1420000', 'ضريبة القيمة المضافة - مدخلات', 'VAT Receivable', 'ASSET', '1100000', False),

    # النقدية والبنوك والمحافظ الإضافية — حسابات الخزينة بتتولّد تحت المجموعة دي
    ('1190000', 'النقدية والبنوك والمحافظ', 'Cash / Banks / Wallets', 'ASSET', '1100000', True),

    # الأصول الثابتة (سجل أصول — من غير إهلاك دلوقتي)
    ('1500000', 'الأصول الثابتة',        'Fixed Assets',        'ASSET',     '1000000',  True),
    ('1510000', 'أثاث ومفروشات',         'Furniture & Fixtures','ASSET',     '1500000',  False),
    ('1520000', 'آلات ومعدات',           'Machinery & Equipment','ASSET',    '1500000',  False),
    ('1530000', 'أجهزة وكمبيوتر',        'Computers & Devices', 'ASSET',     '1500000',  False),
    ('1540000', 'سيارات ووسائل نقل',     'Vehicles',            'ASSET',     '1500000',  False),
    ('1590000', 'أصول ثابتة أخرى',       'Other Fixed Assets',  'ASSET',     '1500000',  False),

    ('2000000', 'الخصوم',               'Liabilities',         'LIABILITY', None,       True),
    ('2100000', 'الخصوم المتداولة',     'Current Liabilities', 'LIABILITY', '2000000',  True),
    ('2110000', 'الموردون',             'Accounts Payable',    'LIABILITY', '2100000',  False),
    ('2210000', 'ضريبة القيمة المضافة - مخرجات', 'VAT Payable', 'LIABILITY', '2100000', False),
    ('2310000', 'ضريبة الخصم تحت حساب',  'WHT Payable',         'LIABILITY', '2100000',  False),
    ('2320000', 'مصنعيات مستحقة',        'Accrued Mfg Wages',   'LIABILITY', '2100000',  False),

    ('3000000', 'حقوق الملكية',         'Equity',              'EQUITY',    None,       True),
    ('3110000', 'رأس المال',             'Capital',             'EQUITY',    '3000000',  False),
    ('3120000', 'جاري الشريك',          "Partner's Current A/C",'EQUITY',   '3000000',  False),
    ('3210000', 'الأرباح المحتجزة',     'Retained Earnings',   'EQUITY',    '3000000',  False),
    ('3310000', 'حساب الأرصدة الافتتاحية', 'Opening Balance Equity', 'EQUITY', '3000000', False),

    ('4000000', 'الإيرادات',             'Revenue',             'REVENUE',   None,       True),
    ('4110000', 'إيرادات المبيعات',     'Sales Revenue',       'REVENUE',   '4000000',  False),
    ('4120000', 'مرتجعات المبيعات',     'Sales Returns',       'REVENUE',   '4000000',  False),

    ('5000000', 'المصروفات',             'Expenses',            'EXPENSE',   None,       True),
    ('5110000', 'تكلفة البضاعة المباعة', 'Cost of Goods Sold',  'EXPENSE',   '5000000',  False),
    ('5210000', 'خسارة جرد',             'Inventory Loss',      'EXPENSE',   '5000000',  False),
    ('5220000', 'ربح جرد',                'Inventory Gain',      'EXPENSE',   '5000000',  False),

    # مصروفات تشغيلية وإدارية (سندات الصرف)
    ('5300000', 'مصروفات تشغيلية وإدارية', 'Operating Expenses', 'EXPENSE',  '5000000',  True),
    ('5310000', 'الرواتب والأجور',        'Salaries & Wages',    'EXPENSE',   '5300000',  False),
    ('5320000', 'الإيجارات',              'Rent',                'EXPENSE',   '5300000',  False),
    ('5330000', 'الصيانة',                'Maintenance',         'EXPENSE',   '5300000',  False),
    ('5340000', 'المواصلات والشحن',       'Transport & Shipping','EXPENSE',   '5300000',  False),
    ('5350000', 'المرافق (كهرباء/مياه/تليفون)', 'Utilities',     'EXPENSE',   '5300000',  False),
    ('5370000', 'فرق مصنعيات (زيادة عن المستحق)', 'Mfg Wage Variance', 'EXPENSE', '5300000', False),
    ('5390000', 'مصروفات أخرى',           'Other Expenses',      'EXPENSE',   '5300000',  False),
]


# Starter expense categories: (name_ar, gl_account_code)
EXPENSE_CATEGORIES = [
    ('الرواتب والأجور',  '5310000'),
    ('الإيجارات',        '5320000'),
    ('الصيانة',          '5330000'),
    ('المواصلات والشحن', '5340000'),
    ('المرافق',          '5350000'),
    ('مصروفات أخرى',     '5390000'),
]


class Command(BaseCommand):
    help = 'Seed minimal Egyptian-style Chart of Accounts for Roma.'

    def handle(self, *args, **opts):
        created = 0
        for code, name_ar, name_en, acct_type, parent_code, is_group in COA:
            parent = Account.objects.filter(code=parent_code).first() if parent_code else None
            _, was_created = Account.objects.get_or_create(
                code=code,
                defaults=dict(
                    name_ar=name_ar,
                    name_en=name_en,
                    account_type=acct_type,
                    parent=parent,
                    is_group=is_group,
                    is_active=True,
                ),
            )
            if was_created:
                created += 1
        total = Account.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f'COA seeded: {created} new accounts added (total now: {total}).'
        ))

        # --- Default treasury (cash) accounts --------------------------------
        # نربط الصندوق/البنك الافتراضيين بحسابات الـ COD الموجودة (1110000 / 1120000)
        # عشان نفضل متوافقين مع منطق الترحيل القديم. لو الـ gl_account متبعت مسبقاً،
        # CashAccount.save() مش هيولّد حساب جديد تحت 1190000.
        cash_created = 0
        DEFAULT_CASH = [
            # name, type, gl_code, is_default
            ('الصندوق', 'CASH', '1110000', True),
            ('البنك',   'BANK', '1120000', False),
        ]
        for name, acct_type, gl_code, is_default in DEFAULT_CASH:
            if CashAccount.objects.filter(name=name).exists():
                continue
            gl = Account.objects.filter(code=gl_code).first()
            CashAccount.objects.create(
                name=name, account_type=acct_type,
                gl_account=gl, is_default=is_default, active=True,
            )
            cash_created += 1
        if cash_created:
            self.stdout.write(self.style.SUCCESS(
                f'Treasury: {cash_created} default cash account(s) added.'
            ))

        # --- Starter expense categories --------------------------------------
        cat_created = 0
        for name_ar, gl_code in EXPENSE_CATEGORIES:
            gl = Account.objects.filter(code=gl_code).first()
            _, was_created = ExpenseCategory.objects.get_or_create(
                name_ar=name_ar,
                defaults=dict(gl_account=gl, active=True),
            )
            if was_created:
                cat_created += 1
        if cat_created:
            self.stdout.write(self.style.SUCCESS(
                f'Expenses: {cat_created} starter expense categor(ies) added.'
            ))
