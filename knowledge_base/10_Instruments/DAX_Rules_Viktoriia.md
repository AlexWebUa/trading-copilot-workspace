---
title: DAX (FDAX) — правила отбора POI и таргетов (Viktoriia)
tags: [dax, instrument, poi, mitigation, targets]
aliases: [FDAX rules, DAX POI rules, What do I trade OPEN]
sources: [course-archiver/output/DT_TRADING_SERVER/stream-recordings_-_GER40_Viktoriia_Isqra/notion_1.md, course-archiver/output/DT_TRADING_SERVER/stream-recordings_-_GER40_Viktoriia_Isqra/notion_2.md]
status: defined
updated: 2026-08-04
---

# DAX (FDAX) — правила отбора POI и таргетов

Личный рулбук по FDAX (другой автор и подход, чем [[DAX_Strategy|DAX 1:1 Xetra Open]] — не сравнивать напрямую, это скорее чек-лист отбора POI/таргетов, не законченная бэктестируемая система).

## Базовые параметры

- **OTT**: 09:00–20:00 Kyiv (широкое окно, автор отмечает необходимость сузить).
- **RR**: минимум 1.5–2.

## Что пропускать (Skip)

- Вход в [[../07_POI/Context_BIAS_POI|FTA]].
- Середина рейнджа (Range).
- Локальный лонг «под шорт» (и наоборот) — часто даёт ре-свип или SL.
- Митигация 1D→30M, 4H→15M, 1H→15M (слишком широкий разрыв ТФ для митигации).
- Новости: без сделок перед Unemployment Rate, Non-Farm Employment Change.

## POI по ТФ

- **[[../03_Tools/FVG|FVG]]**: 4H/1H/30M/15M — глубина теста POI **не важна**, любой заход засчитывается как тест. Чаще всего используется 15M FVG.
- **[[../03_Tools/Rejection_Block|Rejection Block]]**: редко, преимущественно 4H/1H+.
- **Митигация**: лучше TF→тот же TF, либо тест FTA-структуры со sweep; допустимо TF ×(-1) при дополнительном подтверждении.
- **Ребаланс**: 4H→15M.

## Таргеты по типу

| Тип таргета | ТФ |
|---|---|
| Fractal (FR) | 1H/4H/1D/1W/ATH |
| FVG | 15M/30M/1H/4H/1D |
| Rejection Block | 1H/4H/1D |
| STDV (Standard Deviation Projection) | 2–2.5 / 4 |
| FVL | 1H/4H |

## Каскад ТФ

**HTF** 4H/1H → **MTF** 30M/15M → **LTF** 5M/3M.

## Типы работы в POI (по длительности)

Continuation · Reversal · Range · SMT — работа в POI зависит от того, в рамках какого из этих четырёх сценариев формируется зона.

## Тайминги сессий (доп. срез, Kyiv, из бэктест-заметок за февраль)

| Период | Время |
|---|---|
| Frankfurt | 09:00–10:00 |
| London | 10:00–12:00 |
| Lunch | 12:00–14:00 |
| Pre-NY | 14:00–15:00 |
| NY | 15:00–16:30 |
| NYSE Open | 16:30–16:50 |
| AM (NY) | 16:50–19:00 |
| Lunch NY | 19:00–20:00 |
| Power Hour | 22:00–23:00 |

> «Power Hour» (последний час NY, 22:00-23:00 Kyiv) — не встречается в [[../05_Sessions_Timings/Session_Dynamics|Динамике сессий]]; специфика этого автора для DAX.

## Связанные заметки

- [[DAX_Strategy]] — другая, законченная бэктестируемая DAX-система (Bellissimo)
- [[../03_Tools/FVG]] · [[../03_Tools/Rejection_Block]]
- [[../05_Sessions_Timings/Session_Dynamics]]
- [[../07_POI/Context_BIAS_POI]] — FTA
