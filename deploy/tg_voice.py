"""استقبال الفويس نوت من تليجرام وتحويله لنص — بيستخدمه البوتين الاتنين."""
import json
import os
import sys
import urllib.request

MAX_VOICE_SECONDS = int(os.environ.get('MAX_VOICE_SECONDS', '180'))


def is_voice(msg):
    return bool(msg.get('voice') or msg.get('audio') or msg.get('video_note'))


def _download(token, file_id):
    req = urllib.request.Request(
        f'https://api.telegram.org/bot{token}/getFile',
        data=json.dumps({'file_id': file_id}).encode('utf-8'),
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        path = json.loads(r.read().decode('utf-8'))['result']['file_path']
    dest = os.path.join('/tmp', 'tg_' + os.path.basename(path))
    url = f'https://api.telegram.org/file/bot{token}/{path}'
    with urllib.request.urlopen(url, timeout=180) as r, open(dest, 'wb') as f:
        f.write(r.read())
    return dest


def to_text(token, msg):
    """بيرجّع (النص, رسالة خطأ للمستخدم). النص فاضي لو فيه مشكلة."""
    v = msg.get('voice') or msg.get('audio') or msg.get('video_note')
    if not v:
        return '', ''
    if (v.get('duration') or 0) > MAX_VOICE_SECONDS:
        return '', f'الرسالة الصوتية طويلة أوي (الحد {MAX_VOICE_SECONDS} ثانية).'
    path = None
    try:
        path = _download(token, v['file_id'])
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from stt import transcribe
        text = transcribe(path)
        return (text, '') if text else ('', 'مسمعتش كلام واضح في الرسالة الصوتية.')
    except Exception as e:
        print('stt failed:', e, file=sys.stderr)
        return '', f'مقدرتش أحوّل الصوت لنص: {e}'
    finally:
        if path:
            try:
                os.remove(path)
            except OSError:
                pass
