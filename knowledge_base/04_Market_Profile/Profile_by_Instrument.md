---
title: Market Profile по инструментам
tags: [profile, instrument, session]
aliases: [Profile by Instrument, Профиль по инструментам]
sources: [raw_notion/Profile_for_USA_Indices.md, raw_notion/Profile_for_EURO_Indices.md, raw_notion/Profile_for_Crypto.md]
status: defined
updated: 2026-04-18
---

# Market Profile по инструментам

Логика Market Profile универсальна, но настройка инструмента профиля зависит от структуры торговых сессий конкретного рынка. Ключевой вопрос: что попадает в анализ — весь 24-часовой диапазон или только реальный аукцион?

## USA Индексы (ES, NQ, YM, RTY и ETF типа SPY)

**Основная ликвидность**: RTH — NYSE/NASDAQ открыты, работают институционалы, HFT, публикуются новости.

| Период | Тайминги (Kyiv) | Использование |
|---|---|---|
| RTH | 16:30 – 23:00 | Строить профиль; формируется реальный POC и VA |
| ETH (Overnight) | 23:00 – 16:30 | Не включать в основной профиль; шум, низкий объём |

**Настройка STPO в TradingView:**
- Session Start: `16:30`
- Session End: `23:00`
- Timezone: `Europe/Kyiv`
- Включить: Show POC / Value Area

> Профиль по 24-часовому графику для USA индексов = смешанная структура с ночными движениями → искажённые POC и VA.

## EURO Индексы (DAX / FDAX, EuroStoxx 50 / FESX)

**Основная ликвидность**: утро–день по Kiiv (CET + 1 час). Акции DAX торгуются на Xetra (Franfurt Stock Exchange). Полноценный аукцион — в европейские торговые часы.

| Период | Тайминги (Kyiv) | Использование |
|---|---|---|
| RTH | 10:00 – 18:30 | Строить профиль; реальный POC и VA |
| ETH | 19:00 – 10:00 | Вторичная активность, реакция на внешние рынки |

**Настройка STPO в TradingView:**
- Session Start: `10:00`
- Session End: `18:30`
- Timezone: `Europe/Kyiv`
- Включить: Show POC / Value Area

## Crypto (BTC, ETH, ALT фьючерсы)

**Особенность**: криптовалюта торгуется 24/7 (или 23/7 для фьючерсов BTC CME). Нет официального RTH/ETH-разделения, нет «звонка» открытия. Открытие нового дня технически = закрытие предыдущего профиля.

**Следствия для профиля:**
- Концепция **Open Type** полностью теряет смысл (нет чёткого открытия аукциона).
- **Initial Balance** (первый час RTH) — неприменим.
- **STPO не нужен** — нет сессии, которую стоит изолировать. Классического **TPO достаточно**.

Логика аукциона при этом **сохраняется**: баланс, VA, POC, инициативные и Responsive движения — работают аналогично. Процессы просто распределены равномерно во времени без «звонка открытия».

## Сводная таблица

| Инструмент | Сессия RTH (Kyiv) | Индикатор | Примечание |
|---|---|---|---|
| ES, NQ, YM, RTY | 16:30 – 23:00 | STPO | Open Type / IB применимы |
| DAX (FDAX) | 10:00 – 18:30 | STPO | OAR/IDAR/SP ключевые уровни |
| EuroStoxx (FESX) | 10:00 – 18:30 | STPO | Аналогично DAX |
| BTC/ETH Futures | 24/7 (BTC: 23/7) | TPO | Нет Open Type / IB |

## Связанные заметки

- [[../04_Market_Profile/RTH_vs_ETH|RTH vs ETH]]
- [[../04_Market_Profile/TPO_STPO|TPO vs STPO]]
- [[../04_Market_Profile/Profile_Logic|Логика Market Profile]]
- [[../04_Market_Profile/VWAP|VWAP — интеграция с OAR/IDAR/SP]]
- [[../10_Instruments/NASDAQ|NASDAQ (NQ)]]
- [[../10_Instruments/SP_500|S&P 500 (ES)]]
