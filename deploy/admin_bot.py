#!/usr/bin/env python3
"""بوت المدير — Claude Code كامل على تليجرام.

بيوصّل رسايل تليجرام بـ `claude` CLI الشغّال على السيرفر جوّه /opt/roma-erp،
فبيبقى معاه نفس القدرات: يقرا ويعدّل الكود، Django shell، migrations، git، deploy.

بيشتغل على **المضيف** (مش جوّه الكونتينر) عشان يقدر يستخدم docker و git.
التشغيل: python3 deploy/admin_bot.py   (أو خدمة systemd: roma-admin-bot)

الأمان: بيرد بس على الـ Telegram IDs اللي في TELEGRAM_ADMIN_ALLOWED_IDS.
"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tg_voice

REPO = os.environ.get('ROMA_REPO', '/opt/roma-erp')
TIMEOUT = int(os.environ.get('ADMIN_BOT_TIMEOUT', '900'))     # 15 دقيقة للمهمة
STATE = os.path.join(REPO, 'deploy', '.admin_bot_session')
MAX_LEN = 3900

HELP = """أهلاً 👋 أنا بوت المدير — Claude Code على السيرفر.

اكتبلي أي حاجة زي ما بتكلّمه على الكمبيوتر:
• «عدّل كذا في الكود وانزله»
• «اعمل تقرير كذا من الداتا»
• «اعمل فاتورة كذا»

🎤 وتقدر تبعتلي **رسالة صوتية** بدل ما تكتب.

/new = ابدأ من أول وجديد (يمسح ذاكرة المحادثة)
/help = المساعدة"""


def api(token, method, payload=None, timeout=70):
    url = f'https://api.telegram.org/bot{token}/{method}'
    req = urllib.request.Request(
        url, data=json.dumps(payload or {}).encode('utf-8'),
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
    """بيفضل يبعت «بيكتب...» كل 4 ثواني لحد ما الرد يجهز.

    مؤشر تليجرام بيختفي بعد ~5 ثواني، والمهمة ممكن تاخد دقيقة أو أكتر —
    من غير ده المستخدم بيفتكر إن البوت مردش.
    """
    while not stop.wait(4):
        try:
            api(token, 'sendChatAction', {'chat_id': chat, 'action': 'typing'},
                timeout=10)
        except Exception:
            pass


def load_session():
    try:
        with open(STATE) as f:
            return f.read().strip() or None
    except OSError:
        return None


def save_session(sid):
    try:
        with open(STATE, 'w') as f:
            f.write(sid or '')
    except OSError:
        pass


# لازم نسمح بالأدوات صراحةً: وضع dontAsk لوحده بيرفض الأوامر اللي بيعتبرها خطرة
# (زي docker exec)، وبما إن البوت ده للمالك وبيشتغل من غير تفاعل — بنسمح بالكل.
ADMIN_TOOLS = ['Bash', 'Read', 'Edit', 'Write', 'Glob', 'Grep', 'NotebookEdit',
               'WebFetch', 'WebSearch', 'Task', 'TodoWrite']


def run_claude(prompt):
    """بينده claude في وضع headless وبيرجّع (النص, session_id)."""
    cmd = ['claude', '-p', prompt, '--output-format', 'json',
           '--permission-mode', 'dontAsk',
           '--allowedTools', *ADMIN_TOOLS]
    sid = load_session()
    if sid:
        cmd += ['--resume', sid]
    try:
        p = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True,
                           timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return 'المهمة خدت وقت طويل جداً ووقفت. جرّب تقسّمها لخطوات أصغر.', sid
    out = (p.stdout or '').strip()
    if not out:
        return f'مفيش رد. خطأ: {(p.stderr or "")[:1500]}', sid
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return out[:3500], sid
    if isinstance(data, dict):
        text = data.get('result') or data.get('text') or json.dumps(data)[:2000]
        return text, data.get('session_id') or sid
    return str(data)[:3500], sid


def main():
    token = os.environ.get('TELEGRAM_ADMIN_BOT_TOKEN', '').strip()
    allowed = {x.strip() for x in
               os.environ.get('TELEGRAM_ADMIN_ALLOWED_IDS', '').split(',') if x.strip()}
    if not token:
        sys.exit('TELEGRAM_ADMIN_BOT_TOKEN مش متظبط')
    if not allowed:
        sys.exit('TELEGRAM_ADMIN_ALLOWED_IDS مش متظبطة — البوت ده خطر من غيرها')
    allowed = {int(x) for x in allowed}
    me = api(token, 'getMe')
    print(f'بوت المدير شغّال: @{me.get("username")} | المصرّح لهم: {sorted(allowed)}')

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
            is_voice = tg_voice.is_voice(msg)
            text = (msg.get('text') or '').strip()
            if not text and not is_voice:
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
                save_session('')
                send(token, chat, 'تمام، بدأنا من أول وجديد.')
                continue

            stop = threading.Event()
            threading.Thread(target=keep_typing, args=(token, chat, stop),
                             daemon=True).start()
            try:
                if is_voice:
                    text, err = tg_voice.to_text(token, msg)
                    if err:
                        send(token, chat, err)
                        continue
                    # بنوريه اللي سمعناه عشان لو الكلام اتفهم غلط يصحّحه
                    send(token, chat, f'🎤 سمعت: {text}')
                reply, sid = run_claude(text)
            finally:
                stop.set()
            if sid:
                save_session(sid)
            send(token, chat, reply)


if __name__ == '__main__':
    main()
