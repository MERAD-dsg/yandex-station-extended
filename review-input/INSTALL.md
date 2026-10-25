# Midi Kit — Spotify, AirPlay и подсветка для Яндекс Станции Миди

Что получится после установки:

- **Spotify Connect** на колонке — официальный клиент Spotify Soloist. Колонка видна в приложении Spotify как обычная колонка.
- **AirPlay** — с iPhone, iPad или Мака колонка видна как **HomePod**.
- **Анимации** на кольце, логотипе и часах, пока играет музыка: 64 узора × 18 палитр, симуляции и режимы под бас. На часах бежит название трека.
- **Голосовое управление без «Алиса»**: «дальше», «назад», «пауза», «стоп», «играй». Тройное «хватит» перезагружает колонку.
- **Веб-пульт** на `http://<IP колонки>:8088/` — плеер и выбор анимаций с телефона.
- **Красивое приветствие** при входе по ssh.
- По желанию — **свой звук при включении** с радугой на кольце.

---

## Что нужно

1. **Яндекс Станция Миди с root-доступом по ssh.** Если `ssh root@<IP колонки>` у тебя не работает, этот набор не поможет: как получить root, здесь не описано. Проверено на прошивке `0.7.1.15…factory-7`. Если колонка обновит прошивку, root обычно пропадает.
2. **Компьютер с macOS или Linux** в той же сети. На Windows — через WSL. Нужны `ssh`, `python3`, `ar` и `objdump`:
   - macOS: `xcode-select --install`
   - Debian/Ubuntu: `sudo apt install openssh-client python3 binutils`
3. **Spotify Premium** — нужен только для получения ключа Soloist. Подключаться к колонке потом можно и с бесплатного аккаунта.
4. **В России — SOCKS5-прокси** до сервера за границей. Spotify не пускает российские IP-адреса, без прокси вход не пройдёт (`session_access_denied`). Подробнее — в шаге 1.
5. Около **300 МБ** свободного места на колонке и 5–10 минут.

---

## Шаг 1. Ключ Soloist и прокси

**Ключ.** Открой https://developer.spotify.com/dashboard/soloist, войди своим Premium-аккаунтом и сгенерируй ключ. Он начинается с **`spak_`**. Если кнопка не работает или пишет, что нужен Premium, сначала создай любое приложение в https://developer.spotify.com/dashboard, потом вернись. Client ID и Client Secret обычного приложения не подойдут.

Ключ личный, никому его не отправляй.

**Прокси (если ты в России).** Нужен адрес вида `socks5h://IP:порт`, до которого колонка достаёт по локальной сети. Варианты:

- На роутере уже есть VPN с SOCKS5 — бери его адрес.
- Есть домашний сервер или Raspberry Pi с VPN-клиентом (Happ, xray, v2ray, sing-box), который слушает SOCKS только на `127.0.0.1:10808`. Тогда открой его для колонки через systemd. Файл `/etc/systemd/system/station-spotify-proxy.socket`:

  ```ini
  [Socket]
  ListenStream=IP_СЕРВЕРА:10818
  FreeBind=true
  IPAddressDeny=any
  IPAddressAllow=IP_КОЛОНКИ 127.0.0.0/8

  [Install]
  WantedBy=sockets.target
  ```

  и `/etc/systemd/system/station-spotify-proxy.service`:

  ```ini
  [Service]
  ExecStart=/usr/lib/systemd/systemd-socket-proxyd 127.0.0.1:10808
  DynamicUser=yes
  ```

  Затем `sudo systemctl daemon-reload && sudo systemctl enable --now station-spotify-proxy.socket`. Прокси для колонки: `socks5h://IP_СЕРВЕРА:10818`.

Если ты не в России, прокси не нужен — на вопрос установщика ответь `none`.

---

## Шаг 2. Вход на колонку по ssh-ключу

Установщик заходит на колонку много раз, поэтому нужен вход по ключу без пароля. Проверка:

```bash
ssh -o BatchMode=yes root@IP_КОЛОНКИ true && echo ок
```

Если не «ок», добавь свой ключ. Корневая файловая система колонки только для чтения, поэтому её нужно на минуту открыть на запись:

```bash
cat ~/.ssh/id_ed25519.pub | ssh root@IP_КОЛОНКИ 'mount -o remount,rw / && mkdir -p /root/.ssh && cat >> /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys; mount -o remount,ro /'
```

Если ключа нет, сначала создай его: `ssh-keygen -t ed25519`.

---

## Шаг 3. Установка

Распакуй архив и запусти установщик:

```bash
unzip midi-kit.zip
cd midi-kit
sh install.sh
```

Он спросит:

- адрес колонки — например `root@192.168.1.50`;
- ключ Soloist — при вводе его не видно;
- прокси — `socks5h://…` или `none`.

То же самое можно передать сразу, без вопросов:

```bash
MIDI_HOST=root@192.168.1.50 SOLOIST_API_KEY=spak_... SOLOIST_PROXY=socks5h://192.168.1.10:10818 sh install.sh
```

Дополнительно:

- `DEVICE_NAME="Кухня"` — имя колонки в Spotify.
- `CHIME_WAV=/путь/к/звуку.wav` — свой звук при включении (WAV, 16 бит). Чтобы сделать WAV из MP3 на Маке: `afconvert -f WAVE -d LEI16@44100 -c 2 звук.mp3 звук.wav`.

Сначала установщик проверит компьютер и колонку. Первый запуск скачает Spotify Soloist (с серверов Spotify) и около 50 пакетов Debian — это несколько минут. Колонку установщик сам не перезагружает.

---

## Шаг 4. Пользуйся

- **Spotify:** в приложении Spotify открой список устройств и выбери «Yandex Station Midi Spotify». Первый раз — обязательно с того же аккаунта, что и ключ. Дальше колонка помнит вход и после перезагрузки.
- **AirPlay:** на iPhone — Пункт управления → значок AirPlay → «HomePod». На Маке — в меню звука. Если играет Spotify, он встанет на паузу. И наоборот: включишь Spotify — AirPlay отключится.
- **Голос** (без «Алиса»):

  | Скажи | Что будет |
  |---|---|
  | дальше / следующий | следующий трек |
  | назад | предыдущий трек |
  | пауза / стоп / хватит | пауза |
  | играй / продолжи | играть (даже если колонка не выбрана в Spotify) |
  | хватит ×3 подряд | перезагрузка колонки |

  Громкость — как обычно у Алисы: «громче», «тише». После перезагрузки громкость начинает слушаться минуты через 2–3.
- **Веб-пульт:** `http://IP_КОЛОНКИ:8088/` — плеер, громкость, выбор узора, палитры и анимации часов, фиксация анимации. Пароля нет, пульт доступен всем в твоей Wi-Fi сети.
- **SSH:** `ssh root@IP_КОЛОНКИ` покажет приветствие со статусом.

---

## Если что-то не так

| Что видишь | Что делать |
|---|---|
| В логе `login failed: make sure --api-key is valid` | Ключ не `spak_…`, или прокси не работает (в России). Проверь, что прокси доступен с колонки. |
| `CURL error: 77` | Не те сертификаты — переустанови: `sh install.sh`. |
| Spotify не виден в приложении | Телефон и колонка должны быть в одной сети. Подожди минуту после включения. |
| AirPlay есть, звука нет | Перезапусти: `ssh root@IP_КОЛОНКИ /data/local/spotify/service.sh restart`. |
| Алиса молчит и не отвечает | Это старая прошивка, а не набор: голосовой модуль Алисы падает при ответе. На Spotify и AirPlay не влияет. |
| После перезагрузки Spotify не поднялся | Подожди 2 минуты: Soloist ждёт сеть и сам перезапускается, если прокси ещё не готов. |

Полезные команды на колонке:

```bash
/data/local/spotify/service.sh status    # работает ли
/data/local/spotify/service.sh restart   # перезапустить всё
/data/local/spotify/service.sh log       # лог Spotify
cat /data/local/spotify/voice.log        # распознанные голосовые команды
cat /data/local/spotify/airplay.log      # лог AirPlay
```

**Раз в 90 дней** сборка Soloist устаревает и перестаёт запускаться. Обнови её и поставь заново:

```bash
python3 spotify/build_runtime.py --refresh
sh install.sh
```

---

## Как удалить

```bash
ssh root@IP_КОЛОНКИ '
  /data/local/spotify/service.sh stop
  mount -o remount,rw /
  rm -f /etc/init.d/S98spotify /etc/init.d/S96chime /etc/profile.d/zz-welcome.sh /etc/dbus-1/system.d/avahi-dbus.conf
  sed -i "/^avahi:/d" /etc/passwd /etc/group
  mount -o remount,ro /
  rm -rf /data/local/spotify /data/local/boot-chime /data/local/welcome
  reboot'
```
