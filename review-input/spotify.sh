#!/bin/sh
set -e

CONF_PATH="${INSTALL_DIR}/librespot.conf"
DEVICE_NAME="${1:-Yandex-Station-Spotify}"
ALSA_DEVICE="default"

echo "=== 1. Очистка старой установки на колонке ==="
adb shell "rm -rf '${INSTALL_DIR}'"
adb shell "mkdir -p '${INSTALL_DIR}' '${CACHE_DIR}'"

echo "=== 2. Проверка наличия librespot ==="
if [ ! -f "librespot-static" ]; then
    echo "Ошибка: не удалось получить статический бинарник librespot!"
    exit 1
fi

echo "=== 3. Загрузка бинарника на колонку ==="
adb push ./librespot-static "${BIN_PATH}"
adb shell "chmod 755 '${BIN_PATH}'"
if [ -f "${CONF_PATH}" ]; then
    ALSA_DEVICE="default"
    CACHE_DIR="${INSTALL_DIR}/cache"
    INITIAL_VOLUME="70"
    VOLUME_CTRL="linear"
fi

case "$1" in
    start)
        if [ -f "${PID_FILE}" ] && kill -0 $(cat "${PID_FILE}") 2>/dev/null; then
            echo "Librespot уже запущен (PID $(cat ${PID_FILE}))."
            exit 0
        fi
        nohup "${BIN_PATH}" \
            --name "${DEVICE_NAME}" \
            --backend pipe \
            --device "aplay -q -D ${ALSA_DEVICE} -f S16_LE -c 2 -r 44100 -t raw" \
            echo "Librespot остановлен."
        $0 stop
        sleep 1
        if [ -f "${PID_FILE}" ] && kill -0 $(cat "${PID_FILE}") 2>/dev/null; then
            echo "Librespot работает (PID $(cat ${PID_FILE}))."
        else
            echo "Librespot остановлен."
        fi
        ;;
    log)
        cat "${LOG_FILE}"
        ;;
    *)
        echo "Использование: $0 {start|stop|restart|status|log}"
        exit 1
        ;;
EOF

adb push /tmp/service.sh "${SERVICE_SCRIPT}"
adb shell "chmod 755 '${SERVICE_SCRIPT}'"
rm -f /tmp/service.sh

echo "=== Установка успешно завершена! ==="
echo "script by t.me/hackalice & t.me/mmdmteam"
echo "Для запуска выполните:"
echo "  adb shell ${SERVICE_SCRIPT} start"

