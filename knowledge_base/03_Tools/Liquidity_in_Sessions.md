---
title: Liquidity in Sessions (сессионные пулы ликвидности)
tags: [tool, liquidity, session]
aliases: [Session Liquidity, Сессионная ликвидность, PWH, PWL, PDH, PDL, AH, AL, LH, LL]
sources: [raw_notion/Liquidity_in_sessions.md]
status: defined
updated: 2026-04-18
---

# Liquidity in Sessions

Сессионные хаи/лои — **ключевые пулы ликвидности** и одновременно **диапазоны для выхода из позиции**.

## Пулы по таймфреймам

### Previous Week (недельные)

| Тег | Расшифровка |
|-----|-------------|
| **PWH** | Previous Week High |
| **PWL** | Previous Week Low |

> При открытии новой недели цена охотится за хаями/лоями **прошлой недели**.

### Previous Day (дневные)

| Тег | Расшифровка |
|-----|-------------|
| **PDH** | Previous Day High |
| **PDL** | Previous Day Low |

> При открытии нового дня цена охотится за хаями/лоями **прошлого дня**.

### Previous Session (сессионные)

| Тег | Расшифровка |
|-----|-------------|
| **AH** | Asia High |
| **AL** | Asia Low |
| **LH** | London High |
| **LL** | London Low |

> На протяжении дня цена последовательно снимает границы **прошедших сессий**.

## Практическое применение

- **Вход**: сессионный пул как POI (после сбора → реакция → [[../02_Market_Structure/Market_Structure_Shift|MSS]] → вход).
- **Выход**: ближайший сессионный пул по направлению позиции — **логичная цель TP**.
- **Bias**: направление движения внутри дня часто определяется, **за каким пулом цена идёт следующим**.

## Связанные заметки

- [[Liquidity]] — общая природа ликвидности
- [[../05_Sessions_Timings/Sessions_Overview]] — Asia / London / NY окна
- [[../05_Sessions_Timings/PO3_AMD_Sessions]] — Manipulation снимает сессионные пулы
- [[CBDR]] — отклонения CBDR относительно D1 H/L
- [[../99_Glossary/Glossary#L|Глоссарий: Session Liquidity]]
