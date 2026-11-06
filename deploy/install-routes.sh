#!/bin/sh
# Run once on the server as root, from the repo's deploy/ folder:  sh install-routes.sh
set -e
mkdir -p /data/coolify/proxy/dynamic/mesora
chown 1000:1000 /data/coolify/proxy/dynamic/mesora        # the app runs as uid 1000
install -m 755 mesora-routes-sync /usr/local/bin/mesora-routes-sync
install -m 644 mesora-routes.service mesora-routes.path /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now mesora-routes.path
systemctl enable mesora-routes.service                     # also sync once at boot
/usr/local/bin/mesora-routes-sync
systemctl is-active mesora-routes.path
