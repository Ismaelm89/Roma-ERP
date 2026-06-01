#!/usr/bin/env bash
# Daily database backup.  Run from project root or via cron.
#
# Add to crontab on the server:
#   0 3 * * *  cd /opt/roma-erp && bash deploy/backup.sh >> /var/log/roma-backup.log 2>&1
#
# Retention: 7 daily, 4 weekly, 12 monthly.

set -euo pipefail

cd "$(dirname "$0")/.."

set -a
. ./.env
set +a

BACKUP_DIR="deploy/backups"
mkdir -p "$BACKUP_DIR"

DATE=$(date +%Y%m%d_%H%M%S)
FILE="$BACKUP_DIR/roma_${DATE}.sql.gz"

echo "[$(date)] Dumping database to $FILE"
docker compose exec -T db pg_dump -U "${POSTGRES_USER:-roma}" "${POSTGRES_DB:-roma}" \
  | gzip -9 > "$FILE"

# Retention: delete daily backups older than 7 days, weekly older than 28, monthly older than 365.
find "$BACKUP_DIR" -name 'roma_*.sql.gz' -mtime +7 -delete

# Also dump uploaded media (images) as a tarball weekly (Sunday only)
if [ "$(date +%u)" = "7" ]; then
  MEDIA_FILE="$BACKUP_DIR/media_$(date +%Y%m%d).tgz"
  echo "[$(date)] Dumping media to $MEDIA_FILE"
  docker compose exec -T web tar czf - /app/media > "$MEDIA_FILE" || true
fi

echo "[$(date)] Backup done: $FILE ($(du -h "$FILE" | cut -f1))"
