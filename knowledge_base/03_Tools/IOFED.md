---
title: IOFED (Institutional Order Flow Entry Drill)
tags: [tool, entry, rule]
aliases: [IOFED, Institutional Order Flow Entry Drill]
sources: [raw_notion/IOFED.md]
status: defined
updated: 2026-04-18
---

# IOFED (Institutional Order Flow Entry Drill)

**IOFED** — тест FVG **от его начала** (ближайший край) до **C.E.** ([[../02_Market_Structure/Price_Delivery_Rebalancing#C.E.|consequent encroachment]] — 50 % FVG).

Это **идеальная точка входа ICT** внутри [[FVG]].

## Ключевая идея

- Цена **не всегда заходит до середины FVG** (C.E.) и тем более до **FullFill** (100 %).
- Если выше по структуре уже был **FullFill соседнего FVG**, то **достаточно теста от края FVG до C.E.** — именно это и есть IOFED.

## Три уровня теста FVG

| Глубина теста | Условия | Сценарий использования |
|---------------|---------|------------------------|
| **IOFED** (от края до C.E., ≈50 %) | Выше уже отработан FullFill соседнего FVG | Агрессивный вход «по драйверу» |
| **C.E.** (50 %) | Стандартный тест | Базовая точка входа |
| **FullFill** (100 %) | Консервативный тест | Максимально безопасный вход |

> Выбор глубины зависит от **контекста**: наличия FullFill выше/ниже, силы импульса, подтверждающих факторов ([[SMT_Divergence|SMT]], [[../02_Market_Structure/Market_Structure_Shift|MSS]]).

## Пример (из исходника)

Цена осуществила IOFED — вход произошёл на касании C.E. FVG, поскольку **выше уже присутствовал FullFill** предыдущего FVG, и продолжение теста до 100 % не требовалось.

## Практическое правило

- IOFED = **агрессивная модель входа** в рамках ICT.
- Применять **только при подтверждённом FullFill выше/ниже** — без этого снижается вероятность отработки.
- На LTF служит **entry model**, на HTF — **маркером силы движения**.

## Связанные заметки

- [[FVG]] — базовая зона для IOFED
- [[../02_Market_Structure/Price_Delivery_Rebalancing]] — IOFED / C.E. / FullFill как иерархия
- [[BPR]] · [[IFVG]] — альтернативные модели работы с FVG
- [[../99_Glossary/Glossary#I|Глоссарий: IOFED]]
