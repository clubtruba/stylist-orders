#!/usr/bin/env bash
set -euo pipefail
mountpoint -q /mnt/ai
mountpoint -q /mnt/archive_hdd_serv
repo=/mnt/ai/repos/stylist-orders
local_backup=/mnt/ai/backups/stylist-orders
other_backup=/mnt/archive_hdd_serv/stylist-orders
mkdir -p "$local_backup" "$other_backup"
chmod 700 "$local_backup" "$other_backup"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
umask 077
docker compose --env-file /mnt/ai/compose/stylist-orders/.env -f "$repo/infrastructure/production/compose.yml" exec -T db pg_dump -U stylist_orders -d stylist_orders -Fc > "$local_backup/$stamp.dump.partial"
mv "$local_backup/$stamp.dump.partial" "$local_backup/$stamp.dump"
tar -C /mnt/ai/data/stylist-orders -czf "$local_backup/$stamp.proofs.tar.gz" payment-proofs
cp "$local_backup/$stamp.dump" "$local_backup/$stamp.proofs.tar.gz" "$other_backup/"
printf 'Backup completed: %s\n' "$stamp"
