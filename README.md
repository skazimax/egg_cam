# Egg camera monitor and local benchmark

Проект обнаруживает яйца на изображениях и в RTSP-потоке, отслеживает новые
появления и отправляет размеченные кадры и суточную статистику в Telegram.
Тот же код позволяет сравнивать несколько моделей на общем наборе кадров.

Основная модель рабочего монитора — `google/owlv2-base-patch16-ensemble`.

## Возможности

- детекция и координаты яиц на кадре;
- отслеживание новых и исчезнувших объектов между кадрами;
- подтверждение кандидата серией кадров;
- Telegram-уведомления с красными рамками;
- повтор неотправленных уведомлений после сетевого сбоя;
- ежедневная статистика;
- локальный benchmark с JSON, CSV, Markdown и размеченными изображениями.

## Поддерживаемые модели

- `owlv2`: основная модель монитора, OWLv2 base patch16 ensemble;
- `yolo_world`: zero-shot YOLOv8s-WorldV2;
- `grounding_dino`: Grounding DINO Tiny;
- `moondream2`: релиз `2025-06-21` с нативной детекцией;
- `qwen_mlx`: экспериментальный платформенно-зависимый адаптер Qwen2.5-VL.

Для рабочего мониторинга достаточно зависимостей из
`requirements-monitor.txt`. Дополнительные benchmark-модели устанавливаются
отдельно и для работы OWLv2 не нужны.

## Требования

- Python 3.11 или 3.12;
- доступ к интернету при первой загрузке модели;
- свободное место для виртуального окружения и кэша модели;
- сетевой доступ к RTSP-камере для потокового режима.

OWLv2 может работать на CPU. Совместимый аппаратный ускоритель уменьшает время
обработки, но не обязателен.

## Production-развёртывание на Ubuntu

Полная инструкция по установке на чистый сервер, настройке `systemd`, проверке
после перезагрузки, каталогам данных и диагностике находится в
[`DEPLOYMENT.md`](DEPLOYMENT.md).

Инструкция поддерживает три схемы:

- прямой доступ сервера к RTSP-камере и Telegram;
- опциональный SSTP и статический маршрут до удалённой сети камеры;
- опциональный AdGuard VPN в локальном SOCKS-режиме только для Telegram.

SSTP и прокси не обязательны: при прямой сетевой доступности достаточно
установить базовый `egg-cam.service`.

## Установка

Перейдите в каталог проекта и создайте изолированное окружение:

```bash
cd /path/to/egg_cam
python3 -m venv .venv
```

### Активация виртуального окружения

Виртуальное окружение нужно активировать в каждом новом терминале перед
установкой пакетов или запуском проекта. После активации команды `python` и
`pip` будут использовать интерпретатор и пакеты из `.venv`.

Для Bash или Zsh:

```bash
source .venv/bin/activate
```

Для Fish:

```fish
source .venv/bin/activate.fish
```

Для Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Для Windows CMD:

```bat
.venv\Scripts\activate.bat
```

После успешной активации в начале приглашения терминала обычно появляется
`(.venv)`. Проверить используемый интерпретатор можно командой:

```bash
python -c "import sys; print(sys.executable)"
```

Путь в выводе должен вести в каталог `.venv`. Все последующие команды в этом
README предполагают, что окружение активировано.

Чтобы выйти из виртуального окружения, выполните:

```bash
deactivate
```

Активация необязательна, если вы явно вызываете интерпретатор окружения:
`.venv/bin/python` в POSIX-системах или `.venv\Scripts\python.exe` в Windows.

Обновите `pip`:

```bash
python -m pip install --upgrade pip
```

### Установка на CPU

Сначала установите CPU-сборку PyTorch, затем остальные зависимости. Такой
порядок не позволяет `pip` случайно загрузить ненужный комплект CUDA:

```bash
python -m pip install torch torchvision \
  --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements-monitor.txt
```

### Установка с аппаратным ускорителем

Сначала установите подходящие `torch` и `torchvision` для доступного ускорителя,
затем установите зависимости проекта:

```bash
python -m pip install -r requirements-monitor.txt
```

Проверьте окружение:

```bash
python -m pip check
python -c "import torch; print('torch:', torch.__version__); print('CUDA:', torch.cuda.is_available())"
```

При `device: auto` код выбирает доступный ускоритель, иначе использует CPU.
Устройство можно явно задать в конфигурации.

## Конфигурация OWLv2

Создайте локальный `config.yaml` на основе `config.example.yaml`. Файл
`config.yaml` исключён из Git.

Минимальная рабочая конфигурация:

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
    device: auto

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

Для машины без рабочего GPU можно явно указать `device: cpu`.

`max_box_area_ratio` задаёт максимальную площадь рамки как долю площади всего
кадра: `0.002` означает `0,2%`. Более крупные рамки отбрасываются до подсчёта и
трекинга. Значения `null` и `0` отключают фильтр. Параметр поддерживается всеми
адаптерами моделей, но в примере включён только для основной модели OWLv2.

Модель загружается при первом запуске. Переменная `HF_HOME=.model_cache`
сохраняет веса внутри каталога проекта; `.model_cache` исключён из Git.

## Секреты и переменные окружения

Создайте локальный файл `.env`:

```bash
CAMERA_RTSP_URL='rtsp://USER:PASSWORD@CAMERA_IP:554/Streaming/Channels/101'
TELEGRAM_BOT_TOKEN='123456:telegram-token'
TELEGRAM_CHAT_ID='@channel_name'
```

Для приватного Telegram-канала `TELEGRAM_CHAT_ID` обычно имеет вид `-100...`.
Бота нужно добавить в канал с правом публикации сообщений.

Ограничьте доступ к файлу:

```bash
chmod 600 .env
```

`.env` уже исключён из Git. Не помещайте токены и пароль камеры в
`config.yaml`, аргументы командной строки или историю оболочки.

Перед запуском в POSIX-совместимой оболочке загрузите переменные:

```bash
set -a
source .env
set +a
```

В PowerShell переменные можно задать для текущей сессии через
`$env:CAMERA_RTSP_URL`, `$env:TELEGRAM_BOT_TOKEN` и `$env:TELEGRAM_CHAT_ID`.

## Проверка установки

Запустите тесты:

```bash
python -m unittest discover -s tests -v
```

Проверьте OWLv2 на одном контрольном изображении:

```bash
HF_HOME=.model_cache python -m egg_benchmark.cli run \
  --config config.yaml \
  --input data/input/coop_sample.png \
  --models owlv2
```

Результат будет записан в `outputs/<timestamp>/`.

## Локальный replay без камеры и Telegram

Replay проверяет модель, трекер и хранилище на сохранённых изображениях:

```bash
HF_HOME=.model_cache python -m egg_benchmark.cli monitor \
  --config config.yaml \
  --input data/input \
  --dry-run \
  --state-dir runtime/replay
```

## Тест Telegram с размеченным кадром

После загрузки переменных из `.env` выполните:

```bash
HF_HOME=.model_cache python -m egg_benchmark.cli telegram-test \
  --config config.yaml \
  --image data/input/coop_sample.png \
  --output runtime/telegram-test.jpg \
  --caption 'Тест egg_cam: размеченный кадр' \
  --detect
```

Флаг `--detect` запускает модель из секции `monitor`, рисует рамки и отправляет
результат. Без этого флага команда отправляет исходное изображение.

## Проверка RTSP-камеры

Короткий тест без публикации в Telegram:

```bash
HF_HOME=.model_cache python -m egg_benchmark.cli monitor \
  --config config.yaml \
  --dry-run \
  --interval 10 \
  --max-frames 3 \
  --state-dir runtime/camera-test
```

Полный ограниченный тест камеры, трекера и Telegram:

```bash
HF_HOME=.model_cache python -m egg_benchmark.cli monitor \
  --config config.yaml \
  --interval 10 \
  --max-frames 3 \
  --state-dir runtime/camera-full-test
```

На свежем `state-dir` после часа `report_hour` монитор может отправить суточный
отчёт, даже если новых яиц на тестовых кадрах нет.

## Рабочий мониторинг

Запуск без ограничения числа кадров:

```bash
HF_HOME=.model_cache python -m egg_benchmark.cli monitor \
  --config config.yaml \
  --interval 300 \
  --state-dir runtime/production
```

Интервал относится к обычному опросу камеры. После появления кандидата монитор
делает быструю серию подтверждающих кадров с параметрами
`confirmation_burst_frames` и `confirmation_interval_seconds`.

Первые `warmup_frames` кадров задают исходное состояние: уже лежащие яйца не
записываются как новые. Далее монитор считает рост максимального числа яиц в
текущей сессии. Например, после последовательности `2 → 0 → 2 → 5` будут
записаны только первые 2 и затем ещё 3 яйца; временное перекрытие яиц курицей не
приведёт к повторному учёту.

Автоматический сброс сессии включается после того, как её максимум виден на
`collection_arm_checks` обычных проверках. Затем гнездо должно быть подтверждено
пустым `collection_confirm_checks` обычных проверок подряд. Подтверждающая
быстрая серия в эти счётчики не входит. При интервале 300 секунд значения `3` и
`6` означают: максимум подтверждается примерно 15 минут, пустое состояние —
около 30 минут. Состояние сессии сохраняется между перезапусками.

Если подстилка или освещение изменились и эталон не подтверждает пустой кадр,
работает резервное условие: `collection_fallback_checks` обычных кадров подряд
без яиц и без курицы в зоне гнёзд. При интервале 300 секунд значение `12`
закрывает зависшую сессию примерно через час. Появление яйца или курицы обнуляет
резервный счётчик.

Пустой кадр засчитывается только при выполнении всех условий:

- детектор не видит яиц;
- детектор не видит курицу, перекрывающую одну из зон `nest_zones`;
- зона гнёзд похожа хотя бы на один эталон из `empty_reference_dir` с
  коэффициентом не ниже `empty_reference_min_similarity`.

Координаты зон нормализованы к диапазону `0..1`, поэтому не зависят от
разрешения камеры. Курицы вне этих зон не блокируют сброс. Детекции из
`occlusion_classes` не входят в число яиц и не рисуются на фотографиях событий.
Если каталог эталонов настроен, но отсутствует или пуст, быстрый сброс по
эталону блокируется, но резервный сброс остаётся доступен.

Для эталонов создайте каталог и скопируйте туда 3–5 кадров, на которых все
гнёзда хорошо видны, в них нет ни яиц, ни куриц:

```bash
mkdir -p runtime/production/empty_reference
cp /path/to/verified-empty-*.jpg runtime/production/empty_reference/
```

Состояние хранится в `runtime/production/events.sqlite3`, кадры событий — в
`runtime/production/events/`. Неотправленные уведомления повторяются в следующем
цикле. После `report_hour` один раз в сутки отправляется статистика за вчера,
сегодня, текущую неделю и месяц.

Параметр `annotation_label_mode` управляет подписями около рамок: `none` убирает
их полностью, `index` оставляет только номер, `full` выводит номер, класс и
уверенность модели. Для Telegram рекомендуется `none` вместе с тонкой рамкой
`annotation_line_width: 2`, чтобы разметка не перекрывала яйцо.

## Сохранение кадров без мониторинга

```bash
python -m egg_benchmark.cli capture --count 10 --interval 300
```

Для быстрой проверки используйте меньший интервал, например 10 секунд.

## Benchmark нескольких моделей

После установки зависимостей выбранных адаптеров:

```bash
python -m egg_benchmark.cli run \
  --config config.yaml \
  --input data/input \
  --models yolo_world,grounding_dino,owlv2,moondream2
```

Ручная разметка находится в `data/ground_truth.csv`. Итоговый отчёт содержит
точность полного совпадения количества и среднюю абсолютную ошибку.

Zero-shot результаты следует проверять на размеченном наборе кадров. Главные
рабочие показатели — пропуски, ложные обнаружения и стабильность на соседних
кадрах. Сохранённые результаты приведены в `BENCHMARK_RESULTS.md`.
