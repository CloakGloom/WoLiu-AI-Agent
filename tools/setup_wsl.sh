#!/bin/bash
set -e

echo "=== Step 1: Fix DNS ==="
echo "nameserver 114.114.114.114" > /etc/resolv.conf
echo "nameserver 8.8.8.8" >> /etc/resolv.conf

echo "=== Step 2: Update apt ==="
apt-get update -y

echo "=== Step 3: Install Docker dependencies ==="
apt-get install -y ca-certificates curl

echo "=== Step 4: Add Docker GPG key ==="
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

echo "=== Step 5: Add Docker repo ==="
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list

echo "=== Step 6: Install Docker ==="
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo "=== Step 7: Add user to docker group ==="
DEFAULT_USER=$(getent passwd 1000 | cut -d: -f1)
if [ -n "$DEFAULT_USER" ]; then
    usermod -aG docker $DEFAULT_USER
    echo "Added $DEFAULT_USER to docker group"
fi

echo "=== Step 8: Start Docker ==="
service docker start

echo "=== DONE ==="