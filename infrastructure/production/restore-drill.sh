#!/usr/bin/env bash
set -euo pipefail
mountpoint -q /mnt/ai
repo=/mnt/ai/repos/stylist-orders
backup=$(find /mnt/ai/backups/stylist-orders -maxdepth 1 -name '*.dump' -type f | sort | tail -n 1)
test -n "$backup"
test -f "${backup%.dump}.proofs.tar.gz"
compose=(docker compose --env-file /mnt/ai/compose/stylist-orders/.env -f "$repo/infrastructure/production/compose.yml")
drill="stylist_restore_$(date -u +%s)"
cleanup() { "${compose[@]}" exec -T db dropdb -U stylist_orders --if-exists "$drill"; }
trap cleanup EXIT
"${compose[@]}" exec -T db createdb -U stylist_orders "$drill"
"${compose[@]}" exec -T db pg_restore -U stylist_orders -d "$drill" --exit-on-error < "$backup"
version=$("${compose[@]}" exec -T db psql -U stylist_orders -d "$drill" -Atc 'SELECT version_num FROM alembic_version')
test "$version" = '0008_invites'
"${compose[@]}" exec -T db psql -U stylist_orders -d "$drill" -Atc 'SELECT count(*) FROM stylist_orders; SELECT count(*) FROM order_payments;'
tar -tzf "${backup%.dump}.proofs.tar.gz" > /dev/null
printf 'Isolated restore drill passed\n'
