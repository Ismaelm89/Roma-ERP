#!/usr/bin/env python3
"""بوت العمليات — بيشتغل على اشتراك Claude (من غير مفتاح API مدفوع).

بينده `claude` في وضع headless بس **مقفول** على أدوات العمليات بتاعتنا بس
(عن طريق خادم MCP جوّه الكونتينر): مفيش ترمينال، مفيش قراية/كتابة ملفات،
مفيش كود. أي حركة بتغيّر بيانات مقفولة ورا تأكيد المستخدم في نفس الشات.

التشغيل: python3 deploy/ops_bot.py   (خدمة systemd: roma-ops-bot)
"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

REPO = os.environ.get('ROMA_REPO', '/opt/roma-erp')
MCP_CONFIG = os.path.join(REPO, 'deploy', 'mcp-ops.json')
SESSION_DIR = os.path.join(REPO, 'deploy', '.ops_sessions')
TIMEOUT = int(os.environ.get('OPS_BOT_TIMEOUT', '300'))
MAX_LEN = 3900

# كل أدوات كلود الأصلية مقفولة — بس أدوات روما شغّالة.
ALLOWED = 'mcp__roma-ops'
DISALLOWED = ['Bash', 'Edit', 'Write', 'Read', 'NotebookEdit', 'WebFetch',
              'WebSearch', 'Task', 'Agent', 'Glob', 'Grep']

SYSTEM = """إنت مساعد العمليات في نظام «روما للملابس» (ERP جملة ملابس).

- اتكلم **مصري عامي** دايماً، ومختصر وواضح.
- الأرقام بصيغة 5,500.00 (فاصلة للآلاف، نقطة للكسر).
- استخدم أدوات روما للبيانات الحقيقية — متخمّنش أرقام ولا أكواد من دماغك أبداً.
- **التأكيد قبل التنفيذ:** أي حركة بتغيّر بيانات، الأداة هترجّعلك ملخّص —
  اعرضه على المستخدم واسأله «تمام؟»، وأول ما يوافق نادي نفس الأداة تاني
  بنفس البيانات + confirm=true.
- لو الاسم مش واضح أو فيه أكتر من نتيجة، اسأل المستخدم يحدّد.
- إنت مالكش دعوة بالكود ولا الوصفات ولا أسعار المنتجات ولا الإعدادات.
- بعد أي حركة تتنفّذ، اذكر رقم المستند والإجمالي.
- ردّك بيتبعت على تليجرام: نص عادي مختصر، من غير جداول ماركداون."""

HELP = """أهلاً 👋 أنا مساعد العمليات بتاع روما.

اكتبلي اللي عايزه بالعربي، مثال:
• «رصيد طارق القناوي كام؟»
• «اعمل فاتورة لعادل سعد: شورت ابيض XL 12 و M 12»
• «اعمل إيصال قبض 5000 من جابر على بنك فيصل»
• «قيمة المخزون كام؟»

أي حاجة هتغيّر بيانات هقولك عليها الأول وأستنى تقولي «تمام».
/new = ابدأ محادثة جديدة"""


def api(token, method, payload=None, timeout=70):
    req = urllib.request.Request(
        f'https://api.telegram.org/bot{token}/{method}',
        data=json.dumps(payload or {}).encode('utf-8'),
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8')).get('result')


def send(token, chat, text):
    text = text or '…'
    while text:
        chunk, text = text[:MAX_LEN], text[MAX_LEN:]
        try:
            api(token, 'sendMessage', {'chat_id': chat, 'text': chunk,
                                       'disable_web_page_preview': True})
        except Exception as e:
            print('send failed:', e, file=sys.stderr)
            return


def keep_typing(token, chat, stop):
    """بيفضل يبعت «بيكتب...» كل 4 ثواني لحد ما الرد يجهز (المؤشر بيختفي بسرعة)."""
    while not stop.wait(4):
        try:
            api(token, 'sendChatAction', {'chat_id': chat, 'action': 'typing'},
                timeout=10)
        except Exception:
            pass


def _sfile(chat):
    os.makedirs(SESSION_DIR, exist_ok=True)
    return os.path.join(SESSION_DIR, f'{chat}.sid')


def get_session(chat):
    try:
        with open(_sfile(chat)) as f:
            return f.read().strip() or None
    except OSError:
        return None


def set_session(chat, sid):
    try:
        with open(_sfile(chat), 'w') as f:
            f.write(sid or '')
    except OSError:
        pass


def run_claude(chat, prompt):
    cmd = ['claude', '-p', prompt, '--output-format', 'json',
           '--mcp-config', MCP_CONFIG, '--strict-mcp-config',
           '--allowedTools', ALLOWED,
           '--disallowedTools', *DISALLOWED,
           '--append-system-prompt', SYSTEM,
           '--permission-mode', 'dontAsk']
    sid = get_session(chat)
    if sid:
        cmd += ['--resume', sid]
    try:
        p = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True,
                           timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return 'الطلب خد وقت طويل. جرّب تقوله بشكل أبسط.', sid
    out = (p.stdout or '').strip()
    if not out:
        return f'مفيش رد. خطأ: {(p.stderr or "")[:800]}', sid
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return out[:3500], sid
    if isinstance(data, dict):
        return (data.get('result') or data.get('text') or 'تمام.',
                data.get('session_id') or sid)
    return str(data)[:3500], sid


def main():
    token = os.environ.get('TELEGRAM_OPS_BOT_TOKEN', '').strip()
    allowed = {x.strip() for x in
               os.environ.get('TELEGRAM_OPS_ALLOWED_IDS', '').split(',') if x.strip()}
    if not token:
        sys.exit('TELEGRAM_OPS_BOT_TOKEN مش متظبط')
    if not allowed:
        sys.exit('TELEGRAM_OPS_ALLOWED_IDS مش متظبطة')
    allowed = {int(x) for x in allowed}
    me = api(token, 'getMe')
    print(f'بوت العمليات شغّال: @{me.get("username")} | المصرّح لهم: {sorted(allowed)}')

    offset = None
    while True:
        try:
            updates = api(token, 'getUpdates',
                          {'timeout': 50, 'offset': offset,
                           'allowed_updates': ['message']}, timeout=70) or []
        except Exception as e:
            print('polling:', e, file=sys.stderr)
            time.sleep(5)
            continue

        for u in updates:
            offset = u['update_id'] + 1
            msg = u.get('message') or {}
            text = (msg.get('text') or '').strip()
            if not text:
                continue
            chat = msg['chat']['id']
            uid = (msg.get('from') or {}).get('id')
            if uid not in allowed:
                send(token, chat, 'مش مصرّحلك تستخدم البوت ده.')
                continue
            if text in ('/start', '/help'):
                send(token, chat, HELP)
                continue
            if text == '/new':
                set_session(chat, '')
                send(token, chat, 'تمام، بدأنا محادثة جديدة.')
                continue
            stop = threading.Event()
            threading.Thread(target=keep_typing, args=(token, chat, stop),
                             daemon=True).start()
            try:
                reply, sid = run_claude(chat, text)
            finally:
                stop.set()
            if sid:
                set_session(chat, sid)
            send(token, chat, reply)


if __name__ == '__main__':
    main()
