---
title: Fibonacci, Premium/Discount, OTE
tags: [tool, poi]
aliases: [Fibonacci, Premium, Discount, OTE, Optimal Trade Entry, Premium Zone, Discount Zone]
sources: [raw_notion/Fibonacci_PremiumDiscount_OTE.md, course-archiver/output/DT_MATERIAL_50/block-2/notion_1.md]
status: defined
updated: 2026-08-05
---

# Fibonacci, Premium/Discount, OTE

## Premium / Discount Zones

Наиболее **выгодные диапазоны** для набора позиции, базовая концепция **Smart Money**:

- **Smart Money покупает в Discount** (нижняя половина диапазона).
- **Smart Money продаёт в Premium** (верхняя половина диапазона).

### Разметка

Инструмент: **«Коррекция по Фибоначчи»**.
Натягивается от **начала тренда** до **его окончания**.

Настройки уровней: `0`, `0.5`, `1`.

| Уровень | Интерпретация |
|---------|---------------|
| `0` | Начало движения |
| `0.5` | **Equilibrium** — граница Premium/Discount |
| `1` | Окончание движения |

- **Ниже 0.5 → Discount** (для лонгов).
- **Выше 0.5 → Premium** (для шортов).

## OTE (Optimal Trade Entry)

**Более детальная точечная зона** внутри Premium/Discount.

Настройки уровней Fib:

- `0.620`
- `0.705`
- `0.790`

Идеальная точка входа ICT находится в этом узком коридоре.

## Правила использования

- Fib **один не работает** — служит **фильтром зоны**, внутри которой ищутся факторы входа (OB, FVG, BB, RB, SMT и т.д.).
- Без контекста (структура, bias, ликвидность) применение бессмысленно.
- На разных ТФ Fib применяется **независимо**, но даёт лучший эффект при **синхронизации** HTF Premium/Discount с LTF OTE.

## Связанные заметки

- [[Order_Block]] · [[FVG]] · [[Breaker_Block]] — факторы входа внутри Discount/Premium
- [[Liquidity]] — ликвидность как цель из Premium/Discount
- [[../06_Bias_Templates/ICT_Daily_Bias]] — контекст для применения Fib
- [[../99_Glossary/Glossary#O|Глоссарий: OTE]]
- [[../99_Glossary/Glossary#P|Глоссарий: Premium/Discount]]
