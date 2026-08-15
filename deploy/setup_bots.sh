#!/usr/bin/env bash
# إعداد بوتات التليجرام — بيسأل سؤال سؤال وبيكتب المفاتيح في .env لوحده.
# التشغيل:  bash /opt/roma-erp/deploy/setup_bots.sh
set -u
cd /opt/roma-erp || { echo "مش لاقي /opt/roma-erp"; exit 1; }

echo "════════════════════════════════════════"
echo "   إعداد بوتات تليجرام — روما"
echo "════════════════════════════════════════"
echo
echo "هسألك 4 أسئلة. الزق الإجابة ودوس Enter."
echo "(اللي بتكتبه مش هيظهر على الشاشة — ده طبيعي)"
echo

ask() {                      # ask "السؤال" اسم_المتغير
  local prompt="$1" var="$2" val=""
  while [ -z "$val" ]; do
    printf '%s\n> ' "$prompt"
    read -r -s val; echo
    [ -z "$val" ] && echo "  ⚠️  مينفعش تسيبها فاضية، جرّب تاني."
  done
  printf -v "$var" '%s' "$val"
}

ask "1/4 — مفتاح Anthropic (بيبدأ بـ sk-ant-):" ANTHROPIC
case "$ANTHROPIC" in
  sk-ant-*) ;;
  *) echo "  ⚠️  المفتاح المفروض يبدأ بـ sk-ant- — لو غلط اقفل ونفّذ تاني."; ;;
esac

ask "2/4 — توكن بوت المدير (من BotFather):" ADMIN_TOKEN
ask "3/4 — توكن بوت العمليات (من BotFather):" OPS_TOKEN

echo "4/4 — رقمك في تليجرام (من @userinfobot) — أرقام بس:"
printf '> '
read -r MYID
case "$MYID" in
  ''|*[!0-9]*) echo "  ❌ لازم أرقام بس. ابدأ تاني."; exit 1 ;;
esac

# شيل أي إعداد قديم للبوتات عشان ميتكررش
sed -i '/^ANTHROPIC_API_KEY=/d;/^TELEGRAM_/d' .env 2>/dev/null

cat >> .env <<EOF
ANTHROPIC_API_KEY=$ANTHROPIC
TELEGRAM_ADMIN_BOT_TOKEN=$ADMIN_TOKEN
TELEGRAM_ADMIN_ALLOWED_IDS=$MYID
TELEGRAM_OPS_BOT_TOKEN=$OPS_TOKEN
TELEGRAM_OPS_ALLOWED_IDS=$MYID
EOF
chmod 600 .env

echo
echo "✅ المفاتيح اتحفظت. بشغّل البوتات دلوقتي..."
echo

docker compose --profile bots up -d --build opsbot || exit 1
cp deploy/roma-admin-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now roma-admin-bot
sleep 6

echo
echo "──────── النتيجة ────────"
echo "• بوت العمليات:"
docker compose logs --tail 3 opsbot 2>&1 | sed 's/^/    /'
echo "• بوت المدير: $(systemctl is-active roma-admin-bot)"
echo
echo "خلاص ✅ افتح البوتين في تليجرام واكتب /start"
