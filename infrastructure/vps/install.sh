#!/usr/bin/env bash
set -euo pipefail
umask 022
[ "$(id -u)" -eq 0 ] || { echo 'Нужен запуск через sudo'; exit 1; }
source_dir=$(cd -- "$(dirname -- "$0")" && pwd)
code_dir="$source_dir"
if [ ! -d "$code_dir/browser" ]; then code_dir=$(cd -- "$source_dir/../.." && pwd); fi
{
    date -u
    echo 'Установка браузера с песочницей; публичные порты не добавляются.'
    /usr/sbin/sshd -t
    docker compose version
    iptables -w -S DOCKER-USER >/dev/null
    if ! docker network inspect stylist-browser-vps >/dev/null 2>&1; then
        if ip -4 route show | grep -q '^172\.30\.72\.'; then
            echo 'Выбранная подсеть уже занята. Остановка для проверки.'
            exit 1
        fi
        if ss -lntH '( sport = :18080 )' | grep -q .; then
            echo 'Порт18080 уже занят. Остановка для проверки.'
            exit 1
        fi
    fi
    install -d -m 755 /opt/stylist-browser
    install -d -m 755 /opt/stylist-browser/browser /opt/stylist-browser/backend/app/services
    cp -a "$code_dir/browser/." /opt/stylist-browser/browser/
    install -m 644 "$code_dir/backend/app/services/product_import.py" /opt/stylist-browser/backend/app/services/product_import.py
    cp -a "$source_dir/compose.yml" "$source_dir/seccomp_profile.json" "$source_dir/firewall.sh" "$source_dir/verify.py" /opt/stylist-browser/
    chown -R root:root /opt/stylist-browser
    chmod 755 /opt/stylist-browser/firewall.sh
    docker compose -f /opt/stylist-browser/compose.yml build browser

    if ! id stylist-browser-tunnel >/dev/null 2>&1; then
        useradd --system --create-home --home-dir /var/lib/stylist-browser-tunnel --shell /usr/sbin/nologin stylist-browser-tunnel
        usermod --password '*' stylist-browser-tunnel
    fi
    install -d -m 700 -o stylist-browser-tunnel -g stylist-browser-tunnel /var/lib/stylist-browser-tunnel/.ssh
    { printf 'restrict,port-forwarding,permitopen="127.0.0.1:18080",command="/usr/bin/false" '; cat "$source_dir/tunnel.pub"; } > /var/lib/stylist-browser-tunnel/.ssh/authorized_keys
    chown stylist-browser-tunnel:stylist-browser-tunnel /var/lib/stylist-browser-tunnel/.ssh/authorized_keys
    chmod 600 /var/lib/stylist-browser-tunnel/.ssh/authorized_keys
    ssh_config=/etc/ssh/sshd_config.d/60-stylist-browser-tunnel.conf
    if [ -e "$ssh_config" ]; then cp -a "$ssh_config" "$source_dir/tunnel-sshd.previous"; fi
    install -m 644 "$source_dir/tunnel-sshd.conf" "$ssh_config"
    if ! /usr/sbin/sshd -t; then
        if [ -e "$source_dir/tunnel-sshd.previous" ]; then cp -a "$source_dir/tunnel-sshd.previous" "$ssh_config"; else rm -f "$ssh_config"; fi
        echo 'Конфигурация SSH отклонена; изменение отменено.'
        exit 1
    fi
    /usr/sbin/sshd -T -C user=stylist-browser-tunnel,host=localhost,addr=127.0.0.1 | grep -E '^(allowtcpforwarding|permitopen|permitlisten|maxsessions|forcecommand|passwordauthentication|authenticationmethods) '
    systemctl reload ssh

    install -m 644 "$source_dir/stylist-browser-firewall.service" /etc/systemd/system/stylist-browser-firewall.service
    systemctl daemon-reload
    systemctl enable --now stylist-browser-firewall.service
    bash /opt/stylist-browser/firewall.sh
    docker compose -f /opt/stylist-browser/compose.yml up -d --wait --wait-timeout 90 browser
    python3 /opt/stylist-browser/verify.py
    docker compose -f /opt/stylist-browser/compose.yml ps
    echo 'Установка завершена. Домашний бот еще не переключен.'
} 2>&1 | tee "$source_dir/install-result.log"
