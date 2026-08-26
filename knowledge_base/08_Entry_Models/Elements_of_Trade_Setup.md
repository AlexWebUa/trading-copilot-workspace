---
title: Elements of Trade Setup
tags: [entry, concept, framework, market-maker]
aliases: [Elements of Trade Setup, Элементы торгового сетапа]
sources: [course-archiver/output/DT_MATERIAL_50/fundamental_-_Elements_of_Trade_Setup/notion.md]
status: defined
updated: 2026-08-05
---

# Elements of Trade Setup

Любой торговый сетап можно описать через **4 типа контекста** цены (что делает рынок сейчас) + **набор POI-инструментов** (за что цепляться внутри этого контекста). Framework предваряется тезисом о природе доставки цены:

> Маркет-мейкер — свой на каждом рынке (Форекс — центробанки, индексы — американские биржи, крипто — фонды). «Ликвидность» в контексте SMC — это не стоп случайного ритейл-трейдера, а пулы фондов/банков/финансовых учреждений. ~90% движения цены на графике — алгоритмическая доставка (не факт, что все крупные игроки прибыльны).

## 4 типа контекста

| Контекст | Что это | На что указывает | Что искать |
|---|---|---|---|
| **Expansion** | Цена агрессивно реагирует и уходит от [[../03_Tools/Fibonacci_Premium_Discount_OTE#\|Equilibrium]] внутри консолидации | Резкий выход из диапазона = агрессия, ММ готов раскрыть предполагаемую модель движения | [[../03_Tools/Order_Block\|Order Block]], оставленный ММ около Equilibrium |
| **Retracement** | Цена двигается назад внутрь недавно созданного range | Агрессия направлена на тест неэффективных уровней | [[../03_Tools/FVG\|FVG]] и Liquidity Voids |
| **Reverse** | Полноценное разворотное движение, противоположное текущему, с характерной манипуляцией | Цена достигла зоны стопов → значительное движение должно развернуться | Пулы ликвидности за старым high/low |
| **Consolidation** | Цена в range без агрессии в любую сторону | ММ разрешает набор ордеров с обеих сторон → готовится основное движение | Импульсивный уход от Equilibrium (середина range) |

## Логика: всё начинается с Consolidation

Формирование заявок на ордера, которые будут сняты позже, происходит именно в фазе консолидации — это исходная точка цикла. Из неё цена уходит в **Expansion**, тестирует через **Retracement**, и либо продолжает контекст, либо даёт **Reverse**.

## Точки опоры внутри каждого контекста

**Контекстные элементы** (типы движения): Expansion, Retracement, Reverse, Consolidation — см. таблицу выше.

**POI-элементы** (за что цепляться внутри order flow):
- [[../03_Tools/Order_Block|Order Blocks]]
- [[../03_Tools/FVG|FVG]] & Liquidity Voids
- [[../03_Tools/Liquidity|Liquidity Pools]] & Stop Runs
- Equilibrium (середина диапазона/range)

## Связанные заметки

- [[Entry_Models|Entry Models — концептуальный обзор]]
- [[../07_POI/POI|POI — определение и отбор]]
- [[../06_Bias_Templates/Market_Maker_Model|Market Maker Buy/Sell Model]] — более детализированная 6-шаговая версия того же принципа накопления/распределения
- [[../05_Sessions_Timings/PO3_AMD|PO3 / AMD]]
- [[../03_Tools/Fibonacci_Premium_Discount_OTE|Equilibrium / Premium-Discount]]
- [[../99_Glossary/Glossary#E|Глоссарий: Expansion]]
