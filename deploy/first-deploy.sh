#!/usr/bin/env bash
# Roma ERP — first-time deployment script.
# Assumes:
#   - You are in the project root
#   - `.env` is already filled in
#   - DNS A-record for $DOMAIN points to this server
#
# Usage:  bash deploy/first-deploy.sh

set -euo pipefail

if [ ! -f .env ]; then
  echo "ERROR: .env file missing.  Copy .env.example to .env and fill it in first."
  exit 1
fi

# Load env vars
set -a
. ./.env
set +a

if [ -z "${DOMAIN:-}" ] || [ "$DOMAIN" = "app.example.com" ]; then
  echo "ERROR: set DOMAIN in .env to your real domain."
  exit 1
fi

echo "==> Replacing nginx domain placeholder…"
sed -i "s/COMFIT_DOMAIN/${DOMAIN}/g" deploy/nginx.conf

echo "==> Phase 1: bring up Postgres + Django without nginx HTTPS"
# Temporarily disable the SSL server block so nginx can boot before the cert exists.
cp deploy/nginx.conf deploy/nginx.conf.bak
sed -i 's|^\(\s*ssl_certificate\)|# \1|g; s|^\(\s*ssl_certificate_key\)|# \1|g; s|^\(\s*listen 443\)|# \1|g; s|^\(\s*http2 on;\)|# \1|g' deploy/nginx.conf

docker compose up -d --build db web nginx

echo "==> Waiting for nginx to be reachable on :80…"
sleep 5

echo "==> Phase 2: obtain Let's Encrypt certificate via webroot challenge"
docker compose run --rm certbot certonly \
  --webroot -w /var/www/certbot \
  -d "$DOMAIN" \
  --email "$LE_EMAIL" \
  --agree-tos --no-eff-email \
  --non-interactive

echo "==> Phase 3: restore nginx HTTPS config + restart"
mv deploy/nginx.conf.bak deploy/nginx.conf
sed -i "s/COMFIT_DOMAIN/${DOMAIN}/g" deploy/nginx.conf
docker compose restart nginx

echo "==> Phase 4: start certbot auto-renew loop"
docker compose up -d certbot

echo
echo "============================================================"
echo "  ✓ النشر اكتمل.  افتح:  https://${DOMAIN}/"
echo "  - لإنشاء أول مستخدم admin:"
echo "      docker compose exec web python manage.py createsuperuser"
echo "  - لزرع شجرة الحسابات (idempotent):"
echo "      docker compose exec web python manage.py seed_coa"
echo "============================================================"
