#!/bin/bash
# ============================================================================
# yandex-station-privacy.sh — v2
#
# Блокировка Яндекс-телеметрии на рутованных Яндекс Станциях (Buildroot:
# Мини 2/3, Лайт и т.п. с root-доступом по ADB).
#
# Что делает:
#   1. quasar.cfg: эндпоинты телеметрии (clickdaemon: clck.yandex.net,
#      clck.yasmina.yango.com) → 127.0.0.1. Метрики никуда не уходят.
#   2. Патчит ПОСТОЯННЫЙ шаблон DNS-резолвера /bkupgrade/data/unbound.conf.head
#      (именно из него Quasar собирает /etc/unbound/unbound.conf при каждом
#      своём старте — патчить живой конфиг бесполезно, его пересоздают):
#        - local-zone refuse для доменов телеметрии;
#        - форвардеры 77.88.8.x (Яндекс-DNS: видит все домены станции)
#          заменены на Cloudflare/Google + роутер.
#   3. Ставит /etc/init.d/S100privacy — страховка после перезагрузок.
#
# Ключевые грабли, на которые наступали (вшиты в решение):
#   - q restart / загрузка Quasar пересоздаёт /etc/unbound/unbound.conf;
#   - штатный restart unbound через pidfile глючит (задвоение/зависание);
#   - heredoc в adb shell висит вечно: adb не закрывает stdin;
#   - демонизированный unbound, запущенный через adb shell без </dev/null,
#     держит pty и adb shell не возвращается.
#
# Использование:
#   ./yandex-station-privacy.sh <IP_станции>     # напр. 192.168.0.102
#   ./yandex-station-privacy.sh                  # одно устройство в adb devices
#   ./yandex-station-privacy.sh --revert <IP>    # откат из бэкапов
#
# Бэкапы: /bkupgrade/data/privacy-backup/ (переживает перезагрузку и OTA)
# ============================================================================

set -euo pipefail

C_R='\033[0;31m'; C_G='\033[0;32m'; C_Y='\033[0;33m'; C_N='\033[0m'
ok()   { echo -e "${C_G}[+]${C_N} $1"; }
warn() { echo -e "${C_Y}[!]${C_N} $1"; }
die()  { echo -e "${C_R}[x]${C_N} $1"; exit 1; }

HEAD_FILE=/bkupgrade/data/unbound.conf.head
BK=/bkupgrade/data/privacy-backup
LOCAL_ZONES='	local-zone: "clck.yandex.net." refuse
	local-zone: "clck.yasmina.yango.com." refuse'
FORWARDERS='	forward-addr: "1.1.1.1"
	forward-addr: "8.8.8.8"'

MODE="apply"; STATION_IP="${STATION_IP:-}"
[ "${1:-}" = "--revert" ] && { MODE="revert"; shift; }
[ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ] && { sed -n '2,38p' "$0"; exit 0; }
[ -n "${1:-}" ] && STATION_IP="$1"

# ---------- Подключение ----------
command -v adb >/dev/null || die "adb не найден. Установи: brew install android-platform-tools"
if [ -n "$STATION_IP" ]; then
    ADB_TARGET="${STATION_IP%%:*}:5555"
    adb connect "$ADB_TARGET" >/dev/null 2>&1 || true
elif [ "$(adb devices | grep -c 'device$')" -gt 1 ]; then
    die "В adb несколько устройств — укажи IP станции: $0 <IP>"
else
    ADB_TARGET=$(adb devices | grep 'device$' | head -1 | awk '{print $1}')
    [ -n "$ADB_TARGET" ] || die "Нет устройства: подключи станцию по ADB (adb connect IP:5555) или передай IP"
fi
adb -s "$ADB_TARGET" get-state >/dev/null 2>&1 || die "Устройство $ADB_TARGET недоступно"
# adb shell на станциях не передаёт код выхода команды (всегда 0),
# поэтому код добываем сами: дописываем на устройство `; echo __RC=$?`.
OK() {
    local out rc
    out=$(adb -s "$ADB_TARGET" shell "$@; echo __RC=\$?" | tr -d '\r')
    rc=$(printf '%s\n' "$out" | tail -1 | sed 's/^__RC=//')
    printf '%s\n' "$out" | sed '$d'
    return "$rc" 2>/dev/null || return 1
}

MODEL=$(OK hostname 2>/dev/null | tr -d '\r' || echo "unknown")
echo "— Станция: ${MODEL} (${ADB_TARGET})"

# ---------- Рестарт unbound: только так, никак иначе ----------
restart_unbound() {
    OK "killall -9 unbound 2>/dev/null; rm -f /var/run/unbound.pid; /usr/sbin/unbound </dev/null >/dev/null 2>&1"
    sleep 2
}

# ---------- Откат ----------
do_revert() {
    OK "test -f $BK/quasar.cfg.bak" || die "Бэкап не найден, откатывать нечего"
    OK "cp $BK/quasar.cfg.bak /system/vendor/quasar/quasar.cfg"
    ok "quasar.cfg восстановлен"
    if OK "test -f $BK/unbound.conf.head.bak"; then
        OK "cp $BK/unbound.conf.head.bak $HEAD_FILE"
        OK "cat $HEAD_FILE > /etc/unbound/unbound.conf && echo '	forward-addr: \"192.168.0.1\"' >> /etc/unbound/unbound.conf"
        restart_unbound
        ok "unbound.conf.head восстановлен, unbound перезапущен"
    fi
    OK "command -v q >/dev/null 2>&1 && q restart" || true
    echo "Готово. Станция в исходном состоянии."
    exit 0
}
[ "$MODE" = "revert" ] && do_revert

# ============================================================================
# Шаг 1. Телеметрия: clickdaemon-эндпоинты в quasar.cfg → 127.0.0.1
# ============================================================================
if OK "test -f /system/vendor/quasar/quasar.cfg"; then
    if OK "grep -q 'clck' /system/vendor/quasar/quasar.cfg"; then
        OK "mkdir -p $BK"
        OK "cp /system/vendor/quasar/quasar.cfg $BK/quasar.cfg.bak"
        N=$(OK "sed -i 's|clck\.yandex\.net|127.0.0.1|g; s|clck\.yasmina\.yango\.com|127.0.0.1|g' /system/vendor/quasar/quasar.cfg; grep -c '127.0.0.1' /system/vendor/quasar/quasar.cfg")
        ok "quasar.cfg: $N эндпоинтов телеметрии → 127.0.0.1 (бэкап в $BK)"
    else
        ok "quasar.cfg уже вычищен от clck-эндпоинтов"
    fi
else
    warn "quasar.cfg не найден — возможно, Android-станция. Шаг 1 пропущен."
fi

# ============================================================================
# Шаг 1б. Перезапуск Quasar с новым quasar.cfg — ДО правки DNS:
# запуск Quasar пересоздаёт /etc/unbound/unbound.conf из шаблона.
# ============================================================================
if OK "command -v q >/dev/null 2>&1" && OK "ps | grep -q '[q]uasar_launcher\|[m]aind'"; then
    echo "— Перезапускаю Quasar (Алиса перезагрузится на ~30 секунд)…"
    OK "q restart" >/dev/null 2>&1 || warn "q restart вернул ошибку — проверь вручную"
    sleep 20
    OK "ps -o pid,args | grep -q '[m]aind'" && ok "Quasar поднялся" || warn "Quasar не поднялся — глянь: adb shell ps | grep maind"
fi

# ============================================================================
# Шаг 2. DNS: патчим постоянный шаблон unbound.conf.head
# ============================================================================
if OK "command -v unbound >/dev/null 2>&1" && OK "test -f $HEAD_FILE"; then
    OK "mkdir -p $BK"
    OK "cp $HEAD_FILE $BK/unbound.conf.head.bak"

    # Новый шаблон: блокировки + не-яндексовые форвардеры (роутер добавится
    # при сборке живого конфига). Файл льём adb push — heredoc через adb виснет.
    HEAD_LOCAL=$(mktemp)
    { echo 'server:'
      echo '	msg-cache-size: 2m'
      echo '	rrset-cache-size: 2m'
      echo '	username: "nobody"'
      echo "$LOCAL_ZONES"
      echo 'forward-zone:'
      echo '	name: "."'
      echo "$FORWARDERS"
    } > "$HEAD_LOCAL"
    adb -s "$ADB_TARGET" push "$HEAD_LOCAL" $HEAD_FILE >/dev/null
    rm -f "$HEAD_LOCAL"

    # Живой конфиг = шаблон + роутер (как это делает сама станция)
    OK "cat $HEAD_FILE > /etc/unbound/unbound.conf && echo '	forward-addr: \"192.168.0.1\"' >> /etc/unbound/unbound.conf"
    if OK "/usr/sbin/unbound-checkconf /etc/unbound/unbound.conf"; then
        restart_unbound
        ok "unbound: телеметрия REFUSED, форвардеры — Cloudflare/Google/роутер"
    else
        OK "cp $BK/unbound.conf.head.bak $HEAD_FILE"
        OK "cp $BK/unbound.conf.head.bak /etc/unbound/unbound.conf"
        restart_unbound
        die "Собранный конфиг невалиден — бэкап восстановлен, отменяюсь"
    fi

    if OK "nslookup clck.yandex.net 127.0.0.1 2>&1 | grep -q REFUSED"; then
        ok "проверка: clck.yandex.net → REFUSED"
    else
        warn "clck.yandex.net не REFUSED — проверь вручную: nslookup clck.yandex.net 127.0.0.1"
    fi
else
    warn "unbound или $HEAD_FILE не найден — шаг 2 пропущен (Android-модель?)"
fi

# ============================================================================
# Шаг 3. Страховка после перезагрузки: S100privacy
# (порядок S100 — после S99quasar; шаблон уже патчен, скрипт только чинит,
#  если живой конфиг по какой-то причине без блокировок)
# ============================================================================
if OK "command -v unbound >/dev/null 2>&1"; then
    if OK "grep -q 'local-zone' /etc/init.d/S99opvk /etc/init.d/S100opvk 2>/dev/null"; then
        ok "найден OpenVK-комплект (S99/S100opvk) — страховка уже есть"
    elif OK "test -f /etc/init.d/S100privacy && grep -q 'local-zone' /etc/init.d/S100privacy"; then
        ok "S100privacy уже установлен"
    else
        INIT_LOCAL=$(mktemp)
        cat > "$INIT_LOCAL" <<'INIT'
#!/bin/sh
# Privacy-страховка unbound (см. yandex-station-privacy.sh):
# шаблон /bkupgrade/data/unbound.conf.head уже патчен, конфиг чиним
# только если блокировки из него по какой-то причине пропали.
grep -q 'local-zone' /etc/unbound/unbound.conf 2>/dev/null && exit 0
cat /bkupgrade/data/unbound.conf.head > /etc/unbound/unbound.conf 2>/dev/null && \
    echo '	forward-addr: "192.168.0.1"' >> /etc/unbound/unbound.conf
killall -9 unbound 2>/dev/null
sleep 1
/usr/sbin/unbound
INIT
        adb -s "$ADB_TARGET" push "$INIT_LOCAL" /etc/init.d/S100privacy >/dev/null
        rm -f "$INIT_LOCAL"
        OK "chmod +x /etc/init.d/S100privacy"
        ok "поставлен /etc/init.d/S100privacy — страховка после перезагрузки"
    fi
fi

echo
echo "Готово. Проверь у себя (Pi-hole/AdGuard): обращения к clck.yandex.net должны прекратиться."
echo "Откат: $0 --revert ${STATION_IP:+'<IP>'}   |   бэкапы в $BK на станции"
