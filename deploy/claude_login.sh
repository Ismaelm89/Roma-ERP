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

# بنشغّل setup-token جوّه `script` عشان يفضل تفاعلي (المتصفح + الكود) وفي نفس
# الوقت نسجّل المخرجات في ملف مؤقت، فنقدر نطلّع التوكن منه **أوتوماتيك** —
# من غير ما المستخدم يحتاج ينسخ ويلزق حاجة (وده كان بيغلط كتير).
LOG="$(mktemp)"
chmod 600 "$LOG"
trap 'shred -u "$LOG" 2>/dev/null || rm -f "$LOG"' EXIT

script -q -e -c "claude setup-token" "$LOG" </dev/tty >/dev/tty 2>&1

TOKEN="$(grep -oE 'sk-ant-oat[A-Za-z0-9_.-]{20,}' "$LOG" | tail -1)"

if [ -z "$TOKEN" ]; then
  echo
  echo "مقدرتش ألتقط التوكن أوتوماتيك — الزقه بإيدك (السطر اللي بيبدأ sk-ant-oat01):"
  for try in 1 2 3; do
    printf '> '
    read -r -s T; echo
    T="$(printf '%s' "$T" | tr -d ' \t\r\n\"'\''')"
    case "$T" in
      sk-ant-oat*) [ "${#T}" -ge 60 ] && { TOKEN="$T"; break; }
                   echo "  ❌ ناقص (${#T} حرف). جرّب تاني." ;;
      '')          echo "  ❌ مدخلتش حاجة. جرّب تاني." ;;
      *)           echo "  ❌ ده مش توكن. جرّب تاني." ;;
    esac
  done
fi

if [ -z "$TOKEN" ]; then
  echo "❌ مفيش توكن. شغّل السكربت تاني."
  exit 1
fi
echo
echo "✅ التقطت التوكن (${#TOKEN} حرف)."

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
