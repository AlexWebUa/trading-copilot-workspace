---
title: STB / BTS (Sell to Buy / Buy to Sell)
tags: [setup, poi, zone, liquidity, structure]
aliases: [STB, BTS, Sell to Buy, Buy to Sell, STB/BTS]
sources: [raw_notion/STBBTS.md, course-archiver/output/DT_MATERIAL_50/block-3/notion_3.md]
status: defined
updated: 2026-08-05
---

# STB / BTS (Sell to Buy / Buy to Sell)

**STB/BTS** — зона спроса или предложения, графически выглядящая как **диапазон от BOS/cBOS до ближайшего экстремума** (low для лонга / high для шорта). Двойное назначение: POI для маркировки контекста и модель для входа.

## Определение

- **BTS (Buy to Sell)** — зона продажи: диапазон от bullish BOS/cBOS вверх до hig (где цена «перешла» в продажи).
- **STB (Sell to Buy)** — зона покупки: диапазон от bearish BOS/cBOS вниз до low (где цена «перешла» в покупки).

## Правила валидации

1. **Движение снимает ликвидность** — обязательно.
2. **Sell- и Buy-движения должны быть импульсными** — отсутствие рваных/слабых свечей.
3. **Наличие имбаланса (FVG) внутри** зоны.

## Применение

| Контекст | Использование |
|---|---|
| HTF (старший ТФ) | POI для маркировки контекста — зона ожидания реакции |
| LTF (младший ТФ) | Вход: искать факторы (BOS, IMB, ликвидность) внутри зоны |

> STB/BTS как HTF-зона: внутри неё ищутся LTF-факторы для входа — аналогично работе в любом POI.

## Связанные заметки

- [[../07_POI/POI|POI — определение и правила отбора]]
- [[../03_Tools/Order_Block|Order Block]]
- [[../03_Tools/FVG|FVG (имбаланс)]]
- [[../02_Market_Structure/BOS|BOS / cBOS]]
- [[../03_Tools/Liquidity|Ликвидность (BSL/SSL)]]
- [[../99_Glossary/Glossary#S|Глоссарий: STBBTS]]
