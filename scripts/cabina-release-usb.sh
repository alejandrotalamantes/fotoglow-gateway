#!/bin/bash
# Libera la camara USB para gphoto2 (ejecutar como root).
# Uso: cabina-release-usb.sh [/dev/bus/usb/BBB/DDD]

set -eu

for proc in \
  gvfs-gphoto2-volume-monitor \
  gphoto2-volume-monitor \
  gvfs-mtp-volume-monitor \
  gvfsd-gphoto2 \
  gvfsd-mtp; do
  killall "$proc" 2>/dev/null || true
done

if [ -n "${1:-}" ] && [ -e "$1" ]; then
  fuser -k "$1" 2>/dev/null || true
  sleep 0.5
fi
