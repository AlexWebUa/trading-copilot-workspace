---
title: Неоднозначности и пробелы
tags: [index, meta, ambiguities]
updated: 2026-04-18
---

# Неоднозначности, пробелы и вопросы к автору

Список мест, где исходный текст недостаточен, противоречив, или требует визуальных пояснений (которые в рамках задачи не анализируются). При обработке каждого файла добавлять сюда пункты по шаблону:

```
### [[Имя заметки]] — короткий заголовок
- **Источник**: `raw_notion/Имя_Файла.md`, строки N–M
- **Тип**: `term_undefined` | `needs_image` | `contradiction` | `unclear_wording` | `incomplete`
- **Проблема**: ...
- **Предложение**: ... (как можно закрыть — вопрос к автору, догадка, временная заглушка)
```

---

## Открытые вопросы

### ~~[[../01_Concepts/Wyckoff_Method]] — отсутствует описание фаз A–E~~ ✅ закрыто
- **Источник**: `raw_notion/Intro.md`, строки 27–42
- **Тип**: `incomplete`
- **Проблема**: Указано, что метод делится на 4 фазы, каждая из которых состоит из 5 диапазонов A–E, но сами диапазоны нигде не описаны.
- **Статус**: Раскрыто в Group 2 — см. [[../01_Concepts/Accumulation_Phase]] и [[../01_Concepts/Distribution_Phase]]. В [[../01_Concepts/Wyckoff_Method]] добавлена сводная секция «Структура диапазонов A–E» со ссылками на обе заметки.

### [[../09_Setups/1h3m_by_Bellissimo]] — «модель m3m3»
- **Источник**: `raw_notion/1h3m_For_Students.md`, строка 68
- **Тип**: `unclear_wording`
- **Проблема**: «Отсутствие модели m3m3 на LTF» — упоминается как ключевой фактор для скипа, но сама модель нигде не определена. Вероятно, имеется в виду связка m3-BOS на LTF с валидацией по второй M3-свече, но это догадка.
- **Предложение**: Уточнить у автора — это BOS на M3 с дополнительным условием, или отдельная сущность.

### ~~[[../09_Setups/1h3m_by_Bellissimo]] / [[../08_Entry_Models/Yura_Pukaliak_Entry_Logic]] — FTA~~ ✅ закрыто
- **Статус**: Определение получено от автора: FTA = «first trouble area — первая точка (POI, ликвидность, уровень), от которой цена может дать реакцию и потенциально сменить тренд». Обновлено в [[../99_Glossary/Glossary]] + добавлена ссылка на [[../07_POI/Context_BIAS_POI]].

### ~~[[../01_Concepts/Context_Determination]] — IOF~~ ✅ закрыто
- **Источник**: `raw_notion/Context.md`, строки 39–43
- **Тип**: `term_undefined`
- **Статус**: Раскрыто в Group 9 — см. [[../07_POI/IOF|Institutional Order Flow (IOF)]]. IOF = специфическая разновидность Order Flow на LTF в момент теста HTF POI.

### ~~[[../09_Setups/1h3m_by_WinstonFX]] — пустая страница со структурой~~ ✅ закрыто
- **Статус**: Контент получен от автора. Написана полная заметка: анализ дня, OF, OTT, One/Two Step Confirming, Model to Entry (BOS 3M, требования к агрессии), RR, TP, SL (защищённая ликвидность), Red Flags, Conditions, Steps. Статус → defined.

### [[../09_Setups/Dynamic_Trading_System_WinstonFX]] — JS-виджет не захвачен
- **Источник**: `raw_notion/Dynamic_Trading_System_WinstonFX.md`
- **Тип**: `incomplete`
- **Проблема**: В файле присутствует маркер `> Loading JavaScript code…` — возможно, контент рендерился динамически и не попал в экспорт.
- **Предложение**: Повторный экспорт с ожиданием загрузки JS.

### ~~[[../09_Setups/Narrative_Fix_Bellissimo]] — только заголовок~~ ✅ закрыто
- **Статус**: Подтверждено автором — страница содержит только изображения (примеры без текста). Stub заметка сохраняется как заглушка; контент не создаётся.

### ~~[[../99_Glossary/Glossary]] — SP (Settlement Price)~~ ✅ закрыто
- **Статус**: Раскрыто в Group 13 — Settlement Price = официальная расчётная цена закрытия Xetra (VWAP последней минуты, 17:30 CET). → [[../04_Market_Profile/OAR_IDAR]]

### [[../99_Glossary/Glossary]] — 8 тем Notion не извлечены скрейпером (частично закрыто)
- **Источник**: `raw_notion/Notion.md`, `Notion_2.md` … `Notion_8.md`
- **Тип**: `incomplete`

| Страница | Тема | Статус |
|---|---|---|
| `Notion.md` | DARK-TRADER-VISION (корневая) | ⬜ не получена |
| `Notion_2.md` | **Inducement** | ✅ закрыто → [[../03_Tools/Inducement]] |
| `Notion_3.md` | **TGIF-Setup** | ✅ закрыто → [[../09_Setups/TGIF_Setup]] |
| `Notion_4.md` | **Trading-Strategy-by-Isqra** | ✅ закрыто → [[../09_Setups/Isqra_Strategy]] |
| `Notion_5.md` | **How-to-Create-Static-Setup** | ✅ закрыто → добавлено в [[../01_Concepts/Static_vs_Dynamic]] |
| `Notion_6.md` | **Day-Types-For-What** | ⬜ не получена |
| `Notion_7.md` | ICT-INTERVIEW: How to Retire at 40 | ⬜ не получена (информационная, не критическая) |
| `Notion_8.md` | **BIAS-POI** | ✅ закрыто → [[../07_POI/Context_BIAS_POI]] |

- **Осталось**: `Notion.md`, `Notion_6.md`, `Notion_7.md` — если критично, запросить у автора.

### [[../06_Bias_Templates/IntraDay_Price_Templates]] — изображения не извлечены
- **Источник**: `raw_notion/IntraDay_Price_Templates.md`
- **Тип**: `needs_image`
- **Проблема**: Файл содержит 2 месяца личных наблюдений автора с 8+ изображениями (по неделям 30.01–17.03), но все они представлены только как URL-ссылки (скрейпер не захватил контент изображений). Текстовая часть сводится к короткому введению и выводам — без описания самих шаблонов.
- **Предложение**: Запросить у автора текстовые описания ICT Intraday Templates или повторный экспорт с alt-текстами. Пока создан [[../06_Bias_Templates/IntraDay_Price_Templates|stub]].

### ~~[[../06_Bias_Templates/ICT_Intraday_Templates]] — дублирующий файл, только изображения~~ ✅ закрыто
- **Статус**: Список 6 шаблонов получен от автора (ICT Classic Buy/Sell Day, London Swing to Z-Day, London Swing to NYD/LC Reversal, Range to NYO/LC Rally, Consolidation Raid on News Release, London Swing to Seek & Destroy). Обновлён [[../06_Bias_Templates/ICT_Intraday_Templates]], статус → defined.

### ~~[[../06_Bias_Templates/Quarterly_Theory]] — материалы на отдельных Notion-страницах~~ ✅ закрыто
- **Статус**: Все 3 страницы материалов получены в `raw_notion/`. Quarterly Theory полностью написана: фракталы времени, True Open, AMDX/XAMD, SSMT (+ Hidden SSMT, валидация), Time Theory, общие наблюдения, сетап-структура. Статус заметки → defined.

---

## Приоритеты для повторного экспорта / уточнения у автора

| Приоритет | Пункт | Тип | Статус |
|---|---|---|---|
| ~~🔴 Высокий~~ | ~~Notion_2 — **Inducement**~~ | — | ✅ закрыто |
| ~~🔴 Высокий~~ | ~~Notion_8 — **BIAS-POI**~~ | — | ✅ закрыто |
| ~~🔴 Высокий~~ | ~~Notion_3 — **TGIF-Setup**~~ | — | ✅ закрыто |
| ~~🟡 Средний~~ | ~~**Quarterly Theory** (1, 2, 3)~~ | — | ✅ закрыто |
| ~~🟡 Средний~~ | ~~**ICT Intraday Templates**~~ | — | ✅ закрыто |
| ~~🟡 Средний~~ | ~~Notion_4 — **Isqra Strategy**~~ | — | ✅ закрыто |
| ~~🟡 Средний~~ | ~~Notion_5 — **How to Create Static Setup**~~ | — | ✅ закрыто |
| ~~🟢 Низкий~~ | ~~**FTA** (First Trouble Area?)~~ | — | ✅ закрыто |
| ~~🟢 Низкий~~ | ~~Narrative_Fix_Bellissimo~~ | — | ✅ закрыто (только изображения) |
| 🟡 Средний | **Notion_6** — Day-Types-For-What | Не экспортирован | ⬜ ожидает |
| ~~🟡 Средний~~ | ~~**Notion_6** — Day-Types-For-What~~ | — | ✅ закрыто → добавлено в [[../06_Bias_Templates/Day_Types]] |
| ~~🟢 Низкий~~ | ~~1h3m WinstonFX~~ | — | ✅ закрыто → [[../09_Setups/1h3m_by_WinstonFX]] |
| 🟡 Средний | Плохие экспорты (8 файлов, без DT16 и Dark_Trader) | h4 = только графика | ℹ️ KB-заметки полные, ре-экспорт не нужен |
| 🟢 Низкий | **DTS WinstonFX** | JS не загружен | ⬜ ожидает (если критично) |
| 🟢 Низкий | **m3m3 модель** (Bellissimo) | Unclear wording | ⬜ уточнить у автора |
| 🟢 Низкий | **Notion_7** — ICT-INTERVIEW | Не экспортирован | ⬜ (не критичный) |

## Статус закрытых пунктов

- ✅ Wyckoff фазы A–E → закрыто в Group 2
- ✅ IOF расшифровка → закрыто в Group 9
- ✅ SP (Settlement Price) → закрыто в Group 13
- ✅ FTA → закрыто (raw_failed, определение автора)
- ✅ Inducement → закрыто (raw_failed)
- ✅ TGIF → закрыто (raw_failed)
- ✅ Isqra Strategy → закрыто (raw_failed)
- ✅ How to Create Static Setup → закрыто (raw_failed, добавлено в Static_vs_Dynamic)
- ✅ Quarterly Theory → закрыто (raw_failed, Materials 1+2+3)
- ✅ ICT Intraday Templates → закрыто (6 шаблонов от автора)
- ✅ BIAS-POI → закрыто (raw_failed)
- ✅ Narrative_Fix_Bellissimo → закрыто (только изображения, контент не создаётся)
- ✅ Notion_6 (Day-Types-For-What) → закрыто (контент добавлен в Day_Types как intro-секция)
- ✅ 1h3m WinstonFX → закрыто (контент получен, полная заметка написана)
- ℹ️ DT16, Dark_Trader_Index_Sessions_Indicator → skip навсегда (только графика; KB-заметки полные из текстовых частей)
