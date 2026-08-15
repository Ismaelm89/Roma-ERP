#!/usr/bin/env bash
# توصيل claude بحساب الاشتراك عشان البوتات تشتغل من غير مفتاح API مدفوع.
#
# `claude setup-token` بيعمل مصادقة بالمتصفح وبيطلّع **توكن طويل المدى**؛
# التوكن ده لازم يتحط في متغيّر البيئة CLAUDE_CODE_OAUTH_TOKEN عشان الخدمات
# (اللي بتشتغل في الخلفية) تستخدمه. السكربت ده بيعمل الاتنين ويعيد تشغيل البوتات.
#
# التشغيل:  ssh root@SERVER -t "bash /opt/roma-erp/deploy/claude_login.sh"
set -u
cd /opt/roma-erp || { echo "مش لاقي /opt/roma-erp"; exit 1; }

echo "════════════════════════════════════════"
echo "   توصيل claude بحسابك"
echo "════════════════════════════════════════"
echo
echo "١) هيظهرلك لينك — افتحه في المتصفح وسجّل دخول ووافق."
echo "٢) هيديك كود — الزقه هنا ودوس Enter."
echo "٣) في الآخر هيطلعلك **توكن طويل** — انسخه، هطلبه منك بعد كده."
echo
read -r -p "دوس Enter عشان نبدأ..." _
echo

claude setup-token
echo
echo "────────────────────────────────────────"
echo "دلوقتي الزق **التوكن** اللي ظهر فوق — السطر اللي بيبدأ بـ sk-ant-oat01"
echo "مش أي حاجة تانية (مش أمر SSH ولا الكود بتاع المتصفح)."
echo "(مش هيظهر على الشاشة وإنت بتلزق — ده طبيعي)"

TOKEN=''
for try in 1 2 3; do
  printf '> '
  read -r -s TOKEN; echo
  TOKEN="$(printf '%s' "$TOKEN" | tr -d ' \t\r\n\"'\''')"      # شيل مسافات/تنصيص
  case "$TOKEN" in
    sk-ant-oat*)
      if [ "${#TOKEN}" -ge 60 ]; then break; fi
      echo "  ❌ التوكن قصير (${#TOKEN} حرف) — يبدو إنه اتلزق ناقص. جرّب تاني." ;;
    '') echo "  ❌ مدخلتش حاجة. جرّب تاني." ;;
    *)  echo "  ❌ ده مش توكن — لازم يبدأ بـ sk-ant-oat01. جرّب تاني." ;;
  esac
  TOKEN=''
done
if [ -z "$TOKEN" ]; then
  echo "❌ التوكن مش مظبوط. شغّل السكربت تاني وخد بالك تنسخ السطر الصح."
  exit 1
fi

echo "بختبر التوكن قبل ما أحفظه..."
OUT="$(CLAUDE_CODE_OAUTH_TOKEN="$TOKEN" timeout 120 claude -p 'اكتب كلمة تمام بس' \
        --permission-mode dontAsk --output-format json 2>&1)"
if ! printf '%s' "$OUT" | grep -q '"is_error":false'; then
  echo "❌ التوكن مش شغّال. رد كلود:"
  printf '%s\n' "$OUT" | head -c 300; echo
  echo "شغّل السكربت تاني."
  exit 1
fi

sed -i '/^CLAUDE_CODE_OAUTH_TOKEN=/d' .env 2>/dev/null
echo "CLAUDE_CODE_OAUTH_TOKEN=$TOKEN" >> .env
chmod 600 .env
echo "✅ التوكن اتحفظ و claude متصل وشغّال."
echo

systemctl restart roma-admin-bot roma-ops-bot
sleep 5
echo "• بوت المدير:   $(systemctl is-active roma-admin-bot)"
echo "• بوت العمليات: $(systemctl is-active roma-ops-bot)"
echo
echo "خلاص ✅ جرّب تكلّم البوت من تليجرام."
