"""بوت العمليات على تليجرام.

الفكرة: تكلّم البوت بالعربي («اعمل فاتورة لفلان...») وهو يفهم ويجهّز الحركة،
بس **قبل ما ينفّذ** بيقولك «هعمل كذا وكذا — تمام؟» وأول ما تقول تمام بينفّذ.
التأكيد ده مقفول في الكود (مش مجرد تعليمات) — أي أداة بتغيّر بيانات مبتشتغلش
من غير confirm=true.

التشغيل:  python manage.py run_ops_bot
"""
import os
import time
import traceback

from django.core.management.base import BaseCommand, CommandError

from botlink import claude, tools_ops
from botlink.models import BotAuditLog
from botlink.telegram import Telegram, TelegramError

HELP = """أهلاً 👋 أنا مساعد العمليات بتاع روما.

اكتبلي اللي عايزه بالعربي، مثال:
• «رصيد طارق القناوي كام؟»
• «اعمل فاتورة لعادل سعد: شورت ابيض XL 12 و M 12»
• «اعمل إيصال قبض 5000 من جابر على بنك فيصل»
• «قيمة المخزون كام؟»

أي حاجة هتغيّر بيانات هقولك عليها الأول وأستنى تقولي «تمام».
/help = المساعدة | /new = ابدأ محادثة جديدة"""


class Command(BaseCommand):
    help = 'شغّل بوت العمليات على تليجرام (long polling)'

    def handle(self, *args, **opts):
        token = os.environ.get('TELEGRAM_OPS_BOT_TOKEN', '').strip()
        api_key = os.environ.get('ANTHROPIC_API_KEY', '').strip()
        allowed = {x.strip() for x in
                   os.environ.get('TELEGRAM_OPS_ALLOWED_IDS', '').split(',') if x.strip()}
        if not token:
            raise CommandError('TELEGRAM_OPS_BOT_TOKEN مش متظبط في .env')
        if not api_key:
            raise CommandError('ANTHROPIC_API_KEY مش متظبط في .env')
        if not allowed:
            raise CommandError('TELEGRAM_OPS_ALLOWED_IDS مش متظبطة — '
                               'لازم تحدد مين مسموحله يستخدم البوت.')
        self.allowed = {int(x) for x in allowed}
        self.tg = Telegram(token)
        self.api_key = api_key
        self.sessions = {}                    # chat_id → history (ذاكرة المحادثة)

        me = self.tg.me()
        self.stdout.write(self.style.SUCCESS(
            f'بوت العمليات شغّال: @{me.get("username")} | '
            f'المصرّح لهم: {sorted(self.allowed)}'))

        offset = None
        while True:
            try:
                updates = self.tg.get_updates(offset=offset, timeout=50)
            except TelegramError as e:
                self.stderr.write(f'polling: {e}')
                time.sleep(5)
                continue
            for u in updates:
                offset = u['update_id'] + 1
                try:
                    self.handle_message(u.get('message') or {})
                except Exception:
                    traceback.print_exc()

    # ------------------------------------------------------------- routing
    def handle_message(self, msg):
        text = (msg.get('text') or '').strip()
        if not text:
            return
        chat = msg['chat']['id']
        frm = msg.get('from') or {}
        uid = frm.get('id')
        name = ' '.join(filter(None, [frm.get('first_name'), frm.get('last_name')])) \
            or frm.get('username') or str(uid)

        if uid not in self.allowed:
            BotAuditLog.objects.create(bot='OPS', telegram_user_id=uid or 0,
                                       telegram_name=name, allowed=False,
                                       message=text[:2000], ok=False,
                                       reply='مرفوض — مش في القايمة البيضا')
            self.tg.send(chat, 'مش مصرّحلك تستخدم البوت ده.')
            return

        if text in ('/start', '/help'):
            self.tg.send(chat, HELP)
            return
        if text == '/new':
            self.sessions.pop(chat, None)
            self.tg.send(chat, 'تمام، بدأنا محادثة جديدة.')
            return

        self.ask_claude(chat, uid, name, text)

    # ------------------------------------------------------------- claude
    def ask_claude(self, chat, uid, name, text):
        self.tg.send_typing(chat)
        history = self.sessions.setdefault(chat, [])
        used = []

        handlers = {}
        for tool, fn in tools_ops.HANDLERS.items():
            handlers[tool] = fn if tool in tools_ops.READ_ONLY else self._gate(tool, fn)

        try:
            reply, tokens = claude.run(
                self.api_key, tools_ops.SYSTEM, tools_ops.TOOLS, handlers,
                history, text, on_step=lambda n, a: used.append(n))
            ok = True
        except Exception as e:
            reply, tokens, ok = f'حصل خطأ: {e}', 0, False
            self.sessions.pop(chat, None)          # ابدأ محادثة نظيفة بعد الخطأ

        # خلّي الذاكرة محدودة عشان التكلفة متزيدش مع طول المحادثة
        if len(history) > 30:
            del history[:len(history) - 30]

        BotAuditLog.objects.create(bot='OPS', telegram_user_id=uid, telegram_name=name,
                                   message=text[:2000], tools_used=', '.join(used)[:1000],
                                   reply=reply[:4000], tokens=tokens, ok=ok)
        self.tg.send(chat, reply)

    def _gate(self, tool, fn):
        """قفل التأكيد: أي أداة بتغيّر بيانات مبتتنفّذش غير بـ confirm=true.

        النداء الأول بيرجّع ملخّص الحركة عشان البوت يعرضه على المستخدم ويستأذنه.
        ده مقفول في الكود عشان ميعتمدش على إن الموديل يفتكر يسأل.
        """
        def wrapper(**kwargs):
            confirmed = bool(kwargs.pop('confirm', False))
            if not confirmed:
                return ('محتاج تأكيد المستخدم الأول. اعرض عليه الحركة دي بالتفصيل '
                        'واسأله «تمام؟»، وأول ما يوافق نادي نفس الأداة تاني بنفس '
                        'البيانات + confirm=true:\n\n' + tools_ops.summarize(tool, kwargs))
            return fn(**kwargs)
        return wrapper
