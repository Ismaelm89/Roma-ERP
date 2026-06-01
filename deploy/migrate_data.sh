#!/usr/bin/env bash
# Roma ERP — migrate data from local SQLite (laptop) to server PostgreSQL.
#
# ON THE LAPTOP (Windows PowerShell):
#   $env:PYTHONIOENCODING = "utf-8"
#   .\.venv\Scripts\python.exe manage.py dumpdata \
#       --exclude contenttypes --exclude auth.permission \
#       --natural-foreign --natural-primary \
#       -o data_dump.json
#   # Upload data_dump.json to the server via:  scp data_dump.json root@SERVER_IP:/opt/roma-erp/
#
# ON THE SERVER (after first-deploy.sh succeeded):
#   bash deploy/migrate_data.sh data_dump.json

set -euo pipefail

DUMP="${1:-data_dump.json}"

if [ ! -f "$DUMP" ]; then
  echo "ERROR: dump file '$DUMP' not found."
  echo "Usage: bash deploy/migrate_data.sh <dump-file.json>"
  exit 1
fi

echo "==> Copying dump into the web container…"
docker compose cp "$DUMP" web:/tmp/data_dump.json

echo "==> Flushing existing data (keeps schema + migrations)…"
docker compose exec web python manage.py flush --no-input

echo "==> Loading dump…"
docker compose exec web python manage.py loaddata /tmp/data_dump.json

echo "==> Re-seeding COA (idempotent)…"
docker compose exec web python manage.py seed_coa

echo "==> Cleaning up…"
docker compose exec web rm -f /tmp/data_dump.json

echo "✓ Done.  Verify by opening https://\$DOMAIN/admin/"
