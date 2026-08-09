#!/bin/bash
echo "=== Interfaces ==="
ip addr show | grep -E "inet |^[0-9]"

echo ""
echo "=== Default routes ==="
ip route show default

echo ""
echo "=== resolv.conf ==="
cat /etc/resolv.conf

echo ""
echo "=== Try common Windows IPs ==="
for ip in 172.19.0.1 192.168.2.1 10.255.255.254 127.0.0.1; do
    code=$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 2 "http://${ip}:17890" 2>/dev/null)
    echo "${ip}: ${code}"
done