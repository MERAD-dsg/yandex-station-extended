#!/bin/sh
PIDFILE=/var/run/rgb_effect.pid
STATEFILE=/tmp/rgb_state
BACKUP_STATEFILE=/bkupgrade/data/opt/rgb_state
# Диоды: micro:{red,green,blue}:ring{1,2,3}  (3 кольца x 3 цвета = 9 диодов)
D=/sys/class/leds/micro
RINGS="1 2 3"

save_state() {
    echo "$*" > "$STATEFILE" 2>/dev/null
    echo "$*" > "$BACKUP_STATEFILE" 2>/dev/null
}

get_state() {
    if [ -f "$STATEFILE" ]; then
        cat "$STATEFILE" 2>/dev/null
    elif [ -f "$BACKUP_STATEFILE" ]; then
        cat "$BACKUP_STATEFILE" 2>/dev/null
    fi
}

# set_ring <n> <r> <g> <b>
set_ring() {
    echo "$2" > ${D}:red:ring${1}/brightness 2>/dev/null
    echo "$3" > ${D}:green:ring${1}/brightness 2>/dev/null
    echo "$4" > ${D}:blue:ring${1}/brightness 2>/dev/null
}

# set_all <r> <g> <b>
set_all() {
    for i in $RINGS; do
        set_ring "$i" "$1" "$2" "$3"
    done
}

stop_effect() {
    if [ -f "$PIDFILE" ]; then
        kill -9 $(cat "$PIDFILE") 2>/dev/null
    fi
    start-stop-daemon --stop -p "$PIDFILE" 2>/dev/null
    for p in $(ps | grep rgb_loop | grep -v grep | awk '{print $1}'); do
        kill -9 "$p" 2>/dev/null
    done
    rm -f "$PIDFILE" /tmp/rgb_loop.sh 2>/dev/null
    set_all 0 0 0
}

set_static() {
    stop_effect
    r=${1:-255}; g=${2:-255}; b=${3:-255}
    save_state static "$r" "$g" "$b"
    set_all "$r" "$g" "$b"
}

run_rainbow() {
    stop_effect
    delay=${1:-0.1}
    save_state rainbow "$delay"
    cat << 'EOF' > /tmp/rgb_loop.sh
#!/bin/sh
D=/sys/class/leds/micro
delay=$1

set_c() {
    r=$1; g=$2; b=$3
    for i in 1 2 3; do
        echo $r > ${D}:red:ring${i}/brightness 2>/dev/null
        echo $g > ${D}:green:ring${i}/brightness 2>/dev/null
        echo $b > ${D}:blue:ring${i}/brightness 2>/dev/null
    done
}

while true; do
    set_c 255 0 0; sleep $delay
    set_c 255 60 0; sleep $delay
    set_c 255 140 0; sleep $delay
    set_c 255 220 0; sleep $delay
    set_c 180 255 0; sleep $delay
    set_c 60 255 0; sleep $delay
    set_c 0 255 0; sleep $delay
    set_c 0 255 80; sleep $delay
    set_c 0 255 200; sleep $delay
    set_c 0 200 255; sleep $delay
    set_c 0 80 255; sleep $delay
    set_c 0 0 255; sleep $delay
    set_c 80 0 255; sleep $delay
    set_c 180 0 255; sleep $delay
    set_c 255 0 200; sleep $delay
    set_c 255 0 80; sleep $delay
done
EOF
    chmod 755 /tmp/rgb_loop.sh
    start-stop-daemon --start -b -m -p "$PIDFILE" -x /bin/sh -- /tmp/rgb_loop.sh "$delay"
}

run_breathe() {
    stop_effect
    r=${1:-180}; g=${2:-0}; b=${3:-255}
    delay=${4:-0.04}
    save_state breathe "$r" "$g" "$b" "$delay"
    cat << EOF > /tmp/rgb_loop.sh
#!/bin/sh
D=/sys/class/leds/micro
delay=\$1
R=$r; G=$g; B=$b
STEPS="10 18 28 42 60 82 110 145 185 225 255 225 185 145 110 82 60 42 28 18 10"
while true; do
    for val in \$STEPS; do
        rr=\$(( R * val / 255 )); gg=\$(( G * val / 255 )); bb=\$(( B * val / 255 ))
        for i in 1 2 3; do
            echo \$rr > \${D}:red:ring\${i}/brightness 2>/dev/null
            echo \$gg > \${D}:green:ring\${i}/brightness 2>/dev/null
            echo \$bb > \${D}:blue:ring\${i}/brightness 2>/dev/null
        done
        sleep \$delay
    done
done
EOF
    chmod 755 /tmp/rgb_loop.sh
    start-stop-daemon --start -b -m -p "$PIDFILE" -x /bin/sh -- /tmp/rgb_loop.sh "$delay"
}

run_spin() {
    stop_effect
    delay=${1:-0.08}
    save_state spin "$delay"
    cat << 'EOF' > /tmp/rgb_loop.sh
#!/bin/sh
D=/sys/class/leds/micro
delay=$1

set_led() {
    idx=$1; r=$2; g=$3; b=$4
    echo $r > ${D}:red:ring${idx}/brightness 2>/dev/null
    echo $g > ${D}:green:ring${idx}/brightness 2>/dev/null
    echo $b > ${D}:blue:ring${idx}/brightness 2>/dev/null
}

while true; do
    set_led 1 255 0 0; set_led 3 100 0 180; set_led 2 0 0 0
    sleep $delay
    set_led 2 255 140 0; set_led 1 150 0 0; set_led 3 0 0 0
    sleep $delay
    set_led 3 0 255 0; set_led 2 150 80 0; set_led 1 0 0 0
    sleep $delay
done
EOF
    chmod 755 /tmp/rgb_loop.sh
    start-stop-daemon --start -b -m -p "$PIDFILE" -x /bin/sh -- /tmp/rgb_loop.sh "$delay"
}

run_spin_color() {
    stop_effect
    r=${1:-0}; g=${2:-255}; b=${3:-255}
    delay=${4:-0.08}
    save_state spin_color "$r" "$g" "$b" "$delay"
    cat << EOF > /tmp/rgb_loop.sh
#!/bin/sh
D=/sys/class/leds/micro
delay=$delay

set_led() {
    idx=\$1; scale=\$2
    echo \$(( $r * scale / 100 )) > \${D}:red:ring\${idx}/brightness 2>/dev/null
    echo \$(( $g * scale / 100 )) > \${D}:green:ring\${idx}/brightness 2>/dev/null
    echo \$(( $b * scale / 100 )) > \${D}:blue:ring\${idx}/brightness 2>/dev/null
}

while true; do
    set_led 1 100; set_led 3 35; set_led 2 0; sleep \$delay
    set_led 2 100; set_led 1 35; set_led 3 0; sleep \$delay
    set_led 3 100; set_led 2 35; set_led 1 0; sleep \$delay
done
EOF
    chmod 755 /tmp/rgb_loop.sh
    start-stop-daemon --start -b -m -p "$PIDFILE" -x /bin/sh -- /tmp/rgb_loop.sh "$delay"
}

run_police() {
    stop_effect
    delay=${1:-0.08}
    save_state police "$delay"
    cat << 'EOF' > /tmp/rgb_loop.sh
#!/bin/sh
D=/sys/class/leds/micro
delay=$1
# красная "половина": кольца 1,2 / синяя "половина": кольца 3,2 (среднее кольцо участвует в обеих)
while true; do
    for k in 1 2 3; do
        for i in 1 2; do echo 255 > ${D}:red:ring${i}/brightness; echo 0 > ${D}:blue:ring${i}/brightness; echo 0 > ${D}:green:ring${i}/brightness; done
        for i in 3; do echo 0 > ${D}:red:ring${i}/brightness; echo 0 > ${D}:blue:ring${i}/brightness; echo 0 > ${D}:green:ring${i}/brightness; done
        sleep $delay
        for i in 1 2; do echo 0 > ${D}:red:ring${i}/brightness; done
        sleep 0.04
    done
    for k in 1 2 3; do
        for i in 3 2; do echo 0 > ${D}:red:ring${i}/brightness; echo 255 > ${D}:blue:ring${i}/brightness; echo 0 > ${D}:green:ring${i}/brightness; done
        for i in 1; do echo 0 > ${D}:red:ring${i}/brightness; echo 0 > ${D}:blue:ring${i}/brightness; echo 0 > ${D}:green:ring${i}/brightness; done
        sleep $delay
        for i in 3 2; do echo 0 > ${D}:blue:ring${i}/brightness; done
        sleep 0.04
    done
done
EOF
    chmod 755 /tmp/rgb_loop.sh
    start-stop-daemon --start -b -m -p "$PIDFILE" -x /bin/sh -- /tmp/rgb_loop.sh "$delay"
}

run_strobe() {
    stop_effect
    delay=${1:-0.05}
    save_state strobe "$delay"
    cat << 'EOF' > /tmp/rgb_loop.sh
#!/bin/sh
D=/sys/class/leds/micro
delay=$1
while true; do
    for i in 1 2 3; do
        echo 255 > ${D}:red:ring${i}/brightness 2>/dev/null
        echo 255 > ${D}:green:ring${i}/brightness 2>/dev/null
        echo 255 > ${D}:blue:ring${i}/brightness 2>/dev/null
    done
    sleep $delay
    for i in 1 2 3; do
        echo 0 > ${D}:red:ring${i}/brightness 2>/dev/null
        echo 0 > ${D}:green:ring${i}/brightness 2>/dev/null
        echo 0 > ${D}:blue:ring${i}/brightness 2>/dev/null
    done
    sleep $delay
done
EOF
    chmod 755 /tmp/rgb_loop.sh
    start-stop-daemon --start -b -m -p "$PIDFILE" -x /bin/sh -- /tmp/rgb_loop.sh "$delay"
}

run_notify() {
    PREV=$(get_state)

    # Stop current animation without wiping the saved state
    if [ -f "$PIDFILE" ]; then
        kill -9 $(cat "$PIDFILE") 2>/dev/null
    fi
    for p in $(ps | grep rgb_loop | grep -v grep | awk '{print $1}'); do
        kill -9 "$p" 2>/dev/null
    done
    rm -f "$PIDFILE" /tmp/rgb_loop.sh 2>/dev/null

    # Play notification sound
    if [ -f /bkupgrade/data/opt/sounds/telegram.wav ]; then
        aplay -q /bkupgrade/data/opt/sounds/telegram.wav 2>/dev/null &
    elif [ -f /bkupgrade/data/opt/telegram.wav ]; then
        aplay -q /bkupgrade/data/opt/telegram.wav 2>/dev/null &
    fi

    for k in 1 2 3 4 5; do
        set_all 0 255 0
        usleep 120000
        set_all 0 0 0
        usleep 80000
    done
    set_all 0 0 0

    # RESTORE PREVIOUS STATE AUTOMATICALLY
    if [ -n "$PREV" ] && [ "$PREV" != "stop" ]; then
        set -- $PREV
        prev_cmd="$1"
        shift
        case "$prev_cmd" in
            static) set_static "$@" ;;
            rainbow) run_rainbow "$@" ;;
            breathe) run_breathe "$@" ;;
            spin) run_spin "$@" ;;
            spin_color) run_spin_color "$@" ;;
            police) run_police "$@" ;;
            strobe) run_strobe "$@" ;;
        esac
    fi
}

case "$1" in
    stop) stop_effect; save_state stop ;;
    static) set_static "$2" "$3" "$4" ;;
    rainbow) run_rainbow "$2" ;;
    breathe) run_breathe "$2" "$3" "$4" "$5" ;;
    spin) run_spin "$2" ;;
    spin_color) run_spin_color "$2" "$3" "$4" "$5" ;;
    police) run_police "$2" ;;
    strobe) run_strobe "$2" ;;
    notify) run_notify ;;
    restore)
        PREV=$(get_state)
        if [ -n "$PREV" ] && [ "$PREV" != "stop" ]; then
            set -- $PREV
            prev_cmd="$1"
            shift
            case "$prev_cmd" in
                static) set_static "$@" ;;
                rainbow) run_rainbow "$@" ;;
                breathe) run_breathe "$@" ;;
                spin) run_spin "$@" ;;
                spin_color) run_spin_color "$@" ;;
                police) run_police "$@" ;;
                strobe) run_strobe "$@" ;;
            esac
        fi
        ;;
    *) echo "Usage: $0 {stop|static r g b|rainbow [speed]|breathe r g b [speed]|spin [speed]|spin_color r g b [speed]|police [speed]|strobe [speed]|notify|restore}" ;;
esac
