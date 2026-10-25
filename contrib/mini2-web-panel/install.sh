#!/bin/sh
# Run this on the Station after copying this directory to /data/opt/mini2-web-panel.
set -eu
ROOT=/data/opt/mini2-web-panel
BB=/bin/busybox
SERVICE=/etc/init.d/S99zwebpanel

[ "$(id -u)" = 0 ] || { echo "Run as root." >&2; exit 1; }
[ -x "$BB" ] || { echo "BusyBox not found at $BB" >&2; exit 1; }
"$BB" --list | grep -qx httpd || {
  echo "This firmware's BusyBox has no httpd applet; nothing was installed." >&2
  exit 1
}
[ -f "$ROOT/www/index.html" ] && [ -x "$ROOT/www/cgi-bin/api.cgi" ] || {
  echo "Panel files are incomplete at $ROOT" >&2
  exit 1
}

if [ ! -s "$ROOT/httpd.conf" ]; then
  printf 'Set a panel password (at least 10 characters): '
  stty -echo
  IFS= read -r password || true
  stty echo
  printf '\n'
  [ "${#password}" -ge 10 ] || { echo "Password too short." >&2; exit 1; }
  printf 'Repeat password: '
  stty -echo
  IFS= read -r password2 || true
  stty echo
  printf '\n'
  [ "$password" = "$password2" ] || { echo "Passwords do not match." >&2; exit 1; }
  hash=$("$BB" httpd -m "$password" | tr -d '\r\n')
  unset password password2
  case "$hash" in \$1\$*) ;; *) echo "BusyBox could not hash the password." >&2; exit 1 ;; esac
  umask 077
  printf '/:admin:%s\n' "$hash" > "$ROOT/httpd.conf"
  chmod 600 "$ROOT/httpd.conf"
fi

if [ ! -s "$ROOT/csrf-token" ]; then
  cat /proc/sys/kernel/random/uuid | tr -d '-\r\n' > "$ROOT/csrf-token"
  chmod 600 "$ROOT/csrf-token"
fi
chmod 755 "$ROOT/www/cgi-bin/api.cgi"

mount -o remount,rw /
rootfs_rw=1
restore_rootfs() {
  if [ "$rootfs_rw" = 1 ]; then mount -o remount,ro / || true; fi
}
trap restore_rootfs 0 1 2 3 15

if [ -f "$SERVICE" ]; then
  cp -p "$SERVICE" "$ROOT/S99zwebpanel.backup.$(date +%Y%m%d-%H%M%S)"
fi
cat > "$SERVICE" <<'SERVICE_EOF'
#!/bin/sh
ROOT=/data/opt/mini2-web-panel
PID=/var/run/mini2-webpanel.pid
LOG=$ROOT/httpd.log
start() {
  [ -x /bin/busybox ] || return 1
  [ -s "$ROOT/httpd.conf" ] || { echo "No panel password config" >> "$LOG"; return 1; }
  if [ -s "$PID" ]; then
    old=$(cat "$PID")
    case "$old" in *[!0-9]*|"") old="" ;; esac
    if [ -n "$old" ] && kill -0 "$old" 2>/dev/null; then return 0; fi
  fi
  /bin/busybox httpd -f -p 0.0.0.0:80 -h "$ROOT/www" -c "$ROOT/httpd.conf" -r "Station Mini 2 panel" >> "$LOG" 2>&1 </dev/null &
  echo $! > "$PID"
  sleep 1
  p=$(cat "$PID")
  if ! kill -0 "$p" 2>/dev/null; then
    rm -f "$PID"
    echo "httpd failed to start; check port 80 and $LOG" >> "$LOG"
    return 1
  fi
}
stop() {
  if [ -s "$PID" ]; then
    p=$(cat "$PID")
    case "$p" in *[!0-9]*|"") p="" ;; esac
    [ -z "$p" ] || kill "$p" 2>/dev/null || true
    rm -f "$PID"
  fi
}
case "$1" in
  start) start ;;
  stop) stop ;;
  restart) stop; sleep 1; start ;;
  status) if [ -s "$PID" ] && kill -0 "$(cat "$PID")" 2>/dev/null; then echo running; else echo stopped; exit 1; fi ;;
  *) echo "Usage: $0 {start|stop|restart|status}"; exit 2 ;;
esac
SERVICE_EOF
chmod 755 "$SERVICE"
sync
mount -o remount,ro /
rootfs_rw=0
trap - 0 1 2 3 15

"$SERVICE" start
printf 'Installed. Open http://<station-ip>/ and sign in as admin.\n'
printf 'Service: %s {status|restart|stop}\n' "$SERVICE"
printf 'Uninstall: sh %s/uninstall.sh\n' "$ROOT"
