#!/bin/sh
# Small, allow-listed CGI API for the Station Mini 2 BusyBox httpd panel.
set -eu
PATH=/bin:/sbin:/usr/bin:/usr/sbin:/data/opt/entware/bin
export PATH
ROOT=/data/opt/mini2-web-panel

reply() {
  status=$1; shift
  printf 'Status: %s\r\n' "$status"
  printf 'Content-Type: application/json; charset=utf-8\r\n'
  printf 'Cache-Control: no-store\r\n'
  printf 'X-Content-Type-Options: nosniff\r\n\r\n'
  printf '%s\n' "$*"
  exit 0
}

param() {
  wanted=$1
  value=
  old_ifs=$IFS
  IFS='&'
  set -f
  # Query values are parsed as inert words; they are never evaluated as shell code.
  set -- ${QUERY_STRING:-}
  set +f
  IFS=$old_ifs
  for part do
    case "$part" in
      "$wanted"=*) value=${part#*=}; break ;;
    esac
  done
  if [ -n "$value" ]; then
    value=$(busybox httpd -d "$value" 2>/dev/null || printf '%s' "$value")
  fi
  printf '%s' "$value"
}

json_string() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g; s/\r//g; s/\n/ /g'
}

ACTION=$(param action)
METHOD=${REQUEST_METHOD:-GET}

case "$ACTION" in
  token)
    [ "$METHOD" = GET ] || reply '405 Method Not Allowed' '{"error":"Use GET"}'
    token=$(cat "$ROOT/csrf-token" 2>/dev/null || true)
    [ -n "$token" ] || reply '503 Service Unavailable' '{"error":"CSRF key is missing"}'
    reply '200 OK' "{\"csrf\":\"$token\"}"
    ;;
  status)
    [ "$METHOD" = GET ] || reply '405 Method Not Allowed' '{"error":"Use GET"}'
    if [ -r /proc/device-tree/model ]; then
      model=$(tr -d '\000\r\n' </proc/device-tree/model 2>/dev/null || echo 'unknown')
    else
      model=unknown
    fi
    uptime=$(cut -d. -f1 /proc/uptime 2>/dev/null || echo 0)
    total_kb=$(awk '/^MemTotal:/ {print $2; exit}' /proc/meminfo 2>/dev/null || echo 0)
    avail_kb=$(awk '/^MemAvailable:/ {print $2; exit}' /proc/meminfo 2>/dev/null || echo 0)
    if [ "${avail_kb:-0}" -eq 0 ] 2>/dev/null; then
      avail_kb=$(awk '/^(MemFree|Buffers|Cached):/ {sum += $2} END {print sum+0}' /proc/meminfo 2>/dev/null || echo 0)
    fi
    used_mb=$(( (total_kb - avail_kb) / 1024 ))
    total_mb=$((total_kb / 1024))
    volume=$(amixer sget Master 2>/dev/null | sed -n 's/.*\[\([0-9][0-9]*\)%\].*/\1/p' | head -n 1 || true)
    case "$volume" in ''|*[!0-9]*) volume=null ;; *) [ "$volume" -le 100 ] || volume=100 ;; esac
    quasar=0
    if ps | grep -q '[m]aind --'; then quasar=1; fi
    model_json=$(json_string "$model")
    reply '200 OK' "{\"model\":\"$model_json\",\"uptime\":${uptime:-0},\"mem_used\":$used_mb,\"mem_total\":$total_mb,\"volume\":$volume,\"quasar\":$quasar}"
    ;;
  volume)
    [ "$METHOD" = POST ] || reply '405 Method Not Allowed' '{"error":"Use POST"}'
    token=$(cat "$ROOT/csrf-token" 2>/dev/null || true)
    [ -n "$token" ] && [ "${HTTP_X_PANEL_CSRF:-}" = "$token" ] || reply '403 Forbidden' '{"error":"CSRF check failed; reload the panel"}'
    value=$(param value)
    case "$value" in ''|*[!0-9]*) reply '400 Bad Request' '{"error":"Volume must be 0..100"}' ;; esac
    [ "$value" -ge 0 ] && [ "$value" -le 100 ] || reply '400 Bad Request' '{"error":"Volume must be 0..100"}'
    amixer set Master "${value}%" >/dev/null 2>&1 || reply '503 Service Unavailable' '{"error":"amixer Master control is unavailable"}'
    reply '200 OK' "{\"ok\":true,\"volume\":$value}"
    ;;
  led)
    [ "$METHOD" = POST ] || reply '405 Method Not Allowed' '{"error":"Use POST"}'
    token=$(cat "$ROOT/csrf-token" 2>/dev/null || true)
    [ -n "$token" ] && [ "${HTTP_X_PANEL_CSRF:-}" = "$token" ] || reply '403 Forbidden' '{"error":"CSRF check failed; reload the panel"}'
    zone=$(param zone); red=$(param r); green=$(param g); blue=$(param b)
    case "$zone" in 1|2|3|4|5|6) ;; *) reply '400 Bad Request' '{"error":"Zone must be 1..6"}' ;; esac
    for channel in "$red" "$green" "$blue"; do
      case "$channel" in ''|*[!0-9]*) reply '400 Bad Request' '{"error":"RGB values must be 0..255"}' ;; esac
      [ "$channel" -le 255 ] || reply '400 Bad Request' '{"error":"RGB values must be 0..255"}'
    done
    led=/sys/class/leds/mini2
    for color in red green blue; do printf 'none\n' > "$led:$color:ring$zone/trigger" 2>/dev/null || true; done
    printf '%s\n' "$red" > "$led:red:ring$zone/brightness" 2>/dev/null || reply '503 Service Unavailable' '{"error":"Mini 2 LED sysfs nodes are unavailable"}'
    printf '%s\n' "$green" > "$led:green:ring$zone/brightness" 2>/dev/null || reply '503 Service Unavailable' '{"error":"Mini 2 LED sysfs nodes are unavailable"}'
    printf '%s\n' "$blue" > "$led:blue:ring$zone/brightness" 2>/dev/null || reply '503 Service Unavailable' '{"error":"Mini 2 LED sysfs nodes are unavailable"}'
    reply '200 OK' '{"ok":true}'
    ;;
  led-clear)
    [ "$METHOD" = POST ] || reply '405 Method Not Allowed' '{"error":"Use POST"}'
    token=$(cat "$ROOT/csrf-token" 2>/dev/null || true)
    [ -n "$token" ] && [ "${HTTP_X_PANEL_CSRF:-}" = "$token" ] || reply '403 Forbidden' '{"error":"CSRF check failed; reload the panel"}'
    led=/sys/class/leds/mini2
    for zone in 1 2 3 4 5 6; do
      for color in red green blue; do
        printf 'none\n' > "$led:$color:ring$zone/trigger" 2>/dev/null || true
        printf '0\n' > "$led:$color:ring$zone/brightness" 2>/dev/null || reply '503 Service Unavailable' '{"error":"Mini 2 LED sysfs nodes are unavailable"}'
      done
    done
    reply '200 OK' '{"ok":true}'
    ;;
  *) reply '404 Not Found' '{"error":"Unknown action"}' ;;
esac
