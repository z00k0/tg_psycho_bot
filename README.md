# Telegram бот психологического словаря

Бот ищет определения по точному совпадению, затем через SQLite FTS5 trigram и,
если результатов нет, предлагает до трёх вариантов RapidFuzz. Telegram работает
только через webhook. Среда и зависимости управляются Poetry.

## Локальная разработка

Требуются Python 3.14 и Poetry 2.x. На Windows установленную версию Python можно
найти командой `py list`.

```powershell
poetry config virtualenvs.in-project true --local
poetry env use (py -3.14 -c "import sys; print(sys.executable)")
poetry sync
poetry run pytest
poetry run python -m app.main --help
```

Перед запуском задайте в окружении значения из `.env.example`. Минимальный пример
PowerShell (URL должен быть доступен Telegram):

```powershell
$env:BOT_TOKEN='123456:token-from-botfather'
$env:BASE_WEBHOOK_URL='https://bot.example.com'
$env:WEBHOOK_PATH='/webhook'
$env:WEBHOOK_SECRET='replace-with-random-secret'
```

Для webhook нужен публичный HTTPS URL; локальный адрес без HTTPS конфигурация
намеренно отклоняет. Остальные параметры имеют документированные значения по
умолчанию в `.env.example`.

Импорт подготовленного словаря в SQLite:

```powershell
poetry run tg-psyco import-dictionary psychological_dictionary.json --database data/dictionary.sqlite3
```

Команда сначала полностью проверяет JSON, затем атомарно пересоздаёт содержимое
словаря и проверяет синхронность FTS5-индекса. Повторный запуск безопасен.

Локальный запуск webhook-сервера после настройки переменных окружения:

```powershell
poetry run tg-psyco serve
```

Сервер предоставляет `/healthz` и `/readyz`. Удаление webhook выполняется только
явной административной командой:

```powershell
poetry run tg-psyco delete-webhook
```

При startup бот проверяет FTS5 trigram, открывает и проверяет словарь, прогревает
fuzzy-индекс и регистрирует `${BASE_WEBHOOK_URL}${WEBHOOK_PATH}` через Telegram
`setWebhook`. Обычная остановка webhook не удаляет.

## Проверка качества и готовности релиза

Полная локальная проверка:

```powershell
poetry check --lock
poetry run ruff check app tests
poetry run pytest -q
$env:BOT_DOMAIN='bot.example.test'
docker compose config --quiet
docker build --target runtime --tag tg-psyco-bot:local .
docker run --rm `
  -e BOT_TOKEN='123456:release-check-token' `
  -e BASE_WEBHOOK_URL='https://bot.example.test' `
  -e WEBHOOK_SECRET='release_check-secret' `
  tg-psyco-bot:local tg-psyco check
```

Тестовые значения последней команды не выполняют сетевых запросов: `check` проверяет
только конфигурацию и SQLite. В Compose настоящие secrets подключаются автоматически.
Release готов, когда проверки Poetry/Ruff/Pytest, Compose config, сборка image и
контейнерный FTS5 probe завершены успешно.

Приложение пишет JSON-логи в stderr. Для поиска фиксируются только стратегия,
длительность, длина нормализованного запроса и число результатов. Исходный текст
сообщения не логируется; bot token и webhook secret редактируются фильтром.

Архитектура и порядок реализации описаны в `BOT_IMPLEMENTATION_PLAN.md`.

## Production через Docker Compose

Основной `docker-compose.yaml` рассчитан на уже установленный на Linux-хосте Nginx.
Он запускает только `bot` и публикует aiohttp как `127.0.0.1:8080`: порт доступен
Nginx на хосте, но не доступен напрямую извне. Если Nginx сам работает в контейнере,
его нужно подключить к Compose-сети проекта вместо использования loopback.

Подготовка конфигурации и secrets:

```bash
cp .env.example .env
# В .env задайте BOT_DOMAIN и при необходимости измените BOT_BIND_PORT.
mkdir -p secrets
printf '%s' '123456:telegram-token' > secrets/bot_token
printf '%s' 'replace-with-random-secret' > secrets/webhook_secret
chmod 600 secrets/bot_token secrets/webhook_secret
```

Перед запуском создайте бота через BotFather, направьте A/AAAA-запись `BOT_DOMAIN`
на сервер и настройте сертификат в существующем Nginx. Не добавляйте файлы из
`secrets/` и `.env` в систему контроля версий.

Пример фрагмента существующего HTTPS `server` в Nginx:

```nginx
location = /webhook {
    proxy_pass http://127.0.0.1:8080;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_connect_timeout 5s;
    proxy_read_timeout 30s;
}

location = /healthz {
    proxy_pass http://127.0.0.1:8080;
}

location = /readyz {
    proxy_pass http://127.0.0.1:8080;
}
```

Если `WEBHOOK_PATH` в `.env` отличается от `/webhook`, измените соответствующий
`location`. После правки проверьте и перечитайте конфигурацию:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Первичная сборка, проверка FTS5 и импорт словаря в named volume:

```bash
docker compose config --quiet
docker compose build --pull
docker compose run --rm --no-deps bot tg-psyco check
docker compose run --rm --no-deps bot \
  tg-psyco import-dictionary \
  /app/psychological_dictionary.json \
  --database /data/dictionary.sqlite3
docker compose up -d bot
docker compose ps
docker compose logs --tail=100 bot
set -a; . ./.env; set +a
curl "http://127.0.0.1:${BOT_BIND_PORT:-8080}/readyz"
curl "https://${BOT_DOMAIN}/healthz"
curl "https://${BOT_DOMAIN}/readyz"
```

Ожидаемый результат: `bot` имеет статус `healthy`, локальный endpoint и оба HTTPS
endpoint через Nginx возвращают HTTP 200. Если bot не становится ready, проверьте
логи, наличие импортированной базы и содержимое secret-файлов.

Импорт нужно выполнить до первого старта бота: команда запускает одноразовый
контейнер на основе сервиса `bot`, записывает базу в тот же named volume и удаляет
контейнер после завершения. Отдельный постоянно работающий сервис для этого не
создаётся. Fuzzy-индекс строится в памяти при запуске бота.

Для обновления словаря остановите бот, пересоберите image, повторите атомарный
импорт и снова запустите бот:

```bash
docker compose stop bot
docker compose build --pull
docker compose run --rm --no-deps bot \
  tg-psyco import-dictionary \
  /app/psychological_dictionary.json \
  --database /data/dictionary.sqlite3
docker compose up -d bot
```

Контейнер бота работает от UID/GID 10001, с read-only root filesystem. SQLite,
включая `dictionary.sqlite3-wal` и `dictionary.sqlite3-shm`, хранится только в
named volume `tg-psyco_dictionary_data`. Запуск нескольких реплик bot с этим
volume не поддерживается.

### Опциональный запуск с Caddy

Для отдельного сервера без Nginx предусмотрен `docker-compose.caddy.yaml`. Это
override-файл: он не запускается самостоятельно, а объединяется с основным Compose.
Caddy публикует 80/443 и автоматически управляет TLS-сертификатом.

```bash
docker compose \
  -f docker-compose.yaml \
  -f docker-compose.caddy.yaml \
  config --quiet
docker compose \
  -f docker-compose.yaml \
  -f docker-compose.caddy.yaml \
  up -d bot caddy
docker compose \
  -f docker-compose.yaml \
  -f docker-compose.caddy.yaml \
  ps
```

Не запускайте этот вариант, если существующий Nginx уже занимает порты 80/443.
Для импорта, backup и административных команд достаточно основного Compose-файла.

### Резервное копирование и восстановление

Самый простой согласованный backup выполняется при остановленном боте. Команда
архивирует весь volume, включая возможные WAL/SHM-файлы:

```bash
mkdir -p backups
docker compose stop bot
docker run --rm \
  -v tg-psyco_dictionary_data:/source:ro \
  -v "$(pwd)/backups:/backup" \
  alpine:3.22 \
  tar -czf /backup/tg-psyco-data.tar.gz -C /source .
docker compose start bot
```

Восстановление заменяет содержимое отдельного data volume, поэтому выполняется
только при остановленном боте и после дополнительной копии текущих данных:

```bash
docker compose stop bot
docker run --rm \
  -v tg-psyco_dictionary_data:/target \
  -v "$(pwd)/backups:/backup:ro" \
  alpine:3.22 \
  sh -c 'find /target -mindepth 1 -maxdepth 1 -delete && tar -xzf /backup/tg-psyco-data.tar.gz -C /target'
docker compose start bot
```

Штатная остановка с 30-секундным grace period:

```bash
docker compose stop
```

Удаление webhook не выполняется при shutdown. При необходимости используйте
явную команду:

```bash
docker compose run --rm --no-deps bot tg-psyco delete-webhook
```
