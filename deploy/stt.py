#!/usr/bin/env python3
"""تحويل الفويس نوت لنص — شغّال على السيرفر نفسه (مجاناً، من غير أي خدمة مدفوعة).

بيستخدم faster-whisper. النموذج بيتحمّل مرة واحدة أول استخدام وبيفضل في الذاكرة،
فأول فويس نوت بتاخد وقت زيادة والباقي أسرع.

بيتنادى من بوتات تليجرام:  from stt import transcribe
وكمان ينفع من الترمينال للاختبار:  python3 deploy/stt.py file.ogg
"""
import os
import sys

MODEL_SIZE = os.environ.get('STT_MODEL', 'small')     # base=أسرع · small=أدق
LANGUAGE = os.environ.get('STT_LANG', 'ar')
_model = None


def _load():
    """بيحمّل النموذج مرة واحدة بس (تحميل ثقيل نسبياً)."""
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        # int8 على المعالج = أسرع بكتير وبدقة قريبة من float
        _model = WhisperModel(MODEL_SIZE, device='cpu', compute_type='int8',
                              cpu_threads=max(1, (os.cpu_count() or 4) - 2),
                              download_root=os.path.join(
                                  os.path.dirname(os.path.abspath(__file__)),
                                  '.whisper-models'))
    return _model


def transcribe(path):
    """بيرجّع نص الفويس نوت (أو نص فاضي لو مفيش كلام مفهوم)."""
    model = _load()
    segments, _info = model.transcribe(
        path, language=LANGUAGE, vad_filter=True,
        # الأرقام والأسماء بتطلع أظبط لما ندّي النموذج سياق الشغل
        initial_prompt='محادثة عن نظام مبيعات ومخزون: فواتير، عملاء، موردين، '
                       'إيصالات قبض، أوامر إنتاج، مقاسات وكميات.')
    return ' '.join(s.text.strip() for s in segments).strip()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit('الاستخدام: python3 stt.py <ملف صوت>')
    print(transcribe(sys.argv[1]))
