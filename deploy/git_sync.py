#!/usr/bin/env python3
"""commit + push تلقائي لأي تعديل البوت يعمله على الكود.

البوت بيعدّل الكود على السيرفر مباشرة، وده كان بيخلي /opt/roma-erp فيه كود
مش موجود في git خالص (وبالتالي `git pull` بيرفض يشتغل، والنسخة المحليّة على
اللاب بتبقى عمياء عن حاجات شغّالة فعلاً). الموديول ده بيتنده بعد كل مهمة:
لو فيه تعديل، بيعمل commit ويرفعه على GitHub.

أمان: فيه قائمة ملفات ممنوع ترفع أبداً (.env، مفاتيح، شهادات). لو ظهر أي
ملف منها، بنوقف الـ commit كله ونبلّغ المستخدم عشان يتصرّف بإيده — أحسن من
إننا نرفع سر بالغلط.

للاختبار: python3 deploy/git_sync.py
"""
import os
import re
import subprocess

REPO = os.environ.get('ROMA_REPO', '/opt/roma-erp')
BRANCH = os.environ.get('ROMA_BRANCH', 'main')

# ملفات ممنوع ترفع — لو واحد منها اتغيّر، بنوقف كل العملية.
SECRET_PATTERNS = [
    r'(^|/)\.env',                       # .env / .env.local / deploy/.env
    r'\.(pem|key|p12|pfx|crt)$',         # مفاتيح وشهادات
    r'(^|/)id_(rsa|ed25519|ecdsa)',      # مفاتيح SSH
    r'(^|/)\.ssh/',
    r'(^|/)data_dump',                   # dumps فيها هاشات باسوردات
]
_SECRET = re.compile('|'.join(SECRET_PATTERNS))


def _git(*args, timeout=120):
    """بينده git ويرجّع (نجح؟, المخرج)."""
    p = subprocess.run(['git', '-C', REPO, *args], capture_output=True,
                       text=True, timeout=timeout)
    out = ((p.stdout or '') + (p.stderr or '')).strip()
    return p.returncode == 0, out


def _changed_paths():
    """مسارات الملفات المتغيّرة من `git status --porcelain` (الملفات المتجاهلة مش داخلة)."""
    ok, out = _git('status', '--porcelain')
    if not ok or not out:
        return []
    paths = []
    for line in out.splitlines():
        rest = line[3:]
        # إعادة التسمية بتجي بالشكل "old -> new" — الاتنين يهمّونا.
        for part in rest.split(' -> '):
            part = part.strip().strip('"')
            if part:
                paths.append(part)
    return paths


def _subject(summary):
    """أول سطر من طلب المستخدم كعنوان للـ commit."""
    line = (summary or '').strip().splitlines()[0] if (summary or '').strip() else ''
    line = ' '.join(line.split())
    if len(line) > 68:
        line = line[:67] + '…'
    return line or 'تعديل من بوت المدير'


def autocommit(summary='', push=True):
    """بيعمل commit لأي تعديل ويرفعه. بيرجّع تقرير بالعربي أو None لو مفيش تعديل."""
    for marker in ('rebase-merge', 'rebase-apply', 'MERGE_HEAD', 'CHERRY_PICK_HEAD'):
        if os.path.exists(os.path.join(REPO, '.git', marker)):
            return ('⚠️ فيه عملية git ناقصة على السيرفر (rebase/merge) — '
                    'مش هعمل commit لحد ما تتخلّص بإيدك.')

    paths = _changed_paths()
    if not paths:
        return None

    secrets = sorted({p for p in paths if _SECRET.search(p)})
    if secrets:
        return ('⚠️ مرفوض الرفع: فيه ملفات حسّاسة اتغيّرت — ' + '، '.join(secrets)
                + '. التعديلات موجودة على السيرفر بس مش مرفوعة؛ راجعها بإيدك.')

    ok, out = _git('add', '-A')
    if not ok:
        return f'⚠️ git add فشل: {out[:300]}'

    ok, out = _git('commit', '-m', _subject(summary), '-m',
                   (f'طلب المستخدم: {summary.strip()}\n\n' if summary.strip() else '')
                   + 'اتعمل من بوت المدير على تليجرام.\n\n'
                     'Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>')
    if not ok:
        if 'nothing to commit' in out:
            return None
        _git('reset')
        return f'⚠️ git commit فشل: {out[:300]}'

    ok, sha = _git('rev-parse', '--short', 'HEAD')
    sha = sha if ok else '?'
    files = len(set(paths))
    report = f'📌 commit {sha} — {files} ملف'

    if not push:
        return report + ' (محلي، من غير رفع)'

    # لازم نكون متقدمين على origin عشان الرفع ينجح لو حد غيّر من مكان تاني.
    _git('fetch', 'origin', BRANCH, timeout=120)
    ok, out = _git('rebase', f'origin/{BRANCH}', timeout=180)
    if not ok:
        _git('rebase', '--abort')
        return (report + f'\n⚠️ الرفع وقف: فيه تعارض مع GitHub — {out[-300:]}\n'
                'التعديل متحفوظ محلياً على السيرفر.')

    ok, out = _git('push', 'origin', f'HEAD:{BRANCH}', timeout=180)
    if not ok:
        return (report + f'\n⚠️ الرفع فشل: {out[-400:]}\n'
                'التعديل متحفوظ محلياً على السيرفر.')
    return report + ' ✓ مرفوع على GitHub'


if __name__ == '__main__':
    print(autocommit('اختبار يدوي لـ git_sync', push=False) or 'مفيش تعديلات.')
