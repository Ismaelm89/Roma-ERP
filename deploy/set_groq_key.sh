#!/usr/bin/env bash
# تفعيل تحويل الصوت السريع (Groq) — بيسأل المفتاح، يختبره، ويشغّل البوتات.
# التشغيل:  ssh root@SERVER -t "bash /opt/roma-erp/deploy/set_groq_key.sh"
set -u
cd /opt/roma-erp || { echo "مش لاقي /opt/roma-erp"; exit 1; }

echo "════════════════════════════════════════"
echo "   تفعيل تحويل الصوت السريع (Groq)"
echo "════════════════════════════════════════"
echo
echo "لو لسه معملتش مفتاح:"
echo "  ١) افتح  https://console.groq.com/keys"
echo "  ٢) سجّل دخول (مجاني — بجوجل أو إيميل)"
echo "  ٣) دوس Create API Key وانسخ المفتاح (بيبدأ بـ gsk_)"
echo
echo "الزق المفتاح هنا (مش هيظهر على الشاشة — ده طبيعي):"

KEY=''
for try in 1 2 3; do
  printf '> '
  read -r -s K; echo
  K="$(printf '%s' "$K" | tr -d ' \t\r\n"'\''')"
  case "$K" in
    gsk_*) [ "${#K}" -ge 20 ] && { KEY="$K"; break; }
           echo "  ❌ المفتاح قصير (${#K} حرف) — يبدو ناقص. جرّب تاني." ;;
    '')    echo "  ❌ مدخلتش حاجة. جرّب تاني." ;;
    *)     echo "  ❌ ده مش مفتاح Groq — لازم يبدأ بـ gsk_. جرّب تاني." ;;
  esac
done
[ -z "$KEY" ] && { echo "❌ مفيش مفتاح. شغّل السكربت تاني."; exit 1; }

echo
echo "بختبر المفتاح على ملف صوت حقيقي..."
if [ ! -f /tmp/test_ar.wav ]; then
  command -v espeak-ng >/dev/null 2>&1 && \
    espeak-ng -v ar -s 130 -w /tmp/test_ar.wav 'رصيد العميل جابر كام' 2>/dev/null
fi

OUT="$(GROQ_API_KEY="$KEY" deploy/.venv-stt/bin/python - <<'PY' 2>&1
import os, sys
sys.path.insert(0, '/opt/roma-erp/deploy')
import stt
try:
    print('OK:' + stt._groq('/tmp/test_ar.wav', os.environ['GROQ_API_KEY']))
except Exception as e:
    d = ''
    try:
        d = e.read()[:200].decode('utf-8', 'replace')
    except Exception:
        pass
    print('ERR:%s %s' % (e, d))
PY
)"

case "$OUT" in
  OK:*) echo "✅ المفتاح شغّال. النص اللي فهمه: ${OUT#OK:}" ;;
  *)    echo "❌ المفتاح مشتغلش:"; echo "   ${OUT#ERR:}"; echo "شغّل السكربت تاني."; exit 1 ;;
esac

sed -i '/^GROQ_API_KEY=/d' .env 2>/dev/null
echo "GROQ_API_KEY=$KEY" >> .env
chmod 600 .env
systemctl restart roma-admin-bot roma-ops-bot
sleep 5

echo
echo "• بوت المدير:   $(systemctl is-active roma-admin-bot)"
echo "• بوت العمليات: $(systemctl is-active roma-ops-bot)"
echo
echo "خلاص ✅ ابعت فويس نوت للبوت وهتلاقيه بيرد في ثواني."
