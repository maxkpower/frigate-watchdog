#!/bin/sh
# Run as root on the machine that will run the watchdog (the Proxmox host if Frigate is in an LXC).
set -e
cd "$(dirname "$0")"
install -m 755 frigate-watchdog /usr/local/sbin/frigate-watchdog
install -m 644 systemd/frigate-watchdog.service systemd/frigate-watchdog.timer /etc/systemd/system/
if [ ! -f /etc/frigate-watchdog.conf ]; then
  install -m 600 frigate-watchdog.conf.example /etc/frigate-watchdog.conf
  echo "Created /etc/frigate-watchdog.conf - edit it now, then run: frigate-watchdog --dry"
fi
mkdir -p /var/lib/frigate-watchdog && chmod 700 /var/lib/frigate-watchdog
systemctl daemon-reload
echo "Installed. NOT started. After editing the config and a clean --dry run:"
echo "  systemctl enable --now frigate-watchdog.timer"
