"""عميل تليجرام بسيط (stdlib بس — من غير مكتبات إضافية).

بيستخدم long polling: بنسأل تليجرام «فيه رسايل جديدة؟» ونستنى لحد ما تيجي.
مفيش webhook فمحتاجش أي إعداد SSL أو دومين للبوت.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

API = 'https://api.telegram.org/bot{token}/{method}'
# أطول رسالة تليجرام بيقبلها = 4096 حرف؛ بنسيب هامش للتقطيع.
MAX_LEN = 3900


class TelegramError(Exception):
    pass


class Telegram:
    def __init__(self, token, timeout=70):
        self.token = token
        self.timeout = timeout

    def _call(self, method, payload=None):
        url = API.format(token=self.token, method=method)
        data = json.dumps(payload or {}).encode('utf-8')
        req = urllib.request.Request(
            url, data=data, headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                body = json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            raise TelegramError(f'{method}: HTTP {e.code} — {e.read()[:300]}')
        except Exception as e:                       # timeout / شبكة
            raise TelegramError(f'{method}: {e}')
        if not body.get('ok'):
            raise TelegramError(f'{method}: {body.get("description")}')
        return body.get('result')

    def get_updates(self, offset=None, timeout=60):
        """بيرجّع الرسايل الجديدة. offset = آخر update_id + 1 (عشان ميكررش)."""
        payload = {'timeout': timeout, 'allowed_updates': ['message']}
        if offset is not None:
            payload['offset'] = offset
        return self._call('getUpdates', payload) or []

    def send(self, chat_id, text, reply_to=None):
        """بيبعت رسالة (وبيقطّعها لو أطول من حد تليجرام)."""
        sent = []
        for chunk in _split(text or '…', MAX_LEN):
            payload = {'chat_id': chat_id, 'text': chunk,
                       'disable_web_page_preview': True}
            if reply_to and not sent:
                payload['reply_to_message_id'] = reply_to
            sent.append(self._call('sendMessage', payload))
        return sent

    def send_typing(self, chat_id):
        try:
            self._call('sendChatAction', {'chat_id': chat_id, 'action': 'typing'})
        except TelegramError:
            pass                                     # مؤشر الكتابة مش مهم لو فشل

    def me(self):
        return self._call('getMe')


def _split(text, limit):
    """بيقطّع النص عند آخر سطر قبل الحد، عشان الجداول متتكسرش في النص."""
    out = []
    while len(text) > limit:
        cut = text.rfind('\n', 0, limit)
        if cut < limit // 2:
            cut = limit
        out.append(text[:cut])
        text = text[cut:].lstrip('\n')
    out.append(text)
    return out
