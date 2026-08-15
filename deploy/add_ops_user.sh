#!/usr/bin/env bash
# إضافة (أو شيل) موظف من بوت العمليات.
#
#   bash deploy/add_ops_user.sh 123456789        ← يضيف
#   bash deploy/add_ops_user.sh -r 123456789     ← يشيل
#   bash deploy/add_ops_user.sh                  ← يعرض المسموح لهم
set -u
cd /opt/roma-erp || { echo "مش لاقي /opt/roma-erp"; exit 1; }

CUR="$(grep '^TELEGRAM_OPS_ALLOWED_IDS=' .env 2>/dev/null | cut -d= -f2-)"

show() {
  echo "المسموح لهم دلوقتي في بوت العمليات:"
  echo "  ${1:-(مفيش)}" | tr ',' '\n' | sed 's/^/  /'
}

if [ $# -eq 0 ]; then
  show "$CUR"
  echo
  echo "للإضافة:  bash deploy/add_ops_user.sh 123456789"
  echo "للشيل:    bash deploy/add_ops_user.sh -r 123456789"
  exit 0
fi

REMOVE=no
if [ "$1" = "-r" ]; then REMOVE=yes; shift; fi
ID="${1:-}"
case "$ID" in
  ''|*[!0-9]*) echo "❌ لازم رقم تليجرام (أرقام بس)."; exit 1 ;;
esac

# ابني القايمة الجديدة من غير تكرار
NEW="$(printf '%s\n' "$CUR" | tr ',' '\n' | sed 's/[[:space:]]//g' | grep -v "^$ID$" \
       | grep -v '^$' | paste -sd, -)"
if [ "$REMOVE" = no ]; then
  NEW="${NEW:+$NEW,}$ID"
fi
if [ -z "$NEW" ]; then
  echo "❌ مينفعش تسيب القايمة فاضية (البوت هيرفض الكل)."; exit 1
fi

sed -i '/^TELEGRAM_OPS_ALLOWED_IDS=/d' .env
echo "TELEGRAM_OPS_ALLOWED_IDS=$NEW" >> .env
chmod 600 .env
systemctl restart roma-ops-bot
sleep 4

if [ "$REMOVE" = yes ]; then echo "✅ اتشال $ID"; else echo "✅ اتضاف $ID"; fi
show "$NEW"
echo
echo "بوت العمليات: $(systemctl is-active roma-ops-bot)"
