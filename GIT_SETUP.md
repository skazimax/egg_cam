# Перенос через Git

Эта папка подготовлена для отдельного Git-репозитория. В неё включены исходники,
тесты, документация и контрольные изображения из `data/input`. Виртуальные
окружения, кэши моделей, веса, результаты запусков, runtime-состояние и секреты
не включены.

## Создание репозитория на Mac

```bash
cd /Users/admin/Documents/BCS/ai/egg_detection_benchmark_git
git init
git add .
git commit -m "Initial egg detection monitor"
git branch -M main
git remote add origin YOUR_GIT_REPOSITORY_URL
git push -u origin main
```

Перед `git commit` можно проверить состав:

```bash
git status
git status --short --ignored
```

Файлы с `TELEGRAM_BOT_TOKEN`, `CAMERA_RTSP_URL` и паролями камеры добавлять в
репозиторий нельзя. На Ubuntu их следует задавать переменными окружения.

## Получение на Ubuntu

```bash
git clone YOUR_GIT_REPOSITORY_URL ~/egg_detection_benchmark
cd ~/egg_detection_benchmark

sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-monitor.txt
```

Проверка на сохранённых изображениях:

```bash
HF_HOME=.model_cache \
.venv/bin/python -m egg_benchmark.cli monitor \
  --input data/input \
  --dry-run \
  --state-dir runtime/ubuntu-test
```
