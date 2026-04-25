---
title: Breaker Block (BB)
tags: [tool, poi]
aliases: [BB, Breaker Block, Брейкер-блок]
sources: [raw_notion/Breaker_Block.md]
status: defined
updated: 2026-04-18
---

# Breaker Block (BB)

**Breaker Block** — аналог [[Order_Block|Order Block]], но **полностью прошит** Imbalance/FVG-свечой. Зона, где произошёл явный перехват инициативы — старая позиция сломана, блок переработан в противоположную функцию (был сопротивлением → стал поддержкой и наоборот).

## Правила использования

1. **Связка с FVG 0.5**: лучший сценарий — торговать **Breaker + FVG 50%** (см. [[../02_Market_Structure/Price_Delivery_Rebalancing#Уровни реакции внутри FVG|C.E.]]).
2. **Любой таймфрейм** — BB работает на всех ТФ.
3. **Только со структурой**: без контекста [[../02_Market_Structure/Market_Structure|Market Structure]] зона слабая.
4. **Стоп-лосс**: за фитиль свечи BB.

> ⚠️ BB — редкая формация. По оценке автора-источника, встречается в торговле нечасто.

## Связанные заметки

- [[Order_Block]] — базовая зона спроса/предложения (BB = прошитый OB)
- [[FVG]] — связка BB + FVG 50% как оптимальная модель
- [[Mitigation_Block]] · [[Rejection_Block]] — родственные блоки
- [[../02_Market_Structure/Market_Structure]] — контекст для BB
- [[../07_POI/POI]]
- [[../99_Glossary/Glossary#B|Глоссарий: BB]]
