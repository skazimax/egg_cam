# Local egg detection benchmark

Для публикации этой подготовленной копии в отдельном репозитории см.
`GIT_SETUP.md`.

Локальный стенд сравнивает модели на одинаковых кадрах и сохраняет:

- число найденных яиц;
- координаты и уверенность;
- время обработки;
- исходный ответ VLM;
- изображения с рамками;
- сводные JSON, CSV и Markdown.

## Модели

- `qwen_mlx`: экспериментальная `Qwen2.5-VL-3B-Instruct` в 4-bit MLX для Apple Silicon;
- `yolo_world`: zero-shot `YOLOv8s-WorldV2`;
- `grounding_dino`: `Grounding DINO Tiny`.
- `owlv2`: `OWLv2 base patch16 ensemble`;
- `moondream2`: закреплённый релиз `2025-06-21` с нативной детекцией.

DeepSeek-VL2-Tiny пока не включён: официальный runtime ориентирован на CUDA,
а его CPU/MLX-порты менее воспроизводимы. Его имеет смысл добавить после
получения базовых результатов.

## Установка на Apple Silicon

Детекторы и Qwen нужно держать в разных окружениях: Moondream2 требует
`transformers==4.52.4`, а актуальный `mlx-vlm` требует `transformers>=5.14`.

```bash
cd /Users/admin/Documents/GIT/egg_cam
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-detectors.txt

python3 -m venv .venv-qwen
.venv-qwen/bin/python -m pip install -r requirements-qwen.txt
```

Модели загружаются при первом запуске и сохраняются в кэше Hugging Face.

## Перенос на Ubuntu

Не переносите `.venv`: виртуальные окружения содержат платформенные бинарные
файлы и должны создаваться заново на целевой машине. Каталоги `.model_cache`,
`outputs` и `runtime` тоже можно не копировать. Для монитора нужна только OWLv2;
MLX/Qwen на Ubuntu не используется.

С macOS проект можно передать по SSH:

```bash
rsync -av \
  --exclude '.venv*' \
  --exclude '.model_cache' \
  --exclude 'outputs' \
  --exclude 'runtime' \
  --exclude 'weights' \
  --exclude 'yolov8s-worldv2.pt' \
  /Users/admin/Documents/GIT/egg_cam/ \
  USER@UBUNTU_HOST:~/egg_detection_benchmark/
```

На Ubuntu рекомендуется Python 3.11 или 3.12:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg

cd ~/egg_detection_benchmark
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-monitor.txt
```

При `device: auto` выбирается NVIDIA CUDA, затем Apple MPS, иначе CPU. Проверка:

```bash
.venv/bin/python -c "import torch; print('CUDA:', torch.cuda.is_available())"
```

Если на ноутбуке есть NVIDIA GPU, команду установки PyTorch для его версии CUDA
лучше взять в официальном селекторе PyTorch, а затем установить остальные
зависимости. Без совместимой видеокарты OWLv2 будет работать на CPU, но медленнее.

После установки сначала выполните локальный replay:

```bash
HF_HOME=.model_cache \
.venv/bin/python -m egg_benchmark.cli monitor \
  --input data/input --dry-run \
  --state-dir runtime/ubuntu-test
```

Затем задайте `CAMERA_RTSP_URL`, `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID` так же,
как в разделе ниже. Ubuntu-ноутбук должен находиться в сети, из которой доступен
IP камеры и TCP-порт RTSP (обычно 554).

## Один кадр или каталог

```bash
.venv/bin/python -m egg_benchmark.cli run \
  --input data/input \
  --models yolo_world,grounding_dino,owlv2,moondream2
```

Можно запускать модели отдельно:

```bash
.venv-qwen/bin/python -m egg_benchmark.cli run --input data/input --models qwen_mlx
.venv/bin/python -m egg_benchmark.cli run --input data/input --models owlv2
```

Результат появится в `outputs/<timestamp>/`.

Ручные контрольные значения находятся в `data/ground_truth.csv`. Их можно
исправлять или дополнять; отчёт автоматически посчитает точность полного
совпадения количества и среднюю абсолютную ошибку.

## Получение кадров по RTSP

RTSP лучше задавать переменной окружения, чтобы пароль не оказался в истории:

```bash
export CAMERA_RTSP_URL='rtsp://USER:PASSWORD@CAMERA_IP:554/Streaming/Channels/101'
.venv/bin/python -m egg_benchmark.cli capture --count 10 --interval 300
```

Для быстрого теста можно использовать интервал 10 секунд. Для реального сбора —
300 секунд.

## Мониторинг и Telegram

При старте первые два кадра используются как исходное состояние: уже лежащие
яйца не записываются как новые. При обнаружении нового кандидата сервис делает
burst из трёх кадров: исходный кадр, повтор через 5 секунд и ещё один контрольный
кадр через 5 секунд. Если яйцо присутствует на первом повторе, уведомление уходит
примерно через 5 секунд. После регистрации оно не считается повторно, пока не
исчезнет из кадра.

Сначала проверьте полный pipeline на локальных изображениях без Telegram:

```bash
HF_HOME=.model_cache \
.venv/bin/python -m egg_benchmark.cli monitor \
  --input data/input \
  --dry-run \
  --state-dir runtime/replay
```

Для Telegram создайте бота через BotFather, добавьте его администратором канала
с правом публикации сообщений и задайте переменные окружения. Для публичного
канала `TELEGRAM_CHAT_ID` может иметь вид `@channel_name`; для приватного обычно
используется числовой идентификатор вида `-100...`.

```bash
export CAMERA_RTSP_URL='rtsp://USER:PASSWORD@CAMERA_IP:554/Streaming/Channels/101'
export TELEGRAM_BOT_TOKEN='123456:telegram-token'
export TELEGRAM_CHAT_ID='@channel_name'

HF_HOME=.model_cache \
.venv/bin/python -m egg_benchmark.cli monitor \
  --interval 300 \
  --state-dir runtime/production
```

Для тестовой отправки одного изображения без запуска модели и камеры:

```bash
export TELEGRAM_BOT_TOKEN='123456:telegram-token'
export TELEGRAM_CHAT_ID='@channel_name'

HF_HOME=.model_cache \
.venv/bin/python -m egg_benchmark.cli telegram-test \
  --image data/input/coop_sample.png \
  --caption 'Тест egg monitor: отправка работает' \
  --detect
```

С флагом `--detect` команда запускает модель из секции `monitor`, рисует красные
рамки вокруг обнаруженных яиц и отправляет размеченный кадр. RTSP-мониторинг и
учёт статистики не запускаются. Без `--detect` отправляется исходное изображение.
Переменные `export` и команду нужно выполнять в одном терминале.

В рабочем мониторинге при подтверждении нового яйца также отправляется
размеченный кадр с красной рамкой.

Состояние хранится в `runtime/production/events.sqlite3`, фотографии событий —
в `runtime/production/events/`. Неотправленные из-за сбоя Telegram фотографии
повторяются на следующем цикле. После 08:00 один раз в сутки публикуется отчёт:
за вчера, сегодня, с начала недели и с начала месяца. Час, число подтверждающих кадров
и параметры сопоставления рамок настраиваются в секции `monitor` файла
`config.example.yaml`.

Для короткой проверки камеры без публикации:

```bash
HF_HOME=.model_cache \
.venv/bin/python -m egg_benchmark.cli monitor \
  --dry-run --interval 10 --max-frames 3 \
  --state-dir runtime/camera-test
```

Интервал `--interval 300` относится только к обычному фоновому опросу. После
первого обнаружения включается быстрая серия, поэтому подтверждение и отправка
занимают примерно пять секунд. Параметры `confirmation_burst_frames` и
`confirmation_interval_seconds` находятся в секции `monitor`.

## Проверка тестов

```bash
.venv/bin/python -m unittest discover -s tests -v
```

## Интерпретация

Zero-shot результаты нельзя использовать как окончательную статистику без
проверки на наборе размеченных кадров. Главные показатели — пропуски, ложные
обнаружения за сутки и стабильность на соседних кадрах.

Текущие результаты новых кадров приведены в `BENCHMARK_RESULTS.md`.
