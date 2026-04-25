---
title: TPO vs STPO
tags: [profile, tool, tpo]
aliases: [TPO, STPO, Time Price Opportunity, Session Time Price Opportunity]
sources: [raw_notion/TPO_vs_STPO.md]
status: defined
updated: 2026-04-18
---

# TPO vs STPO

**TPO** (Time Price Opportunity) и **STPO** (Session Time Price Opportunity) — индикаторы Market Profile в TradingView. Оба визуализируют, на каких ценовых уровнях рынок проводил больше всего времени (где формировался консенсус).

## TPO — классический дневной профиль

Строит структуру аукциона по дням: каждый блок (TPO) соответствует 30-минутному отрезку. Автоматически отображает POC, VAH/VAL и полноценный дневной профиль.

**Ограничение**: включает весь 24-часовой диапазон, не разделяя основную сессию (RTH) и ночную торговлю (ETH). Для инструментов с выраженным RTH/ETH-разделением (индексы) — POC и VA могут быть искажены малоликвидными ночными движениями.

## STPO — сессионный профиль с настройкой

Та же аукционная логика, но с возможностью задать **точные временны́е границы сессии**. Позволяет изолировать только нужный торговый период (RTH) и видеть реальный аукцион ключевых участников.

**Настройка**: `Indicators → Session Time Price Opportunity (STPO) → Session Settings → Session Start / Session End / Timezone`.

## Когда использовать STPO

| Инструмент | Рекомендуемые тайминги STPO (Kyiv) | Причина |
|---|---|---|
| ES, NQ, YM (USA индексы) | 16:30 – 23:00 | RTH NYSE/NASDAQ; основной объём и POC формируются здесь |
| DAX, EuroStoxx (EURO индексы) | 10:00 – 18:30 | RTH Xetra; европейский аукцион |
| BTC и Crypto | TPO достаточно | 24/7 рынок без выраженного RTH; STPO не даёт преимущества |

> Анализировать 24-часовой профиль для индексов = видеть смешанную структуру с ночным «шумом». STPO отделяет то, что действительно важно.

## Практический итог

- **TPO** → обзорная картина по дням, для криптовалют.
- **STPO** → точный сессионный контекст для индексных фьючерсов с чёткими RTH/ETH границами.

## Связанные заметки

- [[../04_Market_Profile/RTH_vs_ETH|RTH vs ETH]]
- [[../04_Market_Profile/Profile_by_Instrument|Профиль по инструментам]]
- [[../04_Market_Profile/Profile_Logic|Логика Market Profile]]
- [[../04_Market_Profile/POC|Point of Control]]
- [[../04_Market_Profile/Value_Area|Value Area]]
- [[../99_Glossary/Glossary#T|Глоссарий: TPO, STPO]]
