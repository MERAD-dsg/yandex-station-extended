#!/bin/sh
set -eu
SERVICE=/etc/init.d/S99zwebpanel
ROOT=/data/opt/mini2-web-panel

[ "$(id -u)" = 0 ] || { echo "Run as root." >&2; exit 1; }
if [ -x "$SERVICE" ]; then "$SERVICE" stop || true; fi
if [ -f "$SERVICE" ]; then
  mount -o remount,rw /
  rm -f "$SERVICE"
  sync
  mount -o remount,ro /
  echo "Removed $SERVICE; panel files/password remain in $ROOT."
else
  echo "Service is already removed. Panel files/password remain in $ROOT."
fi
