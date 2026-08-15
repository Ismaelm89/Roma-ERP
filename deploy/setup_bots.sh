#!/usr/bin/env bash
# إعداد بوتات التليجرام — بيسأل سؤال سؤال وبيشغّل البوتين.
# البوتين بيشتغلوا على اشتراك Claude بتاعك (مفيش مفتاح API مدفوع).
# التشغيل:  bash /opt/roma-erp/deploy/setup_bots.sh
set -u
cd /opt/roma-erp || { echo "مش لاقي /opt/roma-erp"; exit 1; }

echo "════════════════════════════════════════"
echo "   إعداد بوتات تليجرام — روما"
echo "════════════════════════════════════════"
echo

# ── 1) مصادقة claude بالاشتراك ────────────────────────────────
if claude auth status >/dev/null 2>&1 || [ -f "$HOME/.claude.json" ]; then
  echo "✅ claude متصل بحسابك خلاص."
else
  echo "خطوة 1: توصيل claude بحساب الاشتراك بتاعك."
  echo "هيفتح رابط — افتحه من الموبايل/الكمبيوتر وسجّل دخول، والزق الكود هنا."
  echo
  claude setup-token || { echo "❌ المصادقة فشلت. جرّب تاني."; exit 1; }
  echo
fi

# ── 2) توكنز تليجرام ─────────────────────────────────────────
echo "دلوقتي 3 أسئلة. الزق الإجابة ودوس Enter."
echo "(التوكن مش هيظهر على الشاشة — ده طبيعي)"
echo

ask() {
  local prompt="$1" var="$2" val=""
  while [ -z "$val" ]; do
    printf '%s\n> ' "$prompt"
    read -r -s val; echo
    [ -z "$val" ] && echo "  ⚠️  مينفعش تسيبها فاضية، جرّب تاني."
  done
  printf -v "$var" '%s' "$val"
}

ask "1/3 — توكن بوت المدير (من BotFather):" ADMIN_TOKEN
ask "2/3 — توكن بوت العمليات (من BotFather):" OPS_TOKEN

echo "3/3 — رقمك في تليجرام (من @userinfobot) — أرقام بس:"
printf '> '
read -r MYID
case "$MYID" in
  ''|*[!0-9]*) echo "  ❌ لازم أرقام بس. ابدأ تاني."; exit 1 ;;
esac

sed -i '/^TELEGRAM_/d' .env 2>/dev/null
cat >> .env <<EOF
TELEGRAM_ADMIN_BOT_TOKEN=$ADMIN_TOKEN
TELEGRAM_ADMIN_ALLOWED_IDS=$MYID
TELEGRAM_OPS_BOT_TOKEN=$OPS_TOKEN
TELEGRAM_OPS_ALLOWED_IDS=$MYID
EOF
chmod 600 .env

# ── 3) تشغيل ─────────────────────────────────────────────────
echo
echo "✅ اتحفظت. بشغّل البوتين..."
cp deploy/roma-admin-bot.service deploy/roma-ops-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now roma-admin-bot roma-ops-bot
sleep 6

echo
echo "──────── النتيجة ────────"
echo "• بوت المدير:   $(systemctl is-active roma-admin-bot)"
echo "• بوت العمليات: $(systemctl is-active roma-ops-bot)"
echo
echo "خلاص ✅ افتح البوتين في تليجرام واكتب /start"
echo "لو فيه مشكلة:  journalctl -u roma-ops-bot -n 30"
