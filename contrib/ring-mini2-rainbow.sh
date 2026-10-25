#!/bin/sh
# Animate the six RGB ring zones on a rooted Yandex Station Mini 2.
# Run on the station as root; Ctrl+C stops the animation.
set -eu

LED=/sys/class/leds/mini2
DELAY=${DELAY:-0.20}

[ "$(id -u)" = 0 ] || {
  echo "Run this script as root (SSH root@station)." >&2
  exit 1
}

for zone in 1 2 3 4 5 6; do
  for color in red green blue; do
    path="$LED:$color:ring$zone/brightness"
    [ -w "$path" ] || {
      echo "LED channel not writable: $path" >&2
      exit 1
    }
    # Disable a kernel LED trigger so it does not overwrite our brightness values.
    printf 'none\n' > "$LED:$color:ring$zone/trigger"
  done
done

set_zone() {
  zone=$1
  red=$2
  green=$3
  blue=$4
  printf '%s\n' "$red"   > "$LED:red:ring$zone/brightness"
  printf '%s\n' "$green" > "$LED:green:ring$zone/brightness"
  printf '%s\n' "$blue"  > "$LED:blue:ring$zone/brightness"
}

# Nine colors form a smooth-ish spectrum; the offset moves it around the ring.
set_color() {
  case "$1" in
    0) set_zone "$zone" 255 0   0   ;; # red
    1) set_zone "$zone" 255 96  0   ;; # orange
    2) set_zone "$zone" 255 255 0   ;; # yellow
    3) set_zone "$zone" 0   255 0   ;; # green
    4) set_zone "$zone" 0   255 255 ;; # cyan
    5) set_zone "$zone" 0   0   255 ;; # blue
    6) set_zone "$zone" 96  0   255 ;; # violet
    7) set_zone "$zone" 255 0   255 ;; # magenta
    8) set_zone "$zone" 255 0   96  ;; # pink
  esac
}

step=0
while :; do
  zone=1
  while [ "$zone" -le 6 ]; do
    color_index=$(( (step + zone - 1) % 9 ))
    set_color "$color_index"
    zone=$((zone + 1))
  done
  step=$(( (step + 1) % 9 ))
  sleep "$DELAY"
done
