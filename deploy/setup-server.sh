#!/usr/bin/env bash
# Roma ERP — one-shot server provisioner for Ubuntu 22.04 / 24.04.
# Run as root on a fresh Hetzner / DigitalOcean / Vultr / etc. VPS:
#
#   curl -fsSL https://raw.githubusercontent.com/<your-user>/<your-repo>/main/deploy/setup-server.sh | bash
#
# After this completes, edit `.env` and run `bash deploy/first-deploy.sh`.

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root (or via sudo)."
  exit 1
fi

echo "==> Updating system packages…"
apt-get update -y
apt-get upgrade -y

echo "==> Installing Docker, Compose, git, ufw, fail2ban…"
apt-get install -y \
  ca-certificates curl gnupg lsb-release \
  ufw fail2ban git unattended-upgrades

# Docker official repo
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" \
  > /etc/apt/sources.list.d/docker.list

apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

systemctl enable docker --now

echo "==> Firewall: allow SSH, 80, 443"
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
echo "y" | ufw enable

echo "==> Enabling unattended-upgrades (security patches)"
dpkg-reconfigure --priority=low unattended-upgrades || true

echo
echo "============================================================"
echo "  السيرفر جاهز ✓"
echo "  الخطوة التالية:"
echo "    1. clone repo:    git clone <your-repo-url> /opt/roma-erp"
echo "    2. cd /opt/roma-erp"
echo "    3. cp .env.example .env  &&  nano .env       # املأ القيم"
echo "    4. bash deploy/first-deploy.sh"
echo "============================================================"
