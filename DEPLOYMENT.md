# Production-развёртывание Egg Cam на Ubuntu

Инструкция описывает установку CPU-мониторинга как `systemd`-сервиса. Базовый
вариант предполагает прямой доступ сервера к RTSP-камере и Telegram. SSTP для
доступа к удалённой сети камеры и AdGuard VPN SOCKS для Telegram подключаются
независимо и являются опциональными.

Проверенная схема:

```text
Ubuntu host
├── egg-cam-sstp.service       # опционально: маршрут к сети камеры
├── egg-cam-adguard.service    # опционально: SOCKS только для Telegram
└── egg-cam.service            # RTSP → OWLv2 → SQLite → Telegram
```

## 1. Требования

- Ubuntu 22.04/24.04 x86_64;
- Python 3.11 или 3.12;
- минимум 2 CPU;
- минимум 2 ГБ RAM и 4 ГБ swap, рекомендуется 4 ГБ RAM;
- 5–8 ГБ свободного диска;
- RTSP URL камеры;
- Telegram-бот, добавленный администратором канала.

На 2 ГБ RAM OWLv2 использует swap. Проверенный CPU-инференс занимает примерно
65–70 секунд на кадр, поэтому интервал опроса 300 секунд подходит для начальной
эксплуатации.

Примеры ниже используют:

```text
пользователь: skazimax
проект:       /home/skazimax/git/egg_cam
камера:       192.168.2.3
сеть камеры:  192.168.2.0/24
```

При развёртывании под другим пользователем замените эти значения в unit-файлах.

## 2. Подготовка Ubuntu

```bash
sudo apt update
sudo apt install -y git python3 python3-venv ffmpeg curl
```

Для машины с 2 ГБ RAM добавьте swap, если его ещё нет:

```bash
swapon --show
```

Пример создания swap-файла размером 4 ГБ:

```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

Не выполняйте повторно создание `/swapfile`, если он уже существует.

## 3. Установка проекта

```bash
mkdir -p ~/git
cd ~/git
git clone <REPOSITORY_URL> egg_cam
cd egg_cam

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install torch torchvision \
  --index-url https://download.pytorch.org/whl/cpu
.venv/bin/python -m pip install -r requirements-monitor.txt
.venv/bin/python -m pip check
```

`PySocks` входит в основные зависимости и используется только при включённом
SOCKS-прокси.

## 4. Конфигурация модели и секретов

```bash
cd ~/git/egg_cam
cp config.example.yaml config.yaml
nano config.yaml
```

Для CPU-сервера рекомендуется:

```yaml
models:
  owlv2:
    model_id: google/owlv2-base-patch16-ensemble
    classes:
      - a chicken egg
      - a white egg
      - a brown egg
    occlusion_classes:
      - a chicken
    occlusion_confidence: 0.50
    confidence: 0.30
    max_box_area_ratio: 0.002
    device: cpu

monitor:
  model: owlv2
  confirm_frames: 2
  confirmation_burst_frames: 3
  confirmation_interval_seconds: 5.0
  warmup_frames: 2
  max_missed_frames: 1
  iou_threshold: 0.20
  max_center_distance: 0.035
  collection_arm_checks: 3
  collection_confirm_checks: 6
  collection_fallback_checks: 12
  nest_zones:
    - [0.20, 0.15, 0.51, 0.76]
  nest_occlusion_min_overlap: 0.10
  empty_reference_dir: runtime/production/empty_reference
  empty_reference_min_similarity: 0.70
  annotation_label_mode: none
  annotation_line_width: 2
  report_hour: 8
```

Монитор считает только рост максимального числа яиц в текущей сессии. Сессия
автоматически сбрасывается, когда максимум был виден на трёх обычных проверках,
а затем камера шесть обычных проверок подряд видит открытые пустые гнёзда.
Курица в `nest_zones` и недостаточное сходство с эталоном не считаются пустым
кадром. При интервале 300 секунд подтверждение пустого гнезда занимает около
30 минут. Если сходство с эталоном остаётся неопределённым, 12 кадров подряд без
яиц и без курицы в зоне гнёзд выполняют резервный сброс примерно через час.
Счётчики и максимум хранятся в `runtime/production/events.sqlite3` и переживают
перезапуск сервиса.

Создайте каталог эталонов и скопируйте в него 3–5 проверенных кадров, где все
гнёзда хорошо видны и в них нет яиц и куриц:

```bash
mkdir -p ~/git/egg_cam/runtime/production/empty_reference
cp /path/to/verified-empty-*.jpg \
  ~/git/egg_cam/runtime/production/empty_reference/
```

Если настроенный каталог отсутствует или пуст, монитор безопасно блокирует
автоматический сброс сессии.

Создайте `.env`:

```bash
nano ~/git/egg_cam/.env
```

```bash
CAMERA_RTSP_URL='rtsp://USER:PASSWORD@192.168.2.3:554/Streaming/Channels/101'
TELEGRAM_BOT_TOKEN='1234567890:AA...'
TELEGRAM_CHAT_ID='@channel_name'
```

Для приватного канала `TELEGRAM_CHAT_ID` обычно имеет вид `-100...`. Символы
`@`, `:`, `/`, `#` и `%` в пароле внутри RTSP URL должны быть URL-кодированы.

```bash
chmod 600 ~/git/egg_cam/.env
```

Не добавляйте `.env`, `config.yaml` и кэш моделей в Git.

## 5. Проверка до установки сервиса

```bash
cd ~/git/egg_cam
set -a
source .env
set +a
```

Проверьте RTSP:

```bash
timeout 30 ffmpeg -hide_banner -loglevel warning \
  -rtsp_transport tcp -i "$CAMERA_RTSP_URL" \
  -ss 4 -frames:v 1 -q:v 2 -y /tmp/egg-cam-test.jpg
file /tmp/egg-cam-test.jpg
```

Задержка `-ss 4` нужна, чтобы дождаться полноценного HEVC-ключевого кадра.

Загрузите модель и выполните ограниченный dry-run:

```bash
HF_HOME=.model_cache .venv/bin/python -m egg_benchmark.cli monitor \
  --config config.yaml \
  --dry-run \
  --interval 10 \
  --max-frames 1 \
  --state-dir runtime/camera-test
```

Первый запуск загружает модель в `.model_cache` и может занять несколько минут.

## 6. Базовый systemd-сервис без VPN и прокси

Создайте `/etc/systemd/system/egg-cam.service`:

```ini
[Unit]
Description=Egg camera detection and Telegram monitor
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=skazimax
Group=skazimax
WorkingDirectory=/home/skazimax/git/egg_cam
Environment=HF_HOME=/home/skazimax/git/egg_cam/.model_cache
Environment=PYTHONUNBUFFERED=1
Environment=OMP_NUM_THREADS=2
Environment=TOKENIZERS_PARALLELISM=false
EnvironmentFile=/home/skazimax/git/egg_cam/.env
ExecStart=/home/skazimax/git/egg_cam/.venv/bin/python -m egg_benchmark.cli monitor --config /home/skazimax/git/egg_cam/config.yaml --interval 300 --state-dir /home/skazimax/git/egg_cam/runtime/production
Restart=always
RestartSec=30
TimeoutStartSec=120
TimeoutStopSec=30
Nice=10
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

Включите сервис:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now egg-cam.service
systemctl status egg-cam.service
```

Если камера доступна только через SSTP или Telegram заблокирован, сначала
настройте соответствующие опциональные разделы ниже, затем используйте
комбинированный unit из раздела 9.

## 7. Опционально: SSTP до сети камеры

### 7.1. Установка клиента

```bash
sudo apt install -y sstp-client ppp
```

Создайте защищённую конфигурацию:

```bash
mkdir -p ~/.config/egg-cam
chmod 700 ~/.config/egg-cam
nano ~/.config/egg-cam/sstp.env
```

```bash
SSTP_SERVER='vpn.example.com'
SSTP_USERNAME='username'
SSTP_PASSWORD='password'
SSTP_ROUTES='192.168.2.0/24'
```

```bash
chmod 600 ~/.config/egg-cam/sstp.env
```

### 7.2. Автоматический маршрут PPP

Создайте `/etc/ppp/ip-up.d/egg-cam-sstp`:

```sh
#!/bin/sh
set -eu

[ "${PPP_IPPARAM:-}" = "egg-cam-sstp" ] || exit 0
. /home/skazimax/.config/egg-cam/sstp.env
/usr/sbin/ip route replace "${SSTP_ROUTES:-192.168.2.0/24}" dev "$PPP_IFACE"
```

Создайте `/etc/ppp/ip-down.d/egg-cam-sstp`:

```sh
#!/bin/sh
set -eu

[ "${PPP_IPPARAM:-}" = "egg-cam-sstp" ] || exit 0
. /home/skazimax/.config/egg-cam/sstp.env
/usr/sbin/ip route del "${SSTP_ROUTES:-192.168.2.0/24}" dev "$PPP_IFACE" 2>/dev/null || true
```

```bash
sudo chmod 755 /etc/ppp/ip-up.d/egg-cam-sstp
sudo chmod 755 /etc/ppp/ip-down.d/egg-cam-sstp
```

### 7.3. SSTP unit

Создайте `/etc/systemd/system/egg-cam-sstp.service`:

```ini
[Unit]
Description=Egg Cam SSTP tunnel
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
EnvironmentFile=/home/skazimax/.config/egg-cam/sstp.env
ExecStart=/usr/sbin/sstpc --tls-ext --cert-warn --save-server-route --ipparam egg-cam-sstp --user ${SSTP_USERNAME} --password ${SSTP_PASSWORD} ${SSTP_SERVER} usepeerdns require-mschap-v2 noauth noipdefault refuse-eap noccp unit 20 ipparam egg-cam-sstp nodetach
Restart=on-failure
RestartSec=10
TimeoutStopSec=15
KillMode=mixed

[Install]
WantedBy=multi-user.target
```

`--tls-ext` включает SNI и нужен для SSTP-сервера с доменным именем.
`--cert-warn` допускает недоверенный сертификат; при наличии корректной цепочки
CA лучше использовать `--ca-cert` и убрать `--cert-warn`.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now egg-cam-sstp.service
```

Проверка:

```bash
systemctl status egg-cam-sstp.service
ip -brief address show ppp20
ip route get 192.168.2.3
ping -c 2 192.168.2.3
timeout 3 bash -c '</dev/tcp/192.168.2.3/554' && echo RTSP_OK
```

### 7.4. Маршруты на SSTP-концентраторе

На центральном роутере должен быть маршрут к удалённой LAN через VPN-адрес
роутера камеры. Например:

```text
192.168.2.0/24 → 172.16.1.2
```

На роутере камеры должен быть обратный маршрут к VPN-адресу сервера через
SSTP-интерфейс. Например:

```text
172.16.1.1/32 → SSTP_CL2
```

Межсетевые экраны обоих роутеров должны разрешать двусторонний forwarding.

## 8. Опционально: AdGuard VPN SOCKS для Telegram

Этот вариант нужен, если обычный HTTPS работает, а подключение к
`api.telegram.org:443` завершается таймаутом. SOCKS-режим направляет через VPN
только Telegram-запросы приложения и не меняет default route, SSH или SSTP.

### 8.1. Установка и вход

Официальная команда установки:

```bash
curl -fsSL https://raw.githubusercontent.com/AdguardTeam/AdGuardVPNCLI/master/scripts/release/install.sh | sh -s -- -v
```

Согласитесь создать ссылку `/usr/local/bin/adguardvpn-cli`, затем выполните:

```bash
adguardvpn-cli login
adguardvpn-cli config set-mode SOCKS
adguardvpn-cli config set-socks-host 127.0.0.1
adguardvpn-cli config set-socks-port 1080
adguardvpn-cli list-locations
```

Установка описана в официальной документации:
<https://adguard-vpn.com/kb/adguard-vpn-for-linux/installation/>.

### 8.2. AdGuard unit

Создайте `/etc/systemd/system/egg-cam-adguard.service`:

```ini
[Unit]
Description=AdGuard VPN SOCKS proxy for Egg Cam
Wants=network-online.target
After=network-online.target
Before=egg-cam.service

[Service]
Type=simple
User=skazimax
Group=skazimax
Environment=HOME=/home/skazimax
ExecStartPre=-/usr/local/bin/adguardvpn-cli disconnect
ExecStart=/usr/local/bin/adguardvpn-cli connect --location Frankfurt --yes --ipv4only --no-progress --no-fork --boot
Restart=always
RestartSec=10
TimeoutStartSec=90
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
```

Замените `Frankfurt` на город из `adguardvpn-cli list-locations`, если нужно.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now egg-cam-adguard.service
```

Проверка:

```bash
systemctl status egg-cam-adguard.service
ss -lnt | grep 127.0.0.1:1080
curl -4 --socks5-hostname 127.0.0.1:1080 \
  -o /dev/null -w 'HTTP %{http_code}\n' https://api.telegram.org
```

Ожидаемый ответ корневого URL Telegram — `HTTP 302`.

## 9. Комбинированный монитор с SSTP и AdGuard

Когда включены оба опциональных сервиса, используйте следующий
`/etc/systemd/system/egg-cam.service`:

Сначала создайте `/usr/local/sbin/egg-cam-wait-dependencies`:

```sh
#!/bin/sh
set -u

attempt=1
while [ "$attempt" -le 45 ]; do
    route_ready=false
    camera_ready=false
    telegram_ready=false

    if /usr/sbin/ip route get 192.168.2.3 2>/dev/null | /usr/bin/grep -q "dev ppp20"; then
        route_ready=true
    fi
    if /usr/bin/timeout 3 /bin/bash -c '</dev/tcp/192.168.2.3/554' 2>/dev/null; then
        camera_ready=true
    fi
    if /usr/bin/curl -4 --socks5-hostname 127.0.0.1:1080 \
        --silent --output /dev/null --connect-timeout 3 --max-time 5 \
        https://api.telegram.org; then
        telegram_ready=true
    fi

    if [ "$route_ready" = true ] && [ "$camera_ready" = true ] && [ "$telegram_ready" = true ]; then
        echo "Egg Cam dependencies are ready"
        exit 0
    fi

    echo "Waiting for dependencies: route=$route_ready camera=$camera_ready telegram=$telegram_ready"
    attempt=$((attempt + 1))
    sleep 2
done

echo "Egg Cam dependencies did not become ready" >&2
exit 1
```

```bash
sudo chmod 755 /usr/local/sbin/egg-cam-wait-dependencies
```

Затем установите комбинированный unit:

```ini
[Unit]
Description=Egg camera detection and Telegram monitor
Wants=network-online.target egg-cam-sstp.service egg-cam-adguard.service
After=network-online.target egg-cam-sstp.service egg-cam-adguard.service

[Service]
Type=simple
User=skazimax
Group=skazimax
WorkingDirectory=/home/skazimax/git/egg_cam
Environment=HF_HOME=/home/skazimax/git/egg_cam/.model_cache
Environment=PYTHONUNBUFFERED=1
Environment=OMP_NUM_THREADS=2
Environment=TOKENIZERS_PARALLELISM=false
Environment=ALL_PROXY=socks5h://127.0.0.1:1080
Environment=all_proxy=socks5h://127.0.0.1:1080
Environment=NO_PROXY=localhost,127.0.0.1,192.168.0.0/16
Environment=no_proxy=localhost,127.0.0.1,192.168.0.0/16
EnvironmentFile=/home/skazimax/git/egg_cam/.env
ExecStartPre=/usr/local/sbin/egg-cam-wait-dependencies
ExecStart=/home/skazimax/git/egg_cam/.venv/bin/python -m egg_benchmark.cli monitor --config /home/skazimax/git/egg_cam/config.yaml --interval 300 --state-dir /home/skazimax/git/egg_cam/runtime/production
Restart=always
RestartSec=30
TimeoutStartSec=120
TimeoutStopSec=30
Nice=10
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

`Wants`, а не `Requires`, позволяет монитору пережить краткий перезапуск
AdGuard или SSTP. Не используйте глобальный TUN-маршрут AdGuard на удалённом
сервере без отдельной проверки: он может изменить маршрут ответов SSH.

```bash
sudo systemctl daemon-reload
sudo systemctl enable egg-cam-sstp.service
sudo systemctl enable egg-cam-adguard.service
sudo systemctl enable --now egg-cam.service
```

## 10. Проверка после перезагрузки

```bash
sudo reboot
```

После восстановления SSH:

```bash
systemctl is-enabled egg-cam-sstp egg-cam-adguard egg-cam
systemctl is-active egg-cam-sstp egg-cam-adguard egg-cam

ip -brief address show ppp20
ip route get 192.168.2.3
ss -lnt | grep 127.0.0.1:1080
sudo journalctl -b -u egg-cam-sstp -u egg-cam-adguard -u egg-cam
```

В рабочем журнале после загрузки должны появиться строки:

```text
[owlv2] loading model...
frame=camera_... visible=... new=... latency=...s
```

## 11. Данные и обслуживание

Обычные кадры:

```text
runtime/production/frames/
```

Кадры подтверждённых событий:

```text
runtime/production/events/
```

SQLite со статистикой и состоянием:

```text
runtime/production/events.sqlite3
```

Полезные команды:

```bash
sudo systemctl status egg-cam-sstp egg-cam-adguard egg-cam
sudo journalctl -u egg-cam -f
sudo systemctl restart egg-cam
ls -lht ~/git/egg_cam/runtime/production/frames | head
free -h
swapon --show
df -h /
```

Кадры пока не удаляются автоматически. Для длительной работы настройте
ротацию или периодическую очистку после определения требуемого срока хранения.

## 12. Типовые проблемы

### RTSP возвращает `401 Unauthorized`

Проверьте логин, пароль, право Live View и канал `101`. Не передавайте RTSP URL
как аргумент командной строки: он попадёт в историю и список процессов.

### Первый кадр серый

Это неполный HEVC-кадр до первого keyframe. Рабочая функция проекта прогревает
поток около четырёх секунд. Для ручной проверки используйте `ffmpeg -ss 4`.

### Telegram работает локально, но недоступен на сервере

Сравните прямой запрос и SOCKS:

```bash
curl -4 --connect-timeout 8 https://api.telegram.org
curl -4 --socks5-hostname 127.0.0.1:1080 https://api.telegram.org
```

`401 Unauthorized` от Bot API означает неверный или отозванный токен, а
сетевой таймаут — проблему маршрута/блокировки.

### Модель завершается из-за памяти

Проверьте `journalctl -u egg-cam`, `free -h` и swap. Увеличьте RAM до 4 ГБ либо
добавьте swap. На проверенной машине пик OWLv2 составлял около 1,7 ГБ RAM.

### SSTP подключён, но камера недоступна

Проверьте по порядку:

```bash
ping -c 2 192.168.1.1   # SSTP-концентратор
ping -c 2 172.16.1.2    # VPN-адрес роутера камеры, если ICMP разрешён
ping -c 2 192.168.2.1   # LAN-интерфейс роутера камеры
ping -c 2 192.168.2.3   # камера
```

Отсутствие ответа от VPN-адреса роутера не всегда является ошибкой, если его
LAN и камера доступны. Главная проверка — маршрут к камере через `ppp20` и
открытый RTSP-порт.
