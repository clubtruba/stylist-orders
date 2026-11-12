#!/usr/bin/env bash
set -euo pipefail
# Only packets from the dedicated browser bridge are affected.
iptables -w -S DOCKER-USER >/dev/null
for chain in SBVPS-OUT SBVPS-HOST; do
    iptables -w -N "$chain" 2>/dev/null || true
    iptables -w -F "$chain"
done
iptables -w -A SBVPS-OUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
for subnet in 0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.168.0.0/16 224.0.0.0/4 240.0.0.0/4 82.165.142.124/32; do
    iptables -w -A SBVPS-OUT -d "$subnet" -j REJECT
done
iptables -w -A SBVPS-OUT -p tcp --dport 443 -j ACCEPT
iptables -w -A SBVPS-OUT -p udp --dport 53 -j ACCEPT
iptables -w -A SBVPS-OUT -p tcp --dport 53 -j ACCEPT
iptables -w -A SBVPS-OUT -j REJECT
iptables -w -A SBVPS-HOST -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -w -A SBVPS-HOST -j REJECT
iptables -w -C DOCKER-USER -i br-stylist-vps -j SBVPS-OUT 2>/dev/null || iptables -w -I DOCKER-USER 1 -i br-stylist-vps -j SBVPS-OUT
iptables -w -C INPUT -i br-stylist-vps -j SBVPS-HOST 2>/dev/null || iptables -w -I INPUT 1 -i br-stylist-vps -j SBVPS-HOST
