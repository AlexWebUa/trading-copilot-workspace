# Протокол исследования торговых стратегий
## Trading Co-Pilot · Crypto Futures · 2026
_Актуализирован 2026-04-28 по итогам финализации торговых правил._

---

## 1. Цель

Найти **3–5 торговых сетапов** с наибольшим реальным edge на крипто-фьючерсах Binance,
которые в совокупности обеспечивают:

| Параметр | Цель |
|---|---|
| Сделок в месяц | 5–20 |
| Прибыль в месяц | ≥ +7.5% к депозиту |
| Риск на сделку | 0.5–1% (зависит от неопределённости сделки) |
| Минимальный RR | **1.5** |
| Drawdown | ≤ 15% по журналу |

**Принцип отбора:** высокий WR приоритетнее высокого RR.
Сетап с WR 65% и avg RR 1.8 лучше сетапа с WR 45% и avg RR 3.5 —
оба дают схожий expectancy, но первый создаёт меньше стресса и меньше комиссий.

---

## 2. Ключевые сведения

### 2.1 Инструменты для тестирования

| Тикер | Приоритет | Причина |
|---|---|---|
| BTCUSDT | Первичный | Самая чистая структура, benchmark |
| ETHUSDT | Первичный | SMT-коррелят BTC (BTC/ETH — единственная активная SMT-пара) |
| SOLUSDT | Вторичный | Высокая волатильность, хорошо реагирует на ICT-уровни |
| BNBUSDT | Вторичный | Независимое движение, дополнительная диверсификация |

Все инструменты — **Binance Perpetual Futures**.

### 2.2 Таймфреймы

| Роль | TF | Назначение в движке |
|---|---|---|
| HTF контекст | W1 / D1 | Глобальный bias, ключевые пулы и имбалансы (HTFConditions) |
| Рабочий ТФ | H4 / H1 | Идентификация POI, sweep, BOS (основные Conditions) |
| Уточнение | M30 / M15 | Уточнение зон внутри HTF POI; локальная структура; допустимы для входа |
| **Вход / Выход** | **M5 / M3 / M1** | **entry_conditions; exit simulation на тех же барах** |

**Принцип:**
- W1/D1 определяет КУДА идёт рынок глобально
- H4/H1 определяет ГДЕ входить (зона/уровень)
- M30/M15/M5/M1 определяет КОГДА входить (паттерн подтверждения)

**Синхронизация:** чем больше последовательных ТФ движутся в одном направлении — тем лучше условия для сделки. Максимальный синхрон W1↔D1↔H4↔H1 = наилучшие условия.

### 2.3 Сессии (все времена — Киев)

| Сессия | Время |
|---|---|
| Азиатская | 02:00–10:00 |
| Франкфуртская | 09:00–10:00 |
| Лондонская | 10:00–18:00 |
| Нью-Йоркская | 15:00–22:00 |

OTT (основное торговое окно): **09:00–17:00 Киев**.

### 2.4 Математическая рамка для отбора

Для совокупности 3–5 сетапов, торгуемых одновременно:

```
Суммарный monthly P&L (%) = Σ [ trades_per_month(i) × expectancy(i) × risk_pct(i) ]
Цель: ≥ 7.5%

Минимальные условия для одного сетапа:
  expectancy ≥ 0.5R   (слабый, но вносит вклад)
  expectancy ≥ 0.75R  (хороший)
  expectancy ≥ 1.0R+  (отличный, таргет для swing-сетапов)
```

Примеры комбинаций достигающих цели:
- 2 сетапа × 5 сделок × 0.75R × 1% = 7.5%  ✓
- 3 сетапа × 3 сделки × 1.0R × 0.5–1% = 4.5–9%  ✓
- 1 swing-сетап × 2 сделки × 3.0R × 1% + 2 intraday × 4 сделки × 0.6R × 1% = 10.8%  ✓

### 2.5 Статистические требования

- **Минимальная выборка:** отменена (решение трейдера, 2026-08-22) — качество важнее количества.
  Взамен: доверительный интервал на winrate обязателен, чтобы малая выборка была видна в самом отчёте.
- **Walk-forward обязателен:** 70% IS / 30% OOS для каждого правила.
- **OOS критерий:** PF(OOS) ≥ 0.80 × PF(IS). Деградация >20% → правило нестабильно.
- **Ablation обязателен:** для топ-5 правил. Условие считается шумом если его удаление
  не снижает PF(IS) более чем на 0.1 → убрать, упростить правило.

### 2.6 Рамка исследования (согласована 2026-08-22)

- **Инструмент:** только BTCUSDT. Один инструмент = меньше сравнений = меньше случайных «edge».
- **Риск на сделку:** 1% всегда, во всех сетапах.
- **Минимальный RR:** 1.8 для открытия любой сделки (`SetupRule.min_rr`, глобальный дефолт).
- **12 синтетических правил** (`rules.py` + `rules_orderflow.py`) в исследование стратегий **не входят** —
  они не описывают ничью методологию; код остаётся как есть.
- **Незавершённые сделки** исключаются из статистики, но выводятся строкой «N сделок не завершилось».
- **Множественные сравнения:** набор правил фиксируется до прогона и не расширяется по ходу;
  walk-forward скользящими фолдами вместо одного 70/30; **«edge не найден» — публикуемый результат**,
  а не повод крутить пороги.

---

## 3. Кандидаты на исследование

### 3.1 Уже написанные правила (немедленный запуск после апгрейда движка)

**Группа A — Базовые (BUILTIN_RULES):**
```
fvg_ob_long          H1: MS bullish + BOS + OB + FVG → fvg_ce вход
sweep_bos_long       H1: MS bullish + sweep SSL + BOS + FVG → fvg_ce
ob_fvg_short         H1: MS bearish + sweep BSL + BOS + OB + FVG → fvg_ce
```

**Группа B — Orderflow (ORDERFLOW_RULES):**
```
ob_in_hvn_long        H1: Группа A + OB перекрывает HVN
poc_discount_bos_long H1: Группа A + цена ниже POC (value area)
lvn_acceleration_long H1: BOS с импульсом ≥1.5 ATR + цена в LVN
vah_rejection_short   H1: MS bearish + BOS + FVG + цена выше POC
(+ остальные из rules_orderflow.py)
```

### 3.2 Новые Multi-TF правила (после Change 1)

Каждое правило строится по трём слоям: HTFConditions (W1/D1 или H4 bias) → Conditions (H4/H1 сетап) → entry_conditions (M5/M3/M1 триггер).

**MT-1: H4 Bias → H1 Sweep+FVG → 5m BOS (классический 1H3M)**
```
HTFConditions (H4):
  detect_market_structure.state == bullish
  detect_order_block.obs.0.type == bullish (H4 OB ниже как цель)
Conditions (H1):
  detect_liquidity.recent_sweeps.0.side == sellside (снятие SSL на H1)
  detect_bos.direction == bullish (H1 BOS после sweep)
  detect_fvg.fvgs.0.type == bullish, fill_state in [untouched, IOFED]
entry_conditions (5m):
  detect_bos.direction == bullish (5m слом структуры внутри H1 FVG/OB)
  detect_fvg.fvgs.0.type == bullish (5m FVG после 5m BOS)
entry_tf: 5m, entry_after_ltf: signal_close
SL: ob (граница H1 OB), TP1: rr:1.5 (80%), TP2: liquidity (20%)
Session: frankfurt, london, ny_am
```

**MT-2: H4 OB → H1 BOS → 5m Sponsored Candle (deep pullback)**
```
HTFConditions (H4):
  detect_market_structure.state == bullish
  detect_order_block.obs.0.is_mitigated == False (активный H4 OB)
  detect_fib_zones: цена в discount
Conditions (H1):
  detect_bos.direction == bullish (разворот на H1 в H4 OB)
  detect_fvg.fvgs.0.type == bullish
entry_conditions (5m):
  detect_sponsored_candle.sponsored_obs.0.type == bullish (sweep + SC на 5m)
entry_tf: 5m, entry_after_ltf: signal_close
SL: ob (H1 OB граница), TP1: rr:2.0 (80%), TP2: rr:5.0 (20%)
risk_pct: 0.5, max_entry_wait_bars_ltf: 60
```

**MT-3: D1 Structure → H4 Sponsored Candle → 5m BOS (swing)**
```
HTFConditions (D1):
  detect_market_structure.state == bullish
  detect_fib_zones: цена в discount (D1 уровень)
Conditions (H4):
  detect_sponsored_candle.sponsored_obs.0.type == bullish
  detect_liquidity.recent_sweeps.0.side == sellside
entry_conditions (5m):
  detect_bos.direction == bullish
entry_tf: 5m, entry_after_ltf: signal_close
SL: ob (H4 SC граница), TP1: rr:3.0 (80%), TP2: rr:8.0 (20%)
risk_pct: 0.5, max_bars_open: 120 (≈30 дней на H4)
```

**MT-4: H1 OB → 1m BOS + FVG (точный скальп внутри зоны)**
```
HTFConditions (H4):
  detect_market_structure.state == bullish
Conditions (H1):
  detect_order_block.obs.0.type == bullish (H1 OB — Sponsored Candle)
  detect_order_block.obs.0.is_mitigated == False
  detect_fib_zones: цена в discount (H1 swing)
entry_conditions (1m):
  detect_liquidity.recent_sweeps exists (1m sweep SSL)
  detect_bos.direction == bullish (1m BOS после sweep)
  detect_fvg.fvgs.0.type == bullish (1m FVG)
entry_tf: 1m, entry_after_ltf: signal_close, max_entry_wait_bars_ltf: 30
SL: swing (1m), TP1: rr:1.5 (80%), TP2: rr:3.0 (20%)
Session: frankfurt, london, ny_am, ny_pm
```

**MT-5: H4 Compression → H1 cBOS → 5m next_open (volatility expansion)**
```
HTFConditions (H4):
  detect_compression.active_compressions exists
  detect_market_structure.state == bullish
Conditions (H1):
  detect_bos.type == cBOS, displacement_atr_multiple >= 1.5
  detect_fvg.fvgs.0.type == bullish
entry_conditions (5m): []  (пустые — вход на первой 5m свече после H1 cBOS)
entry_tf: 5m, entry_after_ltf: next_open
SL: atr:1.2, TP1: rr:2.0 (80%), TP2: rr:5.0 (20%)
```

**MT-6: H4 Breaker Block → H1 BOS → 5m BOS**
```
HTFConditions (H4):
  detect_breaker_block.breakers.0.type == bullish
Conditions (H1):
  detect_bos.direction == bullish
  detect_fvg.fvgs.0.type == bullish
entry_conditions (5m):
  detect_bos.direction == bullish
entry_tf: 5m, entry_after_ltf: signal_close
SL: ob, TP1: rr:2.0 (80%), TP2: rr:5.0 (20%)
```

> Примечание: Mitigation Block не используется в стратегии → MT-6 с Mitigation Block из предыдущей версии удалён. Нумерация сдвинута.

---

## 4. Методология исследования

### Фаза 1 — Baseline (сразу после апгрейда движка)

**Задача:** понять реальную performance существующих однотаймфреймовых правил.

1. Запустить `compare_rules()` на всех BUILTIN + ORDERFLOW правилах.
   - Инструменты: BTCUSDT, ETHUSDT, SOLUSDT
   - TF: H1 (основной), H4 (swing)
   - Период: последние 5000 баров (~7 мес H1, ~2.3 года H4)
   - `fee_bps=8.0`, `walk_forward_split=0.70`
2. Отсев по критериям: PF(IS) ≥ 1.3 AND trades ≥ 30 AND OOS не деградирует >20%.
3. Для прошедших отсев: `ablate_conditions()` → убрать шум.
4. Документировать все результаты в таблице (Раздел 5.1).

**Ожидаемый результат:** 2–4 правила переходят в Фазу 2. Остальные — архив с причиной отсева.

### Фаза 2 — Multi-TF Rules Research

**Задача:** протестировать Multi-TF правила (MT-1 … MT-6) + варианты.

1. Для каждого правила из Раздела 3.2:
   a. Запустить на BTCUSDT, 5000 баров H1, walk-forward 70/30.
   b. Если trades(IS) ≥ 15 → запустить на ETHUSDT, SOLUSDT.
   c. Если PF(OOS) ≥ 1.2 на 2+ инструментах → переходит в Фазу 3.
2. Для перспективных правил: parameter sweep по tp_levels (RR 1.5/2.0/3.0/5.0).
3. Session breakdown: если одна сессия даёт PF > 1.5 при других < 1.0 → добавить `required_session`.
4. Sync-level тест: сравнить варианты правила с H4 bias vs D1+H4 bias — даёт ли доп. фильтр улучшение?

**Ожидаемый результат:** 5–8 правил с достаточной статистикой.

### Фаза 3 — Финальный отбор и портфельный анализ

**Задача:** выбрать 3–5 правил которые вместе закрывают цель.

1. Для каждого финалиста: полный backtest на всех 4 инструментах за максимальный период.
2. Проверка портфельной математики:
   ```
   Σ [ freq_per_month × expectancy × risk_pct ] ≥ 7.5%
   max_concurrent_drawdown ≤ 15%  (симулировать одновременную просадку всех правил)
   ```
3. Проверка частотности: `session_breakdown` → убедиться что 5–20 сделок/мес реалистичны.
4. Ручная проверка 10–15 сделок из OOS выборки каждого финалиста на графике.
5. Финальная документация SetupRule в BUILTIN_RULES.

---

## 5. Формат документирования результатов

### 5.1 Таблица результатов (обновляется после каждого прогона)

Файл: `research/results_log.md`

```markdown
| Rule | Instrument | TF | N(IS) | WR(IS) | PF(IS) | E(R)(IS) | N(OOS) | PF(OOS) | Status |
|---|---|---|---|---|---|---|---|---|---|
| sweep_bos_long | BTCUSDT | H1 | 45 | 58% | 1.42 | +0.52 | 18 | 1.21 | ✅ Фаза 2 |
| fvg_ob_long | BTCUSDT | H1 | 67 | 51% | 1.18 | +0.31 | 22 | 0.89 | ❌ OOS деградация |
```

### 5.2 Карточка сетапа (финалист)

Файл: `research/setups/[rule_name].md`

```markdown
## [Название сетапа]

**Описание:** Одно предложение — что ловит, почему работает.

**Logic:**
- HTF bias (W1/D1 или H4): ...
- Trigger (H4/H1): ...
- Confirmation (M5/M1): ...
- Entry: ... / SL: ... / TP1 (80%): ... / TP2 (20%): ...

**SetupRule (production):**
[код SetupRule]

**Backtest Results:**
| Instrument | TF | Period | N | WR% | PF | E(R) | avg_bars | monthly_trades |
|---|---|---|---|---|---|---|---|---|
| BTCUSDT | H1 | 2025-01 → 2025-08 | 52 | 60% | 1.61 | +0.74 | 18 | ~7 |
| ETHUSDT | H1 | ... | ... | ... | ... | ... | ... | ... |

**Walk-Forward:**
| Split | IS PF | OOS PF | Verdict |
|---|---|---|---|
| 70/30 | 1.61 | 1.38 | ✅ Stable |

**Session breakdown:**
Лондон: 65% сделок, PF 1.9
Нью-Йорк: 25% сделок, PF 1.3
Азия: 10% сделок, PF 0.8 → исключить?

**Ablation (load-bearing conditions):**
[таблица из print_ablation()]

**Risk params:**
- risk_pct: 1.0%
- Expected monthly contribution: ~5 сделок × 0.74R × 1% = 3.7%

**Known weaknesses:**
- ...

**Ручная проверка:** 12/15 OOS сделок визуально соответствуют логике сетапа.
```

### 5.3 Итоговый отчёт

Файл: `research/FINAL_SELECTION.md`

```markdown
## Финальные 3–5 сетапов

### Портфельная математика
[таблица: rule × freq × expectancy × risk_pct = monthly contribution]
[суммарная цель vs факт]

### Матрица корреляций
[когда все правила могут быть в просадке одновременно?]

### Production SetupRules
[финальные определения для BUILTIN_RULES]

### Следующий шаг
[Forward test план: 30 сделок в demo/paper trading]
```

---

## 6. Критерии завершения исследования

Исследование завершено когда:

- [ ] Найдено 3–5 правил с PF(OOS) ≥ 1.3 на 2+ инструментах
- [ ] Суммарный ожидаемый monthly P&L ≥ 7.5% (с учётом fee_bps=8)
- [ ] Суммарная частота 5–20 сделок в месяц достигается
- [ ] Максимальная одновременная просадка ≤ 15%
- [ ] Ручная проверка ≥ 10 OOS сделок на каждый финалист
- [ ] Все финальные правила добавлены в BUILTIN_RULES с комментариями
- [ ] FINAL_SELECTION.md заполнен и задокументирован

---

## 7. Что НЕ делаем в этом исследовании

- ❌ Не оптимизируем параметры детекторов (swing_lookback, min_width_atr и т.д.) —
  ведёт к overfitting. Параметры остаются дефолтными.
- ❌ Не тестируем >20 правил одновременно без предварительного логического отбора.
- ❌ Не принимаем решения только по IS метрикам — OOS обязателен.
- ❌ Не включаем BNB/SOL в baseline (только BTCUSDT) — сначала находим edge на BTC,
  потом подтверждаем на альтах.
- ❌ Не используем Mitigation Block в правилах — не является частью стратегии.
- ❌ Не используем SMT для крипты как условие в SetupRule — SMT актуален только для
  акций (BTC/ETH корреляция используется лишь для ручного контекста, не в коде).

---

## 8. Зависимости (что должно быть готово до старта)

| Зависимость | Статус | Детали |
|---|---|---|
| Change 2: LTF Entry + Exit (1m/5m) | ✅ Готово | `entry_tf`, `entry_conditions`, `_LTF_SCAN` state в engine.py |
| Change 1: Multi-TF HTF conditions | ✅ Готово | `HTFCondition`, `htf_conditions`, `_evaluate_htf_conditions` |
| Change 3: Partial TP (80/20) | ✅ Готово | `TPLevel`, `tp_levels`, `partial_exits` |
| Change 4: Time-based exit | ✅ Готово | `max_bars_open` в SetupRule и engine |
| Change 5: Fees + Variable risk | ✅ Готово | `fee_bps`, `risk_pct`, `pnl_pct_series` в BacktestSummary |
| fetch_ohlcv_batched | ✅ Готово | Пагинация, cap 100k баров, sleep 0.1s |

**Все зависимости выполнены. 279 тестов проходят. Исследование можно запускать.**

> ⚠️ **Синтаксис операторов в SetupRule/HTFCondition:** используется `eq` вместо `==`,
> `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `not_in`, `exists`, `true`, `false`.
> Псевдокод правил в Разделе 3.2 написан для читаемости — при реализации
> в Python заменяй `==` → `eq`, `!=` → `ne` и т.д.
