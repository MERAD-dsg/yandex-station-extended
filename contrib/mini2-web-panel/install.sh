#!/bin/sh
# Run on the Station after copying this directory to /data/opt/mini2-web-panel.
set -eu
ROOT=/data/opt/mini2-web-panel
SERVICE=/etc/init.d/S99zwebpanel
LIGHTTPD=/opt/sbin/lighttpd
PATH=/data/opt/bin:/opt/bin:/opt/sbin:/bin:/sbin:/usr/bin:/usr/sbin
export PATH

[ "$(id -u)" = 0 ] || { echo "Run as root." >&2; exit 1; }
[ -f "$ROOT/www/index.html" ] && [ -f "$ROOT/www/cgi-bin/api.cgi" ] || {
  echo "Panel files are incomplete at $ROOT" >&2
  exit 1
}
chmod 755 "$ROOT/www/cgi-bin/api.cgi"

if [ ! -x "$LIGHTTPD" ]; then
  command -v yse >/dev/null 2>&1 || {
    echo "Install Entware/YSE first; no HTTP server is installed." >&2
    exit 1
  }
  echo "Installing lighttpd and its auth/CGI modules using yse..."
  yse install lighttpd lighttpd-mod-auth lighttpd-mod-authn_file lighttpd-mod-cgi
fi
[ -x "$LIGHTTPD" ] || {
  echo "lighttpd did not appear at $LIGHTTPD after package installation." >&2
  exit 1
}

if [ ! -s "$ROOT/users" ]; then
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
  umask 077
  printf 'admin:%s\n' "$password" > "$ROOT/users"
  unset password password2
  chmod 600 "$ROOT/users"
fi

if [ ! -s "$ROOT/csrf-token" ]; then
  cat /proc/sys/kernel/random/uuid > "$ROOT/csrf-token"
  chmod 600 "$ROOT/csrf-token"
fi
chmod 755 "$ROOT/www/cgi-bin/api.cgi"
chmod 700 "$ROOT"
cat > "$ROOT/lighttpd.conf" <<'CONF_EOF'
server.document-root = "/data/opt/mini2-web-panel/www"
server.bind = "0.0.0.0"
server.port = 80
server.pid-file = "/var/run/mini2-webpanel.pid"
server.errorlog = "/data/opt/mini2-web-panel/lighttpd-error.log"
server.modules = ( "mod_auth", "mod_authn_file", "mod_cgi" )
index-file.names = ( "index.html" )
mimetype.assign = ( ".html" => "text/html", ".cgi" => "application/json" )

# CGI runs as root because it writes ALSA/sysfs controls; only allow-listed
# actions are implemented in www/cgi-bin/api.cgi. Do not expose port 80 publicly.
auth.backend = "plain"
auth.backend.plain.userfile = "/data/opt/mini2-web-panel/users"
auth.require = ( "/" => ( "method" => "basic", "realm" => "Station Mini 2 panel", "require" => "valid-user" ) )
cgi.assign = ( ".cgi" => "" )
CONF_EOF
chmod 600 "$ROOT/lighttpd.conf"

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
LOG=$ROOT/lighttpd-error.log
BIN=/opt/sbin/lighttpd
start() {
  [ -x "$BIN" ] || { echo "lighttpd missing: $BIN" >> "$LOG"; return 1; }
  [ -s "$ROOT/users" ] && [ -s "$ROOT/lighttpd.conf" ] || { echo "panel config missing" >> "$LOG"; return 1; }
  if [ -s "$PID" ]; then
    old=$(cat "$PID")
    case "$old" in *[!0-9]*|"") old="" ;; esac
    if [ -n "$old" ] && kill -0 "$old" 2>/dev/null; then return 0; fi
  fi
  "$BIN" -D -f "$ROOT/lighttpd.conf" >> "$LOG" 2>&1 </dev/null &
  echo $! > "$PID"
  sleep 1
  p=$(cat "$PID")
  if ! kill -0 "$p" 2>/dev/null; then
    rm -f "$PID"
    echo "lighttpd failed to start; check TCP/80 and $LOG" >> "$LOG"
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
