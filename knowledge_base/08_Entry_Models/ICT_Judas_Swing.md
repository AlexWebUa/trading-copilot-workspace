---
title: ICT Judas Swing
tags: [entry, ict, judas-swing, session, manipulation]
aliases: [Judas Swing, ICT Judas Swing]
sources: [raw_notion/ICT_JUDAS_SWING.md, course-archiver/output/DT_MATERIAL_50/sessions-2/notion_3.md, course-archiver/output/DT_MATERIAL_50/sessions-2/notion_5.md]
status: defined
updated: 2026-08-05
---

# ICT Judas Swing

**Judas Swing** — ложное свинговое движение, направленное **противоположно** истинному движению дня. Цель: запутать участников рынка и скрыть настоящее намерение цены.

> Данный инструмент не даёт чёткого входа в позицию, но даёт большее — **понимание, куда и по каким причинам цена двигалась**.

## Правила распознавания

1. Азиатская сессия — **боковик** (обязательное условие).
2. Свинг формируется в окне **00:00–05:00 EST** (London/pre-NY).
3. Движение должно быть **полноценным**, большим — не микро-мув.
4. Перед началом Judas Swing цена делает **манипуляцию над AH/AL** (Asian High/Low) в противоположном направлении.

## Алгоритм определения

1. Определить **BIAS на день** (дневное направление).
2. Judas Swing = движение **противоположного** направления к BIAS.
3. Дождаться **манипуляции над AH/AL** (противоположной Judas Swing).
4. Начало свинг-движения от NYM до конца окна — это и есть Judas Swing.

**Judas Swing формирует экстремум дня**: при бычьем BIAS — Low дня; при медвежьем — High дня.

## NYM / TDO и 8:30 — ключевые уровни для входа

**NYM** (New York Midnight, он же **TDO** — True Daily Open) и **8:30** (для индексов — открытие ОТТ на CME) — уровни, вокруг которых строится план на манипуляцию Judas Swing.

**Логика (пример для Short BIAS)**:
1. Ожидается манипуляция **над NYM** — это и есть Judas Swing (цена выше открытия дня = Premium).
2. Работа в диапазоне **выше NYM** — идеальная зона набора шорт-позиций.
3. Если вход выше NYM не найден — **вторая попытка**: ждать аналогичную манипуляцию над уровнем **8:30 AM**.

(Зеркально для Long BIAS — манипуляция под NYM/8:30, зона ниже = Discount.)

### Классификация зон относительно BIAS

| BIAS | Условие | Классификация |
|---|---|---|
| Short | Цена выше 8:30 **или** NYM | Premium |
| Short | Цена выше 8:30 **и** NYM | **Deep Premium** |
| Long | Цена ниже 8:30 **или** NYM | Discount |
| Long | Цена ниже 8:30 **и** NYM | **Deep Discount** |

NYM/TDO и 8:30 тесно связаны с Classic Buy/Sell Day (см. [[../06_Bias_Templates/ICT_Daily_Bias]], [[../06_Bias_Templates/ICT_Intraday_Templates]]) и OHLC/OLHC — оба уровня используются как референс для того, где именно искать манипуляцию Judas Swing.

## Связь с Daily PO3

Judas Swing = манипуляционная фаза (M) в рамках London-сессии Daily PO3:
- Asia: Accumulation (боковик, накопление).
- London: Manipulation (Judas Swing — ложный выпад).
- NY: Distribution (истинное направление дня).

## Связанные заметки

- [[../05_Sessions_Timings/PO3_AMD|PO3 / AMD — Daily PO3]]
- [[../05_Sessions_Timings/Session_Dynamics|Динамика сессий]]
- [[../03_Tools/Liquidity_in_Sessions|AH/AL — ликвидность в сессиях]]
- [[../05_Sessions_Timings/PO3_AMD#Daily PO3|Daily Open / NYM]]
- [[../06_Bias_Templates/ICT_Daily_Bias|ICT Daily Bias]]
- [[../99_Glossary/Glossary#J|Глоссарий: Judas Swing]]
