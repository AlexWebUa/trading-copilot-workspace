---
title: Market Maker Buy/Sell Model
tags: [bias, market-maker, model, liquidity, ict]
aliases: [Market Maker Model, MMBM, Market Maker B/S Model, MM Buy Model, MM Sell Model]
sources: [raw_notion/Market_Maker_BS_Model.md]
status: defined
updated: 2026-04-18
---

# Market Maker Buy/Sell Model

Шаблонная модель поведения маркет-мейкера: структурированная последовательность фаз, в которой Smart Money накапливает и распределяет позицию. Существует в двух зеркальных версиях — Buy (лонговая) и Sell (шортовая).

## Market Maker Buy Model (бычий)

| Шаг | Фаза | Описание |
|---|---|---|
| 1 | **Consolidation** | Первоначальная консолидация. Не одна-три свечи — серия свечей, формирующих диапазон |
| 2 | **Run to Support** | Пробой нижней границы консолидации → новая краткосрочная консолидация. Возможна коррекция обратно: сильная реакция = «тяжёлый» рынок, продолжит вниз. Вход: в OTE или после рейда краткосрочного хая |
| 3 | **Smart Money Reversal** | Цена достигает ключевой зоны (OB / BB / FVG) и разворачивается. SMT-дивергенция с коррелируемым активом = подтверждение |
| 4 | **Accumulation / Low Risk Buy** | Малая консолидация после реакции от зоны. Вход: в OTE или после рейда краткосрочного лоя |
| 5 | **Re-accumulation** | Повторная зона накопления. Дополнительный вход на тех же условиях |
| 6 | **Distribution** | Цена торгуется выше первоначальной консолидации. Распределение позиций |

> Шагов 4–5 (консолидаций) может быть несколько — каждая даёт повторный вход.

## Market Maker Sell Model (медвежий)

| Шаг | Фаза | Описание |
|---|---|---|
| 1 | **Consolidation** | Первоначальная консолидация (серия свечей) |
| 2 | **Run to Resistance** | Пробой верхней границы консолидации → новая краткосрочная консолидация. Если коррекции нет — вход в OTE или после рейда краткосрочного лоя |
| 3 | **Smart Money Reversal** | Цена достигает ключевой зоны (OB / BB / FVG) и разворачивается. SMT-дивергенция = подтверждение |
| 4 | **Distribution / Low Risk Sell** | Малая консолидация после реакции. Вход: в OTE или после рейда краткосрочного хая |
| 5 | **Re-distribution** | Повторная зона распределения. Дополнительный вход |
| 6 | **Distribution** | Цена торгуется ниже первоначальной консолидации |

## Ключевые наблюдения

- Модель фрактальна: применима на любом таймфрейме.
- Второй шаг (Run to Support/Resistance) = манипуляция в PO3-логике.
- SMT-дивергенция в шаге 3 — сильнейшее подтверждение разворота.
- Коррекция в шаге 2 к исходной консолидации без реакции → дополнительный вход.

## Связанные заметки

- [[../05_Sessions_Timings/PO3_AMD|PO3 / AMD (Power of Three)]]
- [[../01_Concepts/Accumulation_Phase|Accumulation / Re-accumulation]]
- [[../01_Concepts/Distribution_Phase|Distribution / Re-distribution]]
- [[../03_Tools/SMT_Divergence|SMT Divergence]]
- [[../03_Tools/Order_Block|Order Block]]
- [[../06_Bias_Templates/ICT_Daily_Bias|ICT Daily Bias]]
- [[../99_Glossary/Glossary#M|Глоссарий: MMBM]]
