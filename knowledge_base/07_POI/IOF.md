---
title: Institutional Order Flow (IOF)
tags: [poi, iof, order-flow, entry, ltf]
aliases: [IOF, Institutional Order Flow, Институциональный ордер-флоу]
sources: [raw_notion/Institutional_Order_Flow_Как_пример_работы_в_POI_Углубленная_работа_в_POI_и_за_ее_пределами.md, course-archiver/output/DT_MATERIAL_50/block-5/notion_4.md]
status: defined
updated: 2026-08-05
---

# Institutional Order Flow (IOF)

**IOF** (Institutional Order Flow) — подвид Order Flow, появляющийся на **младшем таймфрейме** при тесте HTF POI или снятии крупных пулов ликвидности. Отличается от общего OF конкретным контекстом применения.

## IOF vs OF

| Понятие | Описание |
|---|---|
| **OF** | Общее понятие: способ доставки цены к цели через постоянную работу с ликвидностью |
| **IOF** | Подвид OF: конкретная последовательность LTF-паттернов при тесте HTF POI или снятии ликвидности |

## Элементы IOF

- **MS Shift** (Market Structure Shift) — смена структуры на LTF
- **Flip** — инверсия уровня (FVG / OB меняет функцию)
- **OF Break** — слом ордер-флоу
- **Rebalance** — ребалансировка (тест FVG / OB)
- **LG** — ликвидность-гэп / Liquidity Gap
- **Advanced MS** — продвинутая структура

## Формирование IOF (3 части)

**Part 1** — Реакция от зоны интереса:
- Ожидать MS Shift с инверсией (сдвиг структуры на LTF).
- Затем — ребалансировку или митигацию.
- Далее — работу с ликвидностью и формирование Advanced MS.

**Part 2** — Новый тайминг / достижение локальной цели:
- Оценить, что сформировалось внутри этого движения на HTF.
- Если сформирован «магнит» — ждать цену у свежесформированного IOF и начинать работу от него.

**Part 3** — Достижение новой зоны интереса:
- Применять ту же логику, что и в Part 1 (рекурсивно).

## Ключевое преимущество

IOF позволяет рассматривать **несколько моделей входа** в рамках одного движения: каждая новая POI, сформированная в ходе IOF, даёт дополнительную точку входа.

## Связанные заметки

- [[../07_POI/POI|POI — определение и отбор]]
- [[../07_POI/Work_in_POI|Работа внутри POI (TF-синхронизация)]]
- [[../02_Market_Structure/Market_Structure_Shift|Market Structure Shift (MSS)]]
- [[../03_Tools/FVG|Fair Value Gap]]
- [[../03_Tools/Liquidity|Ликвидность (BSL/SSL)]]
- [[../11_Trade_Management/Order_Flow|Order Flow (OF)]]
- [[../99_Glossary/Glossary#I|Глоссарий: IOF]]
