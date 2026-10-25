# Подсветка (LED)

Как управлять подсветкой зависит от модели:

| Модель | Как устроено | Где описано |
|---|---|---|
| Лайт | 3 RGB-зоны кольца через sysfs | ниже |
| Мини 2 | 6 RGB-зон + LED-часы через sysfs | [`contrib/ring-mini2-rainbow.sh`](https://github.com/Marker284/yandex-station-extended/blob/main/contrib/ring-mini2-rainbow.sh), [`contrib/install-rgb-alice-mini2.sh`](https://github.com/Marker284/yandex-station-extended/blob/main/contrib/install-rgb-alice-mini2.sh), [страница модели](../devices/station-mini2.md) |
| Станция 2 | панель из 88 светодиодов через framebuffer `/dev/fb0` (`89×1`) | [страница модели](../devices/station-2.md#led) |
| Мини 3 | кольцо через framebuffer `/dev/fb0` | [страница модели](../devices/station-mini3.md), [`contrib/ring.sh`](https://github.com/Marker284/yandex-station-extended/blob/main/contrib/ring.sh) |

## Станция Лайт: sysfs

Зоны — `/sys/class/leds/micro:{red,green,blue}:ring{1,2,3}`, яркость 0–255:

```sh
ls /sys/class/leds/
echo 255 > /sys/class/leds/micro:red:ring1/brightness    # зона 1 — красный
echo 0   > /sys/class/leds/micro:red:ring1/brightness    # погасить
```

## Анимации прошивки: формат `.led`

Анимации лежат в `/system/vendor/quasar/ledpatterns/*.led` (на Лайт — 33 штуки:
`alice_listening`, `alice_speaking`, `timer`, `volume`, `bluetooth_*`, `error` …).
Формат текстовый:

```text
gammacorrection          # применять гамма-коррекцию
loop                     # зациклить
1D761D  1D761D  1D761D   1000   # цвет зон ring1 ring2 ring3 и длительность кадра, мс
2D8624  2D8624  2D8624   1000
```

Подробнее — на [странице Лайт](../devices/station-lite.md#led-format).
