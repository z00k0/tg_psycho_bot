# Прогресс реализации Telegram бота

Обновлено: 18 сентября 2026 года.

Основной план проекта находится в `BOT_IMPLEMENTATION_PLAN.md`. Этот файл фиксирует фактически выполненную работу и точку, с которой следует продолжить реализацию.

## Текущее состояние

- Завершены все этапы 1–13 основного плана.
- Следующего этапа в `BOT_IMPLEMENTATION_PLAN.md` нет; проект готов к production
  smoke-test с реальными DNS и Telegram credentials.
- Production-образ, базовый Compose для существующего Nginx, опциональный Caddy
  override, наблюдаемость и сквозные тесты реализованы.

## Завершённые этапы

### Этап 1. Каркас проекта и Poetry

Статус: завершён.

Реализовано:

- Создан пакет `app` и каталоги `app/bot`, `app/db`, `app/search`.
- Создана тестовая структура `tests/unit`.
- Poetry настроен на локальное окружение `.venv` через `poetry.toml`.
- Используется Python 3.14.7.
- Добавлены и зафиксированы зависимости:
  - aiogram 3.31.0;
  - aiohttp 3.14.3;
  - RapidFuzz 3.14.6;
  - pytest 9.1.1;
  - pytest-asyncio 1.4.0;
  - Ruff 0.16.8.
- Созданы `pyproject.toml` и `poetry.lock`.
- Добавлен CLI `python -m app.main` и команда `tg-psyco`.
- Добавлены `.env.example`, `.gitignore`, `README.md`, `data/.gitkeep` и `secrets/.gitkeep`.
- Импорт модулей приложения не создаёт БД и не открывает сетевые соединения.

Проверка этапа:

```powershell
poetry sync
poetry check --lock
poetry run python --version
poetry run python -m app.main --help
poetry run pytest tests/unit/test_project.py -q
```

Результат: 5 тестов этапа пройдены.

### Этап 2. Конфигурация и проверка SQLite

Статус: завершён.

Реализовано в `app/config.py`:

- Типизированная immutable-конфигурация `Settings`.
- Поддержка настроек:
  - `BOT_TOKEN` и `BOT_TOKEN_FILE`;
  - `BASE_WEBHOOK_URL`;
  - `WEBHOOK_PATH`;
  - `WEBHOOK_SECRET` и `WEBHOOK_SECRET_FILE`;
  - `HOST`;
  - `PORT`;
  - `DATABASE_PATH`;
  - `SEARCH_RESULT_LIMIT`;
  - `MAX_QUERY_LENGTH`.
- Значения из файлов `*_FILE` имеют приоритет над обычными переменными окружения.
- Проверяется HTTPS webhook URL, путь webhook, диапазон порта и формат webhook secret.
- Токен и webhook secret маскируются в `repr(Settings)`.
- Ошибки конфигурации представлены контролируемым исключением `ConfigError`.

Реализовано в `app/db/capabilities.py`:

- Startup-проверка FTS5 с `tokenize='trigram'` в базе `:memory:`.
- При отсутствии требуемой возможности выбрасывается `SqliteCapabilityError`.
- Проверка не создаёт файлов на диске.

Проверенная среда:

- Python: 3.14.7.
- SQLite: 3.50.4.
- FTS5 trigram: доступен.

Проверка этапа:

```powershell
poetry run pytest tests/unit/test_config.py tests/unit/test_sqlite_capabilities.py -q

$env:BOT_TOKEN='123456:smoke-token'
$env:BASE_WEBHOOK_URL='https://bot.example.test'
$env:WEBHOOK_SECRET='smoke_secret-123'
poetry run python -m app.main check
```

Результат: тесты конфигурации и SQLite пройдены; CLI выводит подтверждение готовности FTS5 trigram.

### Этап 3. Нормализация поискового запроса

Статус: завершён.

Реализовано в `app/search/normalize.py`:

- Unicode приводится к NFC.
- Регистр приводится через `casefold()`.
- `ё` заменяется на `е`.
- Буквы и цифры сохраняются.
- Пунктуация, управляющие символы и последовательности пробелов заменяются одним пробелом.
- Пустой нормализованный запрос отклоняется через `EmptyQueryError`.
- Слишком длинный запрос отклоняется через `QueryTooLongError`.
- Некорректный тип или лимит отклоняется через `InvalidQueryError`.
- Нормализация идемпотентна.

Проверка этапа:

```powershell
poetry run pytest tests/unit/test_normalize.py -q
```

Результат: 25 тестов нормализации пройдены.

### Этап 4. Схема SQLite, миграции и FTS5-триггеры

Статус: завершён.

Реализовано в `app/db/schema.sql`:

- Основная таблица `terms` с уникальным `term_normalized` и проверкой JSON-флагов.
- Таблица `term_aliases` с внешним ключом и каскадным удалением.
- Индексы для буквы термина и нормализованного алиаса.
- External-content таблица `terms_fts` с `tokenize='trigram'`.
- Триггеры синхронизации FTS после `INSERT`, `UPDATE` и `DELETE`.
- SQL-файл включён в Poetry package data.

Реализовано в `app/db/connection.py`:

- Открытие файловой и in-memory SQLite-базы.
- `PRAGMA foreign_keys = ON`.
- WAL и `synchronous = NORMAL` для файловой БД.
- Настраиваемый `busy_timeout`.
- `sqlite3.Row` как row factory.
- Режим autocommit с явным контекстом `transaction`.
- Commit успешной транзакции и rollback при любом исключении.
- Запрет неявных вложенных транзакций.
- Контекстный менеджер, всегда закрывающий соединение.

Реализовано в `app/db/migrate.py`:

- Таблица `schema_migrations`.
- Чтение текущей версии схемы.
- Идемпотентное применение миграций.
- Проверка порядка, уникальности и содержимого миграций.
- Атомарное применение SQL-схемы и записи версии.
- Полный rollback, включая созданные таблицы, при ошибке SQL.
- Текущая версия схемы: 1.

Проверка этапа:

```powershell
poetry run pytest tests/unit/test_db_connection.py tests/unit/test_migrations.py -q
```

Результат: 22 теста этапа пройдены.

### Этап 5. Импорт JSON в SQLite

Статус: завершён.

Реализовано в `app/db/import_dictionary.py`:

- Полная проверка JSON до открытия или изменения базы: версия схемы, число записей,
  обязательные поля, типы, уникальность ID и нормализованных терминов.
- Для терминов и поисковых вариантов применяется общий нормализатор; ограничение длины
  пользовательского запроса не применяется к исходным словарным данным.
- `search_terms` разделяются на основной термин и уникальные нормализованные алиасы.
- `search_blob` строится из нормализованного термина и алиасов.
- Выполняется полная атомарная пересборка таблиц `terms` и `term_aliases`.
- Повторный импорт идемпотентен и не создаёт дубликатов.
- Ошибка SQLite приводит к rollback всей пересборки и сохраняет предыдущий словарь.
- После импорта сверяется число статей, алиасов и реальных документов FTS5, затем
  выполняется встроенная проверка целостности external-content индекса.
- Добавлены две формы CLI:
  - `poetry run tg-psyco import-dictionary ...`;
  - `poetry run tg-psyco-import ...`.

Проверка этапа:

```powershell
poetry run pytest tests/unit/test_import_dictionary.py -q
poetry run pytest tests/integration/test_real_dictionary_import.py -q
poetry run tg-psyco-import --help
```

Результат:

- минимальная фикстура, повторный импорт, ошибки валидации и rollback проверены;
- импортируются `redirect_to`, `quality_flags` и несколько алиасов;
- все **558 статей** реального JSON импортированы;
- все ID, термины и определения в SQLite совпадают с JSON;
- пустых определений и потерянных записей FTS нет.

### Этап 6. Репозиторий и точный поиск

Статус: завершён.

Реализовано в `app/search/models.py`:

- Immutable-доменная модель `DictionaryArticle`, не зависящая от SQLite, aiogram
  или Telegram API.
- Модель содержит ID, исходный и нормализованный термин, заголовок, определение,
  перенаправление, букву и флаги качества.

Реализовано в `app/db/repository.py`:

- `DictionaryRepository`, принимающий существующее SQLite-соединение без передачи
  владения им репозиторию.
- Получение статьи по стабильному числовому ID через `get_by_id`.
- Точный поиск через `find_exact`: сначала основная таблица `terms`, затем
  `term_aliases` с переходом к основной статье.
- Детерминированный выбор статьи по минимальному ID при неоднозначном алиасе.
- Все пользовательские значения передаются в SQLite только как связанные параметры.
- Результат преобразуется в `DictionaryArticle`, отсутствие записи — в `None`.

Проверка этапа:

```powershell
poetry run pytest tests/unit/test_repository.py -q
```

Результат: 12 тестов этапа пройдены. Проверены основной термин, алиас, приоритет
основного термина, получение по ID, отсутствие результата, варианты регистра,
`ё/е`, пробелов и пунктуации, а также SQL-подобный ввод.

### Этап 7. FTS5 substring/trigram поиск

Статус: завершён.

Реализовано в `app/search/fts_query.py`:

- Builder литерального FTS5-выражения, заключающий запрос в двойные кавычки.
- Вложенные кавычки экранируются удвоением по синтаксису FTS5.
- `OR`, `NOT`, `*`, скобки и дефисы не интерпретируются как операторы поиска.
- Пустой запрос и неверный тип отклоняются контролируемой ошибкой `FtsQueryError`.

Реализовано в `DictionaryRepository.search_fts`:

- Подстрочный поиск через external-content таблицу `terms_fts` с trigram tokenizer.
- FTS-выражение и лимит передаются в SQLite как связанные параметры.
- Совпадения в `term_normalized` и `search_blob` получают безусловный приоритет над
  совпадениями только в заголовке или определении.
- Внутри приоритетной группы используется взвешенный `bm25`: основной термин и
  `search_blob` имеют больший вес.
- При одинаковом ранге результат стабилизируется по нормализованному термину и ID.
- Нормализованные запросы длиной меньше трёх символов возвращают пустой список без
  выполнения SQL к FTS-таблице.
- Пустой результат представлен пустым списком, количество статей ограничивается
  положительным целочисленным параметром `limit`.

Проверка этапа:

```powershell
poetry run pytest tests/unit/test_fts_query.py -q
```

Результат: 32 теста этапа пройдены. Проверены подстроки в начале, середине и конце,
регистр, `ё/е`, фразы из нескольких слов, алиасы в `search_blob`, специальные символы,
пропуск коротких запросов, приоритет термина над определением, лимит и стабильный порядок.

### Этап 8. RapidFuzz fallback

Статус: завершён.

Реализовано в `app/search/models.py`:

- Immutable-модель `FuzzyChoice` для одного нормализованного термина или алиаса.
- Immutable-модель `FuzzySuggestion` с ID статьи, отображаемым термином и оценкой,
  предназначенной только для диагностики.

Реализовано в `DictionaryRepository.load_fuzzy_choices`:

- Основные термины и все алиасы загружаются одним SQL-запросом.
- Результат возвращается как неизменяемый `tuple` в стабильном порядке: ID статьи,
  основной термин, затем алиасы по алфавиту.

Реализовано в `app/search/fuzzy.py`:

- `FuzzyMatcher` хранит собственный immutable-снимок вариантов в памяти.
- `FuzzyMatcher.from_repository` обращается к SQLite только при создании matcher.
- Для сопоставления используется `rapidfuzz.process.extract` со scorer `fuzz.WRatio`.
- Все варианты оцениваются до дедупликации, поэтому несколько алиасов одной статьи
  не вытесняют другие статьи из итогового топ-3.
- Для каждой статьи сохраняется максимальная оценка среди основного термина и алиасов.
- Результат ограничен тремя уникальными статьями и стабильно сортируется по убыванию
  score, затем по отображаемому термину и ID.
- Пустой индекс обрабатывается без исключения.

Проверка этапа:

```powershell
poetry run pytest tests/unit/test_fuzzy.py -q
```

Результат: 15 тестов этапа пройдены. Проверены замена, пропуск, вставка и перестановка
русских букв, регистр и `ё/е`, топ-3, словари из 0–2 статей, дедупликация алиасов,
одинаковые score, диагностическая оценка и отсутствие SQL-запросов при поиске.

Дополнительный smoke-тест реального словаря загрузил 562 поисковых варианта для
558 статей; опечатка в слове «абстракция» возвращает нужную статью первой.

### Этап 9. Единый поисковый сервис

Статус: завершён.

Реализовано в `app/search/models.py`:

- Явные immutable-типы результата: `ExactMatch`, `FtsMatches`, `Suggestions` и
  `InvalidQuery`, объединённые типом `SearchResult`.
- Enum `SearchStrategy` для стратегий `exact`, `fts`, `fuzzy`, `invalid`.
- Стабильные причины некорректного ввода через `InvalidQueryReason`.
- Структурированная `SearchDiagnostics` содержит только стратегию, длину
  нормализованного запроса и количество результатов; полный запрос не сохраняется.

Реализовано в `app/search/service.py`:

- `SearchService` выполняет строгий конвейер normalize → exact → FTS → fuzzy.
- После первого непустого этапа выполнение прекращается.
- Запросы короче трёх символов после exact сразу переходят к fuzzy без вызова FTS.
- Некорректный ввод возвращает `InvalidQuery` до любого обращения к репозиторию.
- Пустой fuzzy-результат остаётся однозначным `Suggestions` с пустым кортежем.
- Лимит FTS и максимальная длина ввода валидируются при создании сервиса.
- Ошибки exact, FTS и fuzzy преобразуются в `SearchServiceError` с указанием этапа;
  исходное исключение сохраняется в `__cause__`, пользовательский ввод в ошибку не попадает.
- Зависимости описаны структурными Protocol-интерфейсами и легко подменяются в тестах.

Проверка этапа:

```powershell
poetry run pytest tests/unit/test_search_service.py -q
```

Результат: 19 тестов этапа пройдены. Проверены четыре типа результата, порядок и число
вызовов, ранний выход, короткий запрос, пустая выдача, невалидный ввод без доступа к БД,
лимиты, безопасная диагностика и контролируемые ошибки всех внутренних стратегий.

Smoke-тест на всех 558 статьях подтвердил реальные пути:

- `абстракция` → `ExactMatch`;
- `стракц` → `FtsMatches`;
- короткий неточный запрос → `Suggestions`;
- строка из пунктуации → `InvalidQuery`.

### Этап 10. Telegram UX, handlers и callback-кнопки

Статус: завершён.

Реализовано в `app/bot/callbacks.py` и `app/bot/keyboards.py`:

- Типизированный aiogram callback `TermCallback` с компактным payload `term:<id>`.
- Вертикальные inline-клавиатуры со стабильным числовым ID вместо текста термина.
- Подпись длинного термина безопасно сокращается до 64 символов.
- Количество fuzzy-кнопок дополнительно ограничивается тремя на presentation-слое.

Реализовано в `app/bot/formatting.py`:

- Термин и определение экранируются для Telegram HTML.
- Определение делится на сообщения не длиннее 4096 символов с учётом увеличения
  длины HTML entities.
- Фрагменты не разрывают entities и вместе содержат исходный текст без потерь.
- Для аномально длинного заголовка предусмотрен безопасный plain-HTML fallback.

Реализовано в `app/bot/handlers.py`:

- `/start` и `/help` с короткой инструкцией.
- Обработка текстового поиска только в приватных чатах и отдельный ответ на
  нетекстовое сообщение.
- Exact match сразу отправляет статью без клавиатуры.
- FTS-результаты отправляются как клавиатура выбора статьи.
- Fuzzy fallback использует фразу «Возможно, вы имели в виду…» и до трёх кнопок.
- Пустой результат и каждый вид невалидного запроса получают понятный ответ.
- Callback по ID получает статью через async application gateway и отправляет
  полное определение.
- Валидный, устаревший, поддельный callback и внутренняя ошибка всегда завершаются
  `callback.answer()`; ошибочные сценарии используют alert.
- Ошибка поиска преобразуется в нейтральное пользовательское сообщение без деталей.
- Router создаётся без Bot API или иных сетевых побочных эффектов.
- `BotSearchGateway` фиксирует асинхронную границу для подключения синхронного
  SearchService/SQLite без блокировки event loop на этапе 11.

Проверка этапа:

```powershell
poetry run pytest tests/unit/test_bot_formatting.py tests/unit/test_bot_handlers.py -q
```

Результат: 26 тестов этапа пройдены. Проверены команды, exact/FTS/fuzzy UX,
клавиатуры, callback-сценарии, HTML-спецсимволы, длинные определения без потери текста,
нетекстовые сообщения и отсутствие необходимости в реальном Telegram API.

### Этап 11. Webhook-приложение и жизненный цикл

Статус: завершён.

Реализовано в `app/bot/gateway.py`:

- `ThreadedSearchGateway` выполняет синхронные SQLite/SearchService операции в
  выделенном `ThreadPoolExecutor` с одним worker.
- SQLite-соединение создаётся, используется и закрывается в одном и том же потоке;
  параллельные Telegram-запросы безопасно сериализуются очередью executor.
- Event loop остаётся свободным во время обращения к БД.
- При создании gateway применяются миграции и один раз прогревается fuzzy-индекс.
- Readiness сверяет версию схемы, непустую таблицу статей, количество реальных
  FTS-документов и наличие fuzzy-вариантов.
- Закрытие идемпотентно, новые операции после shutdown отклоняются контролируемо.

Реализовано в `app/web.py`:

- Side-effect-free фабрика `aiohttp.web.Application`.
- Подключён официальный aiogram `SimpleRequestHandler` с `handle_in_background=True`.
- Webhook защищён `X-Telegram-Bot-Api-Secret-Token` через `secret_token` handler.
- На startup выполняются FTS5/trigram probe, создание gateway, миграции, прогрев
  fuzzy-индекса и `set_webhook`.
- `set_webhook` получает публичный HTTPS URL, secret и только разрешённые update-типы
  `message` и `callback_query`.
- Ошибка регистрации webhook закрывает уже созданный gateway и отменяет startup.
- На shutdown сначала завершаются фоновые задачи webhook и dispatcher, затем
  закрывается SQLite gateway.
- Обычный shutdown намеренно не вызывает `delete_webhook`.
- Добавлены `/healthz` для liveness и `/readyz` для проверки БД/индексов.
- Исключение при readiness даёт контролируемый HTTP 503 без деталей ошибки.

Реализовано в CLI:

- `tg-psyco serve` запускает внутренний aiohttp webhook-сервер.
- `tg-psyco delete-webhook` удаляет webhook только по явной команде.
- Флаг `--drop-pending-updates` позволяет явно удалить ожидающие обновления.
- Bot API session административной команды всегда закрывается.

Проверка этапа:

```powershell
poetry run pytest tests/unit/test_async_gateway.py -q
poetry run pytest tests/integration/test_web_application.py -q
poetry run python -m app.main --help
```

Результат: 11 новых тестов этапа пройдены, включая CLI. Проверены thread-affinity
SQLite, неблокирующий event loop, миграции и readiness, корректный/некорректный webhook
secret, фоновые ответы, параметры `set_webhook`, health endpoints, startup rollback,
shutdown без удаления webhook и отдельная административная операция. Telegram API
полностью заменён тестовой aiogram session, реальных сетевых запросов нет.

### Этап 12. Docker-образ и production Docker Compose

Статус: завершён.

Реализовано:

- Многостадийный `Dockerfile` на точном базовом образе
  `python:3.14.7-slim-bookworm`: Poetry 2.2.1 и компилятор используются только в
  builder, lock-файл проверяется до установки, а готовая `.venv` копируется в runtime.
- Runtime запускается от непривилегированного UID/GID 10001, пишет unbuffered-логи,
  содержит встроенный `/readyz` healthcheck и не содержит Poetry, компилятора,
  тестов, `.env` или secrets.
- `.dockerignore` исключает локальное окружение, Git, кэши, базы, secrets, исходные
  DOC/DOCX/TXT/PDF и тестовые артефакты.
- Основной `docker-compose.yaml` запускает один экземпляр `bot` за существующим
  host Nginx и публикует aiohttp только как `127.0.0.1:8080`.
- Опциональный `docker-compose.caddy.yaml` добавляет Caddy 2.11.4 для серверов без
  reverse proxy и публикует наружу только 80/443.
- Root filesystem сервисов read-only, временные файлы вынесены в `tmpfs`,
  capabilities сброшены, включён `no-new-privileges`.
- SQLite хранится в named volume вместе с WAL/SHM; Caddy override добавляет отдельные
  named volumes для сертификатов и конфигурации.
- Bot token и webhook secret монтируются только в `bot` через Compose secrets и
  читаются из файлов `/run/secrets/*`.
- Настроены readiness/health checks, а для Caddy — зависимость по health;
  `restart: unless-stopped`, 30-секундный graceful stop и ротация json-file логов.
- Импорт словаря запускается одноразовым контейнером через сервис `bot`; отдельный
  Compose-сервис для редкой административной операции не поддерживается.
- `Caddyfile` завершает TLS, сжимает ответы и проксирует запросы в `bot:8080` с
  активной проверкой `/healthz`.
- README документирует подготовку secrets, сборку, импорт, запуск, диагностику,
  обновление, остановку, backup и restore SQLite volume.
- Добавлены конфигурационные тесты Dockerfile, `.dockerignore`, Caddyfile и
  нормализованной Compose-модели.

Проверка этапа:

```powershell
$env:BOT_DOMAIN='bot.example.test'
docker compose config --quiet
docker build --target runtime --tag tg-psyco-bot:local .
docker run --rm tg-psyco-bot:local tg-psyco check
poetry check --lock
poetry run ruff check app tests
poetry run pytest -q
```

Результат:

- Production image успешно собран с нуля, lock-файл проверен во время build.
- В контейнере подтверждены UID/GID 10001 и рабочий SQLite 3.40.1 с FTS5 trigram.
- Runtime filesystem проверен на отсутствие Poetry, GCC, `.env`, secrets и tests.
- Реальный словарь импортирован в тестовый named volume: 558 статей, 4 алиаса и
  558 FTS-документов; новый контейнер увидел те же данные. Тестовый volume удалён.
- Точный Caddy image загружен, `caddy validate` подтвердил корректный Caddyfile.
- Основная Compose-конфигурация публикует bot только на loopback; объединённая с
  Caddy override публикует наружу только 80/443. Значений secrets в YAML нет.
- Полный набор: **205 тестов пройдено**, Ruff без ошибок.

Публичный smoke-test `bot + Nginx/Caddy → healthy → HTTPS` остаётся операционной
проверкой при развёртывании: для startup приложения намеренно нужны действующие
Telegram token, webhook secret и DNS, поскольку бот регистрирует webhook до перехода
в ready. Реальные credentials не создавались и сетевой вызов Telegram в локальной
проверке не выполнялся.

### Этап 13. Сквозная проверка, эксплуатация и документация

Статус: завершён.

Реализовано:

- Добавлен интеграционный тест полного поискового конвейера на текущем JSON и
  реальной SQLite-базе из 558 статей.
- Подтверждены exact-поиск с нормализацией регистра и пунктуации, вариант `ё/е`,
  FTS5 trigram по подстроке и RapidFuzz fallback при опечатке.
- Добавлен сквозной тест webhook update → aiogram handler → threaded gateway →
  SQLite/SearchService → Bot API response.
- Внешний Telegram API полностью заменён `RecordingSession`: fuzzy-ответ содержит
  реальные inline-кнопки, callback первой кнопки возвращает определение из SQLite.
- Некорректный webhook secret получает HTTP 401 до обращения к gateway/dispatcher.
- Создан `app/logging_config.py` с компактным JSON formatter и фильтром редактирования
  bot token/webhook secret в сообщениях и аргументах логов.
- SearchService пишет только событие, стратегию, длительность, число результатов и
  длину нормализованного запроса; исходный пользовательский текст не логируется.
- Ошибки поиска/SQLite и операций Telegram webhook логируются по безопасному типу
  ошибки без exception message и credentials.
- Юнит-тесты проверяют маркировку `exact`, `fts`, `fuzzy`, метрики, отсутствие
  исходного запроса и маскирование secrets.
- Дополнена CLI-валидация команд `check`, `serve`, `delete-webhook` и аргументов
  `import-dictionary`.
- README теперь полностью описывает локальный запуск, обязательные параметры,
  автоматическую регистрацию webhook, DNS/firewall/TLS, production deployment,
  диагностику, безопасные логи, release-check, обновление, backup и restore.
- Deployment разделён на базовый `docker-compose.yaml` для существующего host Nginx
  и опциональный `docker-compose.caddy.yaml`; оба варианта имеют отдельные
  конфигурационные проверки.

Проверка этапа:

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

Результат:

- Poetry lock согласован, Ruff без ошибок.
- Полный набор: **217 тестов пройдено**.
- Compose-модель валидна.
- Обновлённый production image успешно собран.
- Внутри image успешно прошли конфигурация и SQLite FTS5 trigram probe.
- Ни один тест не обращался к реальному Telegram API.

Оставшаяся операционная проверка — запуск на целевом сервере с реальным доменом,
DNS и Telegram credentials, ожидание `healthy` у `bot` (и `caddy`, если выбран
override) и запрос публичных `/healthz` и `/readyz`. Это нельзя достоверно
воспроизвести с фиктивным Telegram token, поскольку startup намеренно регистрирует
настоящий webhook.

## Общая проверка после этапа 13

Последний полный прогон:

```powershell
poetry sync
poetry check --lock
poetry run ruff check app tests
poetry run pytest -q
```

Результат:

- Poetry lock согласован.
- Ruff: ошибок нет.
- Pytest: **217 тестов пройдено**.

Из-за ограничений ACL системного временного каталога Windows тесты не используют встроенный `tmp_path`. Вместо него определена контролируемая фикстура `workspace_tmp_path`, создающая временные файлы внутри `data/.test-runtime` и удаляющая только собственный каталог теста.

## Ключевые файлы

```text
app/
├── __init__.py
├── config.py
├── logging_config.py
├── main.py
├── web.py
├── bot/
│   ├── __init__.py
│   ├── callbacks.py
│   ├── formatting.py
│   ├── gateway.py
│   ├── handlers.py
│   └── keyboards.py
├── db/
│   ├── __init__.py
│   ├── capabilities.py
│   ├── connection.py
│   ├── import_dictionary.py
│   ├── migrate.py
│   ├── repository.py
│   └── schema.sql
└── search/
    ├── __init__.py
    ├── fts_query.py
    ├── fuzzy.py
    ├── models.py
    ├── normalize.py
    └── service.py

tests/
├── conftest.py
├── integration/
│   ├── test_real_search_pipeline.py
│   ├── test_real_dictionary_import.py
│   └── test_web_application.py
└── unit/
    ├── test_async_gateway.py
    ├── test_bot_formatting.py
    ├── test_bot_handlers.py
    ├── test_container_config.py
    ├── test_project.py
    ├── test_config.py
    ├── test_sqlite_capabilities.py
    ├── test_normalize.py
    ├── test_db_connection.py
    ├── test_fts_query.py
    ├── test_fuzzy.py
    ├── test_import_dictionary.py
    ├── test_logging_config.py
    ├── test_migrations.py
    ├── test_repository.py
    └── test_search_service.py
```

## Точка продолжения

Основной план завершён. Продолжение — production deployment и smoke-test по README.

Нужно реализовать:

1. На сервере заполнить `.env` и файлы `secrets/bot_token`,
   `secrets/webhook_secret` реальными значениями.
2. Настроить DNS и firewall, выполнить первичную сборку/импорт/запуск командами из
   README.
3. Убедиться, что `docker compose ps` показывает `healthy`, а публичные `/healthz`
   и `/readyz` отвечают HTTP 200.
4. Проверить реальный диалог с ботом: exact, часть термина, опечатка и callback.
