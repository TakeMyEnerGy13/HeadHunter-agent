# HeadHunter Agent

Telegram-бот, который помогает искать вакансии на HH, быстро оценивать их под резюме и писать персонализированные сопроводительные письма.

Идея проекта: убрать ручную рутину из поиска работы. Бот хранит резюме и настройки пользователя, сам ходит в HH API, фильтрует вакансии, прогоняет их через LLM-анализ и присылает только релевантные варианты с готовым письмом для отклика.

## Что делает бот

- Ищет вакансии на HeadHunter по заданным ключевым словам.
- Поддерживает автопоиск по расписанию.
- Фильтрует вакансии по стоп-словам, чтобы отсекать нерелевантные варианты.
- Запоминает уже просмотренные вакансии и не гоняет пользователя по одним и тем же объявлениям.
- Сравнивает текст вакансии с резюме и оценивает релевантность.
- Генерирует сопроводительное письмо под конкретную вакансию.
- Учитывает пользовательский стиль письма: можно загрузить примеры своих текстов.
- Учитывает предпочтения: например, писать короче, без официоза, делать акцент на конкретном опыте.
- Позволяет написать письмо вручную: пользователь отправляет текст вакансии или ссылку, бот возвращает готовое письмо.
- Логирует LLM-шаги пайплайна в локальную trace-базу для отладки качества, latency и ошибок.
- Поддерживает eval-набор для регрессионной проверки prompt/scoring изменений.
- Работает через Telegram-меню без отдельного интерфейса.

## Что реализовано под капотом

### Telegram-интерфейс

Бот построен на `aiogram` и работает через кнопочное меню:

- загрузка и обновление резюме;
- настройка ключевых слов;
- настройка слов-исключений;
- сохранение примеров стиля;
- сохранение предпочтений к письмам;
- ручная генерация письма;
- запуск поиска по кнопке;
- ручной scan Telegram job channels;
- просмотр последних сохранённых TG-постов;
- включение и выключение автопоиска;
- просмотр текущих настроек;
- очистка истории просмотренных вакансий.

### Поиск вакансий

Клиент HH API находится в `app/services/hh_client.py`.

Он:

- собирает поисковый запрос из нескольких ключевых слов через `OR`;
- ходит в `https://api.hh.ru/vacancies`;
- поддерживает пагинацию;
- запрашивает свежие вакансии через сортировку по времени публикации;
- отсекает вакансии по словам-исключениям;
- дедуплицирует вакансии по `id`;
- умеет листать выдачу, пока не наберет заданное количество новых вакансий;
- возвращает нормализованные `Vacancy`-модели через `pydantic`;
- выводит диагностичную ошибку с `status`, `request_id` и `errors`, если HH API вернул неуспешный ответ.

## Источники вакансий

Бот поддерживает несколько источников. Каждый включается/выключается через `.env`:

| Источник | Требуется | Переменная |
|----------|-----------|------------|
| SuperJob | API ключ ([регистрация](https://api.superjob.ru/register)) | `SUPERJOB_API_KEY` |
| Trudvsem (Работа России) | Ничего | `TRUDVSEM_ENABLED=1` (по умолчанию вкл) |

Если все источники отключены, бот сообщит об этом при попытке поиска.

### Telegram job sources

Отдельный CLI-reader умеет читать публичные Telegram-каналы через Telethon и сохранять подходящие посты в локальную SQLite-базу `data/source_posts.sqlite`.

Это пока не подключено к основному LLM-пайплайну и Telegram-боту: первый шаг только собирает и фильтрует сырой feed.

Настройки в `.env`:

```env
TG_API_ID=your_telegram_api_id_here
TG_API_HASH=your_telegram_api_hash_here
TG_SESSION_NAME=job_bot_tg_source
# Optional defaults for the standalone CLI reader only:
TG_JOB_CHANNELS=ods_jobs,some_ai_jobs_channel
TG_SOURCE_KEYWORDS=python,ai,llm,qa automation
TG_SOURCE_NEGATIVE_KEYWORDS=senior,lead,relocation only
```

Первый запуск может попросить телефон и код авторизации Telegram:

```powershell
python -m app.sources.telegram_feed --limit 20
```

Запуск с параметрами без изменения `.env`:

```powershell
python -m app.sources.telegram_feed --channels ods_jobs --keywords "python,llm" --negative-keywords "senior,lead" --limit 20
```

Посмотреть последние сохранённые посты:

```powershell
python -m app.sources.telegram_feed --list-saved --limit 10
```

В Telegram-меню есть три кнопки:

- `⚙️ Настроить каналы` — сохраняет личный список публичных каналов пользователя. Поддерживаются `@channel`, `channel` и `https://t.me/channel`.
- `📡 Скан TG` — читает только личные каналы пользователя, фильтрует по его текущим ключам и исключениям, сохраняет новые посты.
- `🗂 TG посты` — показывает последние сохранённые TG-посты.

`TG_API_ID`, `TG_API_HASH` и `TG_SESSION_NAME` остаются конфигурацией развёртывания для Telethon. Список каналов для bot-flow задаётся в самом боте и не берётся из `TG_JOB_CHANNELS`. Первую авторизацию Telethon лучше сделать через CLI, потому что Telegram может запросить телефон и код.

### Память и настройки

Данные хранятся в локальной SQLite-базе `bot_data.sqlite`.

В базе лежат:

- `resume_text` - текст резюме;
- `keywords` - ключевые слова для поиска;
- `negative_keywords` - стоп-слова;
- `tone_samples` - примеры пользовательского стиля;
- `preferences` - пожелания к письмам;
- `is_active` - статус автопоиска;
- `seen_vacancies` - история уже просмотренных вакансий.

Для новых полей есть мягкие миграции через `ALTER TABLE`, поэтому существующая локальная база обновляется без ручного пересоздания.

### LLM-анализ и письма

Генерация письма вынесена в пайплайн `app/agents/cover_letter_pipeline.py`.

Пайплайн состоит из 4 шагов:

1. `Parser` извлекает из вакансии роль, компанию, стек, навыки, обязанности и seniority.
2. `Matcher` сопоставляет требования вакансии с резюме и выделяет совпадения, пробелы и selling points.
3. `Writer` пишет письмо на основе релевантного опыта, пользовательского стиля и предпочтений.
4. `Critic` оценивает письмо, ищет проблемы и при необходимости возвращает улучшенную версию.

Если качество ниже порога, пайплайн делает повторную попытку с обратной связью от критика.

Пайплайн возвращает структурированный результат для evals и diagnostics, а основной Telegram-flow по-прежнему получает только готовый текст письма.

### LLM observability

LLM-вызовы пишутся в отдельную SQLite-базу `data/traces.sqlite`.

Логируются:

- `run_id`;
- шаг пайплайна: `parse_job`, `match_profile`, `write_letter`, `critique_letter`;
- модель;
- latency;
- token usage, если провайдер вернул `usage`;
- статус и ошибка;
- hash и короткий preview входа/выхода.

Полные prompts и резюме по умолчанию не сохраняются.

Посмотреть последние trace runs:

```powershell
python -m app.observability_report --last 5
```

### Evals

В проекте есть лёгкий eval harness для проверки LLM-пайплайна на фиксированных CV/JD кейсах.

Датасет лежит в `evals/dataset.jsonl`. Каждый кейс задаёт:

- резюме;
- вакансию;
- ожидаемый `decision`: `good`, `maybe`, `bad`;
- ожидаемый диапазон score;
- запрещённые фразы для письма;
- утверждения, которые письмо не должно выдумывать.
- запрещённые synthetic gaps, которые matcher не должен выводить без явного требования вакансии.
- запрещённые unsupported phrases в matcher output: например `вероятно`, `быстро освоит`, `легко адаптируется`.

Проверить датасет без LLM-запросов:

```powershell
python -m app.evals.run --dry-run
```

Запустить evals:

```powershell
python -m app.evals.run
```

Сохранить JSON-отчёт:

```powershell
python -m app.evals.run --output evals/results/latest.json
```

Запустить один кейс для отладки prompt/scoring изменений:

```powershell
python -m app.evals.run --case-id prompt_engineer_good_001
```

Команда возвращает non-zero exit code, если хотя бы один кейс провален.

Текущий baseline:

```text
Cases: 11
Passed: 11
Failed: 0
```

### Ручная генерация письма

Команда `Написать письмо` позволяет не запускать поиск по HH.

Пользователь может отправить:

- текст вакансии;
- ссылку на вакансию;
- ссылку на другое описание работы.

Если это ссылка, `app/utils/fetcher.py` загружает страницу, вычищает HTML и достает текст. В fetcher добавлена базовая SSRF-защита: приватные и локальные IP-адреса блокируются.

### Планировщик

Автопоиск работает через `APScheduler`.

Раз в 4 часа бот:

- берет всех пользователей с включенным `is_active`;
- запускает поиск для каждого;
- проверяет только новые вакансии;
- анализирует их через LLM;
- отправляет подходящие варианты в Telegram.

## Стек

- Python
- aiogram
- aiosqlite
- httpx
- pydantic
- OpenAI-compatible LLM API
- APScheduler
- BeautifulSoup

## Структура проекта

```text
app/
  agents/        LLM-агенты и пайплайн генерации писем
  database/      SQLite-модели и настройки пользователей
  evals/         CLI runner и deterministic checks для eval-набора
  handlers/      Telegram-команды и меню
  services/      HH API и Telegram-уведомления
  sources/       Источники вакансий вне HH, включая Telegram feed reader
  utils/         Загрузка текста вакансии по URL и вспомогательные функции
  observability.py  Локальное логирование LLM trace steps
evals/           JSONL-датасет для regression checks
config.py        Конфигурация окружения
main_bot.py      Точка входа
```

## Локальные данные и безопасность

Бот хранит пользовательские данные в `bot_data.sqlite`.
Trace-логи LLM-пайплайна хранятся в `data/traces.sqlite`.
Посты из Telegram source reader хранятся в `data/source_posts.sqlite`.

Эти SQLite-файлы не должны попадать в git, потому что там могут быть:

- резюме;
- настройки пользователей;
- история вакансий;
- персональные предпочтения.
- фрагменты входов/выходов LLM-пайплайна.
- тексты вакансий и контакты из Telegram-постов.

Также не коммитьте `.env`, Telegram-токены и ключи LLM API.

## Гайд по запуску

1. Склонируйте репозиторий:

```powershell
git clone https://github.com/TakeMyEnerGy13/HeadHunter-agent.git
cd HeadHunter-agent
```

2. Создайте виртуальное окружение:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

3. Установите зависимости:

```powershell
pip install -r requirements.txt
```

4. Создайте `.env`:

```powershell
Copy-Item .env.example .env
```

5. Заполните переменные окружения:

```env
LLM_API_KEY=your_llm_api_key_here
LLM_BASE_URL=http://localhost:20128/v1
MODEL_NAME=kr/claude-sonnet-4.5
HH_USER_AGENT=hh-agent/0.2 (+https://github.com/TakeMyEnerGy13/HeadHunter-agent)
TG_BOT_TOKEN=your_telegram_bot_token_here
TG_CHAT_ID=your_telegram_chat_id_here
```

6. Запустите бота:

```powershell
python .\main_bot.py
```

После запуска откройте Telegram, отправьте боту `/start`, загрузите резюме и настройте ключевые слова.

## Запуск на VPS 24/7

Самый простой рабочий вариант для Linux-сервера - держать бота как `systemd` service.

1. Подготовьте сервер:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
```

2. Скопируйте проект на сервер, например в `/opt/hh_agent`, и создайте окружение:

```bash
cd /opt/hh_agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

3. Заполните `.env`.

Для обычной работы достаточно `TG_BOT_TOKEN`, `LLM_API_KEY`, `LLM_BASE_URL`, `MODEL_NAME`.

Если используете Telegram channel scan через Telethon, один раз выполните ручную авторизацию:

```bash
source .venv/bin/activate
python -m app.sources.telegram_feed --limit 1
```

4. Установите systemd unit:

```bash
sudo cp deploy/systemd/hh-agent.service /etc/systemd/system/hh-agent.service
sudo systemctl daemon-reload
sudo systemctl enable --now hh-agent
```

5. Проверьте статус и логи:

```bash
sudo systemctl status hh-agent
sudo journalctl -u hh-agent -f
```

Замечания:

- Бот использует polling, поэтому webhook отдельно не нужен.
- SQLite-файлы и Telethon session по умолчанию лежат внутри директории проекта.
- Пути можно переопределить через `.env`: `BOT_DB_PATH`, `TRACE_DB_PATH`, `TG_SOURCE_DB_PATH`, `TG_SESSION_NAME`.
