# Перенос и развёртывание на Windows

Составлено 2026-08-26 при переезде с Linux (`/home/alex/vibecoding`) на Windows.
Проект уже жил на Windows раньше — `run_mcp.bat` с первого коммита содержал
пути `D:\Projects\vibecoding\...`, — так что часть инфраструктуры к этому готова.

---

## 1. Перед отъездом со старой машины

### 1.1 Закоммитить всё

На момент составления в рабочем дереве было **98 изменённых и новых файлов**, а
коммит `7a6dc03` не существовал ни на одном remote. Через git переносится
только то, что закоммичено И запушено.

```bash
cd trading-copilot-workspace
git status --short | wc -l              # сколько ещё не в индексе
git branch -r --contains HEAD           # пусто = HEAD только локально
```

Ветка `p1-p2-remediation` **не имеет upstream**, поэтому при первом push:

```bash
git push -u trading-copilot-workspace p1-p2-remediation
```

> Remote называется `trading-copilot-workspace`, а НЕ `origin`.
> Привычное `git push origin ...` не сработает.

### 1.2 Забрать то, что вне git

| Что | Где | Зачем |
|---|---|---|
| `.env` | `trading-copilot/.env` | `ANTHROPIC_API_KEY` — в git не входит и не должен |
| Состояние копилота | `~/.trading-copilot/` | `session.json`, отчёты анализа, `pine/`, `traces/` |

Кэш котировок (`~/.cache/trading-copilot/`, ~8 МБ) переносить не нужно —
скачается заново. Виртуальное окружение (`.venv`, ~582 МБ) переносить **нельзя**:
оно содержит скомпилированные под Linux бинарники.

---

## 2. Авторство коммитов — три подводных камня

### 2.1 Локальная почта не переезжает с клоном

Личная почта прописана в `.git/config`, а этот файл **не входит в клон**. После
`git clone` на Windows заработает глобальный конфиг — и если там рабочая почта,
все новые коммиты уйдут под ней.

```bash
git config user.email alexwebua1@gmail.com
git config user.name "Oleksandr Ovechko"
```

Проверить: `git log --format="%an <%ae>" -1` после первого коммита.

### 2.2 Push идёт под тем аккаунтом, под которым залогинен gh

На Linux аутентификация шла через `gh auth git-credential` от аккаунта
`Oleksandr-Ovechko` (рабочий), тогда как репозиторий принадлежит `AlexWebUa`
(личный). Коммит атрибутируется по verified-почте, но push-событие GitHub
записывает на аккаунт токена.

Для чистого разделения на новой машине:

```bash
gh auth login          # выбрать AlexWebUa
gh auth status         # убедиться, что активен нужный аккаунт
```

### 2.3 Remote — не `origin`

См. выше. При желании можно переименовать: `git remote rename trading-copilot-workspace origin`.

---

## 3. Развёртывание

```powershell
cd D:\Projects\vibecoding\trading-copilot-workspace\trading-copilot

py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"

copy .env.example .env      # затем вписать ANTHROPIC_API_KEY
```

Python **3.12** — на нём собран проект (`Python 3.12.3`).

### Проверка

```powershell
.venv\Scripts\python.exe -m pytest        # ожидается 541 passed, 3 xfailed
.venv\Scripts\python.exe -c "from copilot.backtest.engine import _KYIV_TZ; print(_KYIV_TZ)"
```

Вторая команда — самая важная: она проверяет часовые пояса (см. § 4.1).

---

## 4. Что отличается от Linux

### 4.1 Часовые пояса — единственный настоящий блокер

В Windows нет системной базы часовых поясов. `zoneinfo.ZoneInfo()` берёт её из
пакета `tzdata`, и без него падает. `backtest/engine.py` создаёт `_KYIV_TZ` и
`_NY_TZ` **на уровне модуля**, поэтому ломается не отдельный тест, а импорт
всего пакета бэктеста.

Исправлено: `tzdata` добавлен в `pyproject.toml` под маркером
`sys_platform == 'win32'` и ставится сам вместе с `pip install -e .`.
Плюс `_tz()` теперь бросает понятное сообщение вместо
`ZoneInfoNotFoundError: 'No time zone found with key Europe/Kyiv'`.

Занятная деталь: `journal/record.py` для той же Киевской зоны использует `pytz`,
у которого своя встроенная база, — тот модуль работал бы и без tzdata.

### 4.2 Пути к интерпретатору

| Linux | Windows |
|---|---|
| `.venv/bin/python` | `.venv\Scripts\python.exe` |
| `source .venv/bin/activate` | `.venv\Scripts\activate` |
| `./run_mcp.sh` | `run_mcp.bat` |

`run_mcp.bat` переписан: раньше в нём были захардкожены `D:\Projects\...` и
несуществующий `.venv_mcp`, теперь всё выводится из `%~dp0`.

### 4.3 Что проверено и НЕ требует правок

- **Кодировки.** Разбор синтаксиса всех `.py` в `copilot/`, `scripts/`, `tests/`
  дал **ноль** мест текстового ввода-вывода без явной `encoding`. База знаний и
  обе спецификации сетапов на кириллице, так что это было главным риском —
  риска нет.
- **Пути.** Везде `pathlib`, разделитель не хардкожен.
- **Запуск MCP из кода.** `cli_agent.py` использует `sys.executable`, а не
  путь к бинарнику.
- **Хардкод `/tmp` и `/home`.** Встречается только как строки-заглушки в моках
  тестов, реальных путей нет.

### 4.4 Мелочи, на которые можно не обращать внимания

- Shebang `#!/usr/bin/env python` в `scripts/debug_detectors.py` — на Windows
  игнорируется, скрипт запускается через `python`.
- `run_mcp.sh` остаётся в репозитории для Linux.

---

## 5. Долгие прогоны

Бэктест-прогоны идут часами (одна арма Silver Bullet ≈ 50 мин на 19 000 барах
15M). Что важно помнить:

- **Параллелить не более 3 арм.** LTF-данные не кэшируются, каждая арма
  скачивает ~95 000 баров за 64 запроса; шесть и более параллельных процессов
  ловят от Binance `429 Too Many Requests`. Ретраи с отступом добавлены, но
  лимит лучше не провоцировать.
- **Результаты писать в каталог проекта, а не во временный.** На Linux сырые
  JSON прогонов лежали в `/tmp` и были стёрты на границе сессии; выводы уцелели
  только потому, что были заранее сведены в `docs/SETUP_*.md`.
- В Windows нет `nohup`; для фона — `Start-Process` в PowerShell либо
  `start /b` в cmd.

---

## 6. Состояние на момент переезда

- Тесты: **541 passed, 3 xfailed**
- Исследование сетапов: 1h3m Bellissimo (прогон 3) и ICT Silver Bullet
  завершены, результаты в `docs/SETUP_1H3M_BELLISSIMO.md` и
  `docs/SETUP_ICT_SILVER_BULLET.md`
- Открыто: P0-11 (ре-базлайн 12 синтетических правил), ablation Bellissimo,
  кэширование LTF-данных, следующий сетап
- Реестр из 11 дефектов, найденных исследованием, — в `PLAN.md`
