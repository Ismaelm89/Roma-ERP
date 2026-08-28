#!/usr/bin/env python3
"""تحويل الفويس نوت لنص.

بيجرّب **Groq** الأول (نموذج whisper-large-v3 — أسرع وأدق بكتير في المصري،
وليه باقة مجانية)، ولو مفيش مفتاح أو الخدمة وقعت بيرجع للنموذج المحلي
(faster-whisper على السيرفر) عشان الصوت ميقفش خالص.

الاستخدام:  from stt import transcribe
للاختبار:   python3 deploy/stt.py file.ogg
"""
import json
import os
import sys
import urllib.error
import urllib.request

GROQ_URL = 'https://api.groq.com/openai/v1/audio/transcriptions'
GROQ_MODEL = os.environ.get('GROQ_STT_MODEL', 'whisper-large-v3-turbo')
LANGUAGE = os.environ.get('STT_LANG', 'ar')
MODEL_SIZE = os.environ.get('STT_MODEL', 'small')          # المحلي (احتياطي)
CONTEXT = ('محادثة عن نظام مبيعات ومخزون: فواتير، عملاء، موردين، إيصالات قبض، '
           'أوامر إنتاج، مقاسات وكميات.')
_model = None


# --------------------------------------------------------------- Groq
def _multipart(fields, filename, content):
    """تجميع طلب multipart بالـ stdlib (من غير مكتبات إضافية)."""
    b = '----RomaVoiceBoundary7d91f3a2c85e4b60'
    out = []
    for k, v in fields.items():
        out.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n'
                   f'{v}\r\n'.encode())
    out.append(f'--{b}\r\nContent-Disposition: form-data; name="file"; '
               f'filename="{filename}"\r\n'
               f'Content-Type: application/octet-stream\r\n\r\n'.encode())
    out.append(content)
    out.append(f'\r\n--{b}--\r\n'.encode())
    return b, b''.join(out)


def _groq(path, api_key, timeout=120):
    with open(path, 'rb') as f:
        content = f.read()
    boundary, body = _multipart(
        {'model': GROQ_MODEL, 'language': LANGUAGE,
         'response_format': 'json', 'prompt': CONTEXT},
        os.path.basename(path), content)
    # لازم User-Agent: Cloudflare بترفض الطلبات اللي مالهاش هوية (خطأ 1010).
    req = urllib.request.Request(GROQ_URL, data=body, headers={
        'Authorization': f'Bearer {api_key}',
        'Content-Type': f'multipart/form-data; boundary={boundary}',
        'User-Agent': 'roma-erp-voice/1.0',
        'Accept': 'application/json',
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return (json.loads(r.read().decode('utf-8')).get('text') or '').strip()


# --------------------------------------------------------------- محلي
def _load():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel(MODEL_SIZE, device='cpu', compute_type='int8',
                              cpu_threads=max(1, (os.cpu_count() or 4) - 2),
                              download_root=os.path.join(
                                  os.path.dirname(os.path.abspath(__file__)),
                                  '.whisper-models'))
    return _model


def _local(path):
    segments, _ = _load().transcribe(path, language=LANGUAGE, vad_filter=True,
                                     initial_prompt=CONTEXT)
    return ' '.join(s.text.strip() for s in segments).strip()


# --------------------------------------------------------------- الواجهة
def transcribe(path):
    """بيرجّع نص الفويس نوت (أو نص فاضي لو مفيش كلام مفهوم)."""
    key = os.environ.get('GROQ_API_KEY', '').strip()
    if key:
        try:
            text = _groq(path, key)
            if text:
                return text
            print('groq: رجّع نص فاضي — بجرّب المحلي', file=sys.stderr)
        except Exception as e:
            detail = ''
            if isinstance(e, urllib.error.HTTPError):
                try:
                    detail = e.read()[:200].decode('utf-8', 'replace')
                except Exception:
                    pass
            print(f'groq failed ({e}) {detail} — بجرّب المحلي', file=sys.stderr)
    return _local(path)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit('الاستخدام: python3 stt.py <ملف صوت>')
    print(transcribe(sys.argv[1]))
