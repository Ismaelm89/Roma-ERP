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
echo "دلوقتي الزق التوكن اللي ظهر فوق (بيبدأ بـ sk-ant-oat)."
echo "(مش هيظهر على الشاشة وإنت بتلزق — ده طبيعي)"
printf '> '
read -r -s TOKEN; echo

if [ -z "$TOKEN" ]; then
  echo "❌ مدخلتش حاجة. شغّل السكربت تاني."
  exit 1
fi
case "$TOKEN" in
  sk-ant-*) ;;
  *) echo "⚠️  التوكن المفروض يبدأ بـ sk-ant- — لو غلط شغّل السكربت تاني."; ;;
esac

sed -i '/^CLAUDE_CODE_OAUTH_TOKEN=/d' .env 2>/dev/null
echo "CLAUDE_CODE_OAUTH_TOKEN=$TOKEN" >> .env
chmod 600 .env
echo "✅ التوكن اتحفظ."
echo

echo "بختبر..."
if CLAUDE_CODE_OAUTH_TOKEN="$TOKEN" timeout 90 claude -p 'اكتب كلمة تمام بس' \
     --permission-mode dontAsk 2>&1 | grep -qi 'not logged in'; then
  echo "❌ لسه مش متصل — يمكن التوكن اتلزق ناقص. شغّل السكربت تاني."
  exit 1
fi
echo "✅ claude متصل وشغّال."
echo

systemctl restart roma-admin-bot roma-ops-bot
sleep 5
echo "• بوت المدير:   $(systemctl is-active roma-admin-bot)"
echo "• بوت العمليات: $(systemctl is-active roma-ops-bot)"
echo
echo "خلاص ✅ جرّب تكلّم البوت من تليجرام."
