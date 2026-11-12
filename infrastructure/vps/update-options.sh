#!/usr/bin/env bash
# Update only browser code; keep existing compose, firewall, SSH and sandbox settings.
set -Eeuo pipefail
umask 022
[ "$(id -u)" -eq 0 ] || { echo 'Запустите через sudo'; exit 1; }
source_dir=$(cd -- "$(dirname -- "$0")" && pwd)
code_dir="$source_dir"
if [ ! -d "$code_dir/browser" ]; then code_dir=$(cd -- "$source_dir/../.." && pwd); fi
{
    date -u
    echo 'Обновление вариантов товара. Порты, SSH, firewall и настройки контейнера не меняются.'
    test -f /opt/stylist-browser/compose.yml
    backup_dir="/opt/stylist-browser/backups/options-$(date -u +%Y%m%dT%H%M%SZ)"
    install -d -m 700 "$backup_dir"
    cp -a /opt/stylist-browser/browser/app.py "$backup_dir/app.py"
    cp -a /opt/stylist-browser/backend/app/services/product_import.py "$backup_dir/product_import.py"
    old_image=$(docker inspect stylist-browser-vps-browser-1 --format '{{.Image}}')
    docker image tag "$old_image" "stylist-browser-vps:before-options-$(basename "$backup_dir")"
    compose_sha=$(sha256sum /opt/stylist-browser/compose.yml | cut -d ' ' -f 1)

    rollback() {
        code=$?
        trap - ERR
        set +e
        echo 'Проверка обновления не прошла. Возвращаю прежнюю браузерную службу.'
        cp -a "$backup_dir/app.py" /opt/stylist-browser/browser/app.py
        cp -a "$backup_dir/product_import.py" /opt/stylist-browser/backend/app/services/product_import.py
        docker image tag "$old_image" stylist-browser-vps:1.0
        docker compose -f /opt/stylist-browser/compose.yml up -d --no-deps --wait --wait-timeout 90 browser
        exit "$code"
    }
    trap rollback ERR
    install -m 644 "$code_dir/browser/app.py" /opt/stylist-browser/browser/app.py
    install -m 644 "$code_dir/backend/app/services/product_import.py" /opt/stylist-browser/backend/app/services/product_import.py
    docker compose -f /opt/stylist-browser/compose.yml build browser
    docker compose -f /opt/stylist-browser/compose.yml up -d --no-deps --wait --wait-timeout 90 browser
    test "$compose_sha" = "$(sha256sum /opt/stylist-browser/compose.yml | cut -d ' ' -f 1)"
    python3 "$source_dir/verify-options.py"
    docker inspect stylist-browser-vps-browser-1 --format 'State={{.State.Status}} User={{.Config.User}} Readonly={{.HostConfig.ReadonlyRootfs}} Security={{json .HostConfig.SecurityOpt}} Ports={{json .HostConfig.PortBindings}}'
    trap - ERR
    echo 'Обновление браузера завершено. Можно обновлять домашний бот.'
} 2>&1 | tee "$source_dir/update-options-result.log"
