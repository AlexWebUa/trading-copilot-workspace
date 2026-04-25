---
title: Прогресс обработки исходников
tags: [index, meta, progress]
updated: 2026-04-18
---

# Прогресс анализа исходных файлов

Трекер статуса обработки исходных файлов из `raw_notion/`. При каждой сессии помечайте пройденные файлы и указывайте, в какую итоговую заметку БЗ был смёрджен контент.

**Легенда статусов**:
- `⬜ pending` — не анализировался
- `🟨 in_progress` — в работе
- `✅ analyzed` — полностью перенесён в БЗ
- `🔗 merged` — контент смёрджен в общую заметку (см. "target")
- `❌ skipped` — пустой/служебный файл, без смысловой нагрузки

**Правила**:
1. При обработке файла записывать `target:` — путь к итоговой заметке.
2. Если файл слит с другими — указать в `target:` общий итог + отметить `🔗 merged`.
3. Неоднозначности складывать в [[_Ambiguities]].

---

## Group 1 — Global Concepts & Visions → `01_Concepts/` (частично перенаправлены)

| # | Файл | Статус | Target |
|---|------|--------|--------|
| 1 | Intro.md | ✅ | [[01_Concepts/Wyckoff_Method]] |
| 2 | History_of_Creation.md | ✅ | [[04_Market_Profile/History_of_Market_Profile]] (перенаправлен — файл на самом деле про Market Profile) |
| 3 | What_You_Need_To_Know.md | ✅ | [[04_Market_Profile/VWAP_Basics]] (перенаправлен — файл на самом деле про VWAP) |
| 4 | Context.md | 🔗 | [[01_Concepts/Context_Determination]] (merged с #5) |
| 5 | КОНТЕКСТ_PashaTrltsk.md | 🔗 | [[01_Concepts/Context_Determination]] (merged с #4) |
| 6 | Yura_Pukaliak_-_Logic.md | ✅ | [[08_Entry_Models/Yura_Pukaliak_Entry_Logic]] (перенаправлен — это модель входа) |
| 7 | Narrative_Fix_Bellissimo.md | ✅ | [[09_Setups/Narrative_Fix_Bellissimo]] (stub — исходник только заголовок) |
| 8 | 1h3m_For_Students.md | 🔗 | [[09_Setups/1h3m_by_Bellissimo]] (merged с #9) |
| 9 | 1h3m_by_Bellisimo.md | 🔗 | [[09_Setups/1h3m_by_Bellissimo]] (merged с #8) |
| 10 | 1H3m_WinstonFX_Vision.md | ✅ | [[09_Setups/1h3m_by_WinstonFX]] (stub → defined; контент получен) |
| 11 | Dynamic_Trading_System_WinstonFX.md | ✅ | [[09_Setups/Dynamic_Trading_System_WinstonFX]] (stub — JS не захвачен) |

## Group 2 — Wyckoff / Фазы рынка → `01_Concepts/` + `04_Market_Profile/`

| # | Файл | Статус | Target |
|---|------|--------|--------|
| 12 | AccumulationRe-accumulation.md | ✅ | [[01_Concepts/Accumulation_Phase]] |
| 13 | DistributionRe-distribution.md | ✅ | [[01_Concepts/Distribution_Phase]] |
| 14 | Auction_Market_Theory.md | ✅ | [[04_Market_Profile/Auction_Market_Theory]] |

## Group 3 — Структура рынка → `02_Market_Structure/`

| # | Файл | Статус | Target |
|---|------|--------|--------|
| 15 | Market_Structure.md | ✅ | [[02_Market_Structure/Market_Structure]] |
| 16 | Advanced_Market_Structure.md | ✅ | [[02_Market_Structure/Advanced_Market_Structure]] |
| 17 | Advanced_Structure_Breakout.md | ✅ | [[02_Market_Structure/Advanced_Structure_Breakout]] |
| 18 | Market_Structure_Shift_Displacement.md | ✅ | [[02_Market_Structure/Market_Structure_Shift]] (MSS + Displacement в одной заметке) |
| 19 | Market_Structure_Range.md | ✅ | [[02_Market_Structure/Market_Structure_Range]] |
| 20 | BOS_variations.md | ✅ | [[02_Market_Structure/BOS]] (смёржен с BOS-разделом из Market_Structure) |
| 21 | Слабые_и_сильные_структурные_точки.md | ✅ | [[02_Market_Structure/Strong_Weak_Structural_Points]] |
| 22 | Эффективная_и_неэффективная_доставка_цены_Ребалансировка.md | ✅ | [[02_Market_Structure/Price_Delivery_Rebalancing]] |
| 23 | Fractals.md | ✅ | [[02_Market_Structure/Fractals]] |

## Group 4 — Инструменты анализа графика → `03_Tools/` ✅

| # | Файл | Статус | Target |
|---|------|--------|--------|
| 24 | Fair_Value_Gap.md | 🔗 | [[03_Tools/FVG]] (merged с #25) |
| 25 | 4H1H30M_FVG_-_Как_с_ними_работать.md | 🔗 | [[03_Tools/FVG]] (merged с #24, раздел «Синхронизация ТФ») |
| 26 | Inversion_Fair_Value_Gap_IFVG.md | ✅ | [[03_Tools/IFVG]] |
| 27 | BPR.md | ✅ | [[03_Tools/BPR]] |
| 28 | Breaker_Block.md | ✅ | [[03_Tools/Breaker_Block]] |
| 29 | Rejection_Block.md | ✅ | [[03_Tools/Rejection_Block]] |
| 30 | Mitigation_Block.md | 🔗 | [[03_Tools/Mitigation_Block]] (merged с #31) |
| 31 | Mitigation_How_it_can_be_used_in_indices.md | 🔗 | [[03_Tools/Mitigation_Block]] (merged с #30, раздел «3 сценария митигации») |
| 32 | Order_Block_DemandSupply_Zone.md | 🔗 | [[03_Tools/Order_Block]] (merged с #33) |
| 33 | Зона_спросапредложения_как_сбалансированный_диапазон.md | 🔗 | [[03_Tools/Order_Block]] (merged с #32, раздел «OB как сбалансированный диапазон») |
| 34 | GAP.md | ✅ | [[03_Tools/GAP]] |
| 35 | CBDR.md | ✅ | [[03_Tools/CBDR]] |
| 36 | Compression.md | ✅ | [[03_Tools/Compression]] |
| 37 | Liquidity.md | ✅ | [[03_Tools/Liquidity]] |
| 38 | Structural_Liquidity.md | ✅ | [[03_Tools/Structural_Liquidity]] |
| 39 | Liquidity_in_sessions.md | ✅ | [[03_Tools/Liquidity_in_Sessions]] |
| 40 | SMT_Divergence.md | ✅ | [[03_Tools/SMT_Divergence]] |
| 41 | Fibonacci_PremiumDiscount_OTE.md | ✅ | [[03_Tools/Fibonacci_Premium_Discount_OTE]] |
| 42 | Golden_Rain.md | ✅ | [[03_Tools/Golden_Rain]] (stub — исходник пустой) |
| 43 | Sponsorsponsorshipsponsored_candle.md | ✅ | [[03_Tools/Sponsored_Candle]] |
| 44 | Poor_HighLow.md | ✅ | [[04_Market_Profile/Poor_High_Low]] (перенаправлен — относится к Market Profile) |
| 45 | IOFED.md | ✅ | [[03_Tools/IOFED]] |

## Group 5 — Market Profile / VWAP → `04_Market_Profile/` ✅

| # | Файл | Статус | Target |
|---|------|--------|--------|
| 46 | Composite_Market_Profile.md | ✅ | [[04_Market_Profile/Composite_Market_Profile]] |
| 47 | Profile_Logic.md | ✅ | [[04_Market_Profile/Profile_Logic]] |
| 48 | Profile_for_Crypto.md | 🔗 | [[04_Market_Profile/Profile_by_Instrument]] (merged с #49, #50) |
| 49 | Profile_for_EURO_Indices.md | 🔗 | [[04_Market_Profile/Profile_by_Instrument]] (merged с #48, #50) |
| 50 | Profile_for_USA_Indices.md | 🔗 | [[04_Market_Profile/Profile_by_Instrument]] (merged с #48, #49) |
| 51 | POC_Test.md | 🔗 | [[04_Market_Profile/POC]] (merged с #52) |
| 52 | Point_of_Control.md | 🔗 | [[04_Market_Profile/POC]] (merged с #51) |
| 53 | Value_Area.md | 🔗 | [[04_Market_Profile/Value_Area]] (merged с #54, #55, #56) |
| 54 | VA_Breakout.md | 🔗 | [[04_Market_Profile/Value_Area]] (merged с #53, #55, #56) |
| 55 | Move_inside_VA.md | 🔗 | [[04_Market_Profile/Value_Area]] (merged с #53, #54, #56) |
| 56 | Move_outside_VA.md | 🔗 | [[04_Market_Profile/Value_Area]] (merged с #53, #54, #55) |
| 57 | TPO_vs_STPO.md | ✅ | [[04_Market_Profile/TPO_STPO]] |
| 58 | Single_Prints.md | ✅ | [[04_Market_Profile/Single_Prints]] |
| 59 | VWAP_Types_Elements.md | 🔗 | [[04_Market_Profile/VWAP]] (merged с #60, #61 + VWAP_Basics) |
| 60 | What_Is_VWAP.md | 🔗 | [[04_Market_Profile/VWAP]] (merged с #59, #61 + VWAP_Basics) |
| 61 | Key_Levels_VWAP_Integration.md | 🔗 | [[04_Market_Profile/VWAP]] (merged с #59, #60 + VWAP_Basics) |
| 62 | RTH_vs_ETH.md | ✅ | [[04_Market_Profile/RTH_vs_ETH]] |
| 63 | BuyingSelling_Tail.md | ✅ | [[04_Market_Profile/Buying_Selling_Tail]] |
| 64 | Initiative_Buying_Selling.md | 🔗 | [[04_Market_Profile/Initiative_vs_Responsive]] (merged с #65) |
| 65 | Responsive_Buying_Selling.md | 🔗 | [[04_Market_Profile/Initiative_vs_Responsive]] (merged с #64) |
| 66 | Market_Rotation_in_Balance.md | ✅ | [[04_Market_Profile/Market_Rotation_in_Balance]] |

## Group 6 — Open Types / Day Types → `06_Bias_Templates/` ✅

| # | Файл | Статус | Target |
|---|------|--------|--------|
| 67 | Open_Auction.md | 🔗 | [[06_Bias_Templates/Open_Types]] (merged с #68, #69, #70, #71) |
| 68 | Open_Drive.md | 🔗 | [[06_Bias_Templates/Open_Types]] (merged с #67, #69, #70, #71) |
| 69 | Open_Rejection_Reverse.md | 🔗 | [[06_Bias_Templates/Open_Types]] (merged с #67, #68, #70, #71) |
| 70 | Open_Test_Drive.md | 🔗 | [[06_Bias_Templates/Open_Types]] (merged с #67, #68, #69, #71) |
| 71 | Open_Type.md | 🔗 | [[06_Bias_Templates/Open_Types]] (merged с #67, #68, #69, #70) |
| 72 | Open_outside_Range.md | 🔗 | [[06_Bias_Templates/Opening_vs_Previous_Day]] (merged с #73, #74, #75) |
| 73 | Open_outside_VA.md | 🔗 | [[06_Bias_Templates/Opening_vs_Previous_Day]] (merged с #72, #74, #75) |
| 74 | Open_within_VA.md | 🔗 | [[06_Bias_Templates/Opening_vs_Previous_Day]] (merged с #72, #73, #75) |
| 75 | Openings_Relationship_to_Previous_Day.md | 🔗 | [[06_Bias_Templates/Opening_vs_Previous_Day]] (merged с #72, #73, #74) |
| 76 | Initial_Balance.md | ✅ | [[06_Bias_Templates/Initial_Balance]] |
| 77 | Neutral_Day.md | 🔗 | [[06_Bias_Templates/Day_Types]] (merged с #78–#82) |
| 78 | Trend_Day.md | 🔗 | [[06_Bias_Templates/Day_Types]] (merged с #77, #79–#82) |
| 79 | Normal_Day.md | 🔗 | [[06_Bias_Templates/Day_Types]] (merged с #77, #78, #80–#82) |
| 80 | Normal_Variation_Day.md | 🔗 | [[06_Bias_Templates/Day_Types]] (merged с #77–#79, #81, #82) |
| 81 | Non-Trend_Day.md | 🔗 | [[06_Bias_Templates/Day_Types]] (merged с #77–#80, #82) |
| 82 | Double_Distribution_Day.md | 🔗 | [[06_Bias_Templates/Day_Types]] (merged с #77–#81) |
| 83 | IntraDay_Price_Templates.md | ✅ | [[06_Bias_Templates/IntraDay_Price_Templates]] (stub — изображения недоступны) |
| 84 | NDOGNWOG.md | ✅ | [[05_Sessions_Timings/NDOG_NWOG]] (перенаправлен — тематически Sessions) |

## Group 7 — Сессии / Тайминги → `05_Sessions_Timings/` ✅

| # | Файл | Статус | Target |
|---|------|--------|--------|
| 85 | Dark_Trader_Index_Sessions_Indicator.md | ✅ | [[05_Sessions_Timings/Sessions_Indicator]] (h4 без текста = только графика; KB-заметка полная из текстовых частей; ре-экспорт не нужен) |
| 86 | Time_Session_Settings.md | 🔗 | [[05_Sessions_Timings/ICT_Macros]] (merged с #90) |
| 87 | Work_with_timings.md | 🔗 | [[05_Sessions_Timings/Session_Dynamics]] (merged с #88, #89) |
| 88 | Динамика_в_сессиях.md | 🔗 | [[05_Sessions_Timings/Session_Dynamics]] (merged с #87, #89) |
| 89 | Когда_стоит_пропустить_торговый_день_опираясь_на_сессии.md | 🔗 | [[05_Sessions_Timings/Session_Dynamics]] (merged с #87, #88) |
| 90 | ICT_MACROS.md | 🔗 | [[05_Sessions_Timings/ICT_Macros]] (merged с #86) |
| 91 | PO3_AMD_Sessions.md | ✅ | [[05_Sessions_Timings/PO3_AMD]] |

## Group 8 — Bias / Templates (ICT) → `06_Bias_Templates/` ✅

| # | Файл | Статус | Target |
|---|------|--------|--------|
| 92 | ICT_DAILY_BIAS.md | ✅ | [[06_Bias_Templates/ICT_Daily_Bias]] |
| 93 | ICT_Intraday_Templates.md | ✅ | [[06_Bias_Templates/ICT_Intraday_Templates]] (stub — изображения недоступны) |
| 94 | ICT_Weekly_Templates.md | 🔗 | [[06_Bias_Templates/Weekly_Templates]] (merged с #95) |
| 95 | Weekly_Profiles.md | 🔗 | [[06_Bias_Templates/Weekly_Templates]] (merged с #94) |
| 96 | DWMY_Opens.md | ✅ | [[06_Bias_Templates/DWMY_Opens]] |
| 97 | Market_Maker_BS_Model.md | ✅ | [[06_Bias_Templates/Market_Maker_Model]] |
| 98 | Квартальная_теория.md | ✅ | [[06_Bias_Templates/Quarterly_Theory]] (stub — материалы на отдельных Notion-страницах) |

## Group 9 — POI / Работа в зонах → `07_POI/` ✅

| # | Файл | Статус | Target |
|---|------|--------|--------|
| 99 | POI.md | 🔗 | [[07_POI/POI]] (merged с #101, #102) |
| 100 | Work_in_POI.md | ✅ | [[07_POI/Work_in_POI]] |
| 101 | Why_POI_not_POI.md | 🔗 | [[07_POI/POI]] (merged с #99, #102) |
| 102 | Как_подобрать_POI.md | 🔗 | [[07_POI/POI]] (merged с #99, #101) |
| 103 | Institutional_Order_Flow_Как_пример_работы_в_POI_Углубленная_работа_в_POI_и_за_ее_пределами.md | ✅ | [[07_POI/IOF]] |
| 104 | Decision_Point_DP.md | ✅ | [[07_POI/Decision_Point_DP]] |

## Group 10 — Entry Models → `08_Entry_Models/` ✅

| # | Файл | Статус | Target |
|---|------|--------|--------|
| 105 | Entry_Models.md | 🔗 | [[08_Entry_Models/Entry_Models]] (merged с #108) |
| 106 | Entry_Models_2.md | 🔗 | [[08_Entry_Models/Entry_Models_Practical]] (merged с #107) |
| 107 | IMB_как_модель_входа.md | 🔗 | [[08_Entry_Models/Entry_Models_Practical]] (merged с #106) |
| 108 | ДИНАМИКА_ENTRY_MODELS.md | 🔗 | [[08_Entry_Models/Entry_Models]] (merged с #105) |
| 109 | Dark_Trader_Модели_входа.md | ❌ | — (контент: "Конспект" + "18+" — пустая страница) |
| 110 | ICT_JUDAS_SWING.md | ✅ | [[08_Entry_Models/ICT_Judas_Swing]] |
| 111 | ICT_SILVER_BULLET.md | ✅ | [[08_Entry_Models/ICT_Silver_Bullet]] |

## Group 11 — Сетапы / Стратегии → `09_Setups/` ✅

| # | Файл | Статус | Target |
|---|------|--------|--------|
| 112 | Setups.md | ✅ | [[09_Setups/NYSE_Open_Setups]] |
| 113 | Basic_Strategies.md | 🔗 | [[09_Setups/VWAP_Strategies]] (merged с #114) |
| 114 | Advanced_Strategies.md | 🔗 | [[09_Setups/VWAP_Strategies]] (merged с #113) |
| 115 | STBBTS.md | ✅ | [[09_Setups/STB_BTS]] |
| 116 | DT15.md | 🔗 | [[09_Setups/DT15_DT16]] (merged с #117) |
| 117 | DT16.md | 🔗 | [[09_Setups/DT15_DT16]] (h4 без текста = только графика; KB-заметка полная из текстовых частей; ре-экспорт не нужен) |

## Group 12 — Order Flow / Trade Management → `11_Trade_Management/` ✅

| # | Файл | Статус | Target |
|---|------|--------|--------|
| 118 | Order_Flow.md | 🔗 | [[11_Trade_Management/Order_Flow]] (merged с #119) |
| 119 | Order_Flow_Validation_Invalidation.md | 🔗 | [[11_Trade_Management/Order_Flow]] (merged с #118) |
| 120 | Momentum.md | ✅ | [[11_Trade_Management/Momentum]] |
| 121 | BE_-_friend_or_foe.md | 🔗 | [[11_Trade_Management/Re-Sweep]] (merged с #124) |
| 122 | Reverses.md | 🔗 | [[11_Trade_Management/Reverses]] (merged с #123) |
| 123 | Reverse_before_target.md | 🔗 | [[11_Trade_Management/Reverses]] (merged с #122) |
| 124 | Re-Sweep.md | 🔗 | [[11_Trade_Management/Re-Sweep]] (merged с #121) |
| 125 | Theory_of_RTGS.md | ✅ | [[11_Trade_Management/Theory_of_RTGS]] |

## Group 13 — Проекции и STDV → `04_Market_Profile/` ✅

| # | Файл | Статус | Target |
|---|------|--------|--------|
| 126 | Standard_Deviation_Projection_STDV.md | ✅ | [[04_Market_Profile/Standard_Deviation_STDV]] |
| 127 | OAR_IDAR.md | 🔗 | [[04_Market_Profile/OAR_IDAR]] (merged с #128) |
| 128 | PD_OAR_IDAR_SP.md | 🔗 | [[04_Market_Profile/OAR_IDAR]] (merged с #127) |

## Group 14 — Multi-TF / Static vs Dynamic → `01_Concepts/` ✅

| # | Файл | Статус | Target |
|---|------|--------|--------|
| 129 | Multi_TF_analysis.md | ✅ | [[01_Concepts/Multi_TF_Analysis]] |
| 130 | Static_vs_Dynamic.md | 🔗 | [[01_Concepts/Static_vs_Dynamic]] (merged с #131, #132) |
| 131 | Static_can_be_Dynamic.md | 🔗 | [[01_Concepts/Static_vs_Dynamic]] (merged с #130, #132) |
| 132 | What_is_Static.md | 🔗 | [[01_Concepts/Static_vs_Dynamic]] (merged с #130, #131) |

## Group 15 — Инструменты рынка → `10_Instruments/` ✅

| # | Файл | Статус | Target |
|---|------|--------|--------|
| 133 | NASDAQ.md | 🔗 | [[10_Instruments/USA_Indices]] (merged с #134–136, #138) |
| 134 | SP_500.md | 🔗 | [[10_Instruments/USA_Indices]] (merged с #133, #135, #136, #138) |
| 135 | DOW_JONES.md | 🔗 | [[10_Instruments/USA_Indices]] (merged с #133, #134, #136, #138) |
| 136 | RUSSEL.md | 🔗 | [[10_Instruments/USA_Indices]] (merged с #133–135, #138) |
| 137 | DAX_11_xetra_open_ресерчбектест.md | ✅ | [[10_Instruments/DAX_Strategy]] |
| 138 | Indices_Fundamental.md | 🔗 | [[10_Instruments/USA_Indices]] (merged с #133–136) |

## Group raw_failed — Отсутствующие страницы Notion → все разделы ✅

Файлы, которые не были захвачены скрейпером изначально, но получены отдельно и **физически перемещены в `raw_notion/`** автором. Все ссылки в KB обновлены.

| # | Файл | Статус | Target |
|---|------|--------|--------|
| F1 | `Inducement.md` | ✅ | [[03_Tools/Inducement]] (новая заметка) |
| F2 | `TGIF_Setup.md` | ✅ | [[09_Setups/TGIF_Setup]] (новая заметка) |
| F3 | `Контекст_BIASPOI_1.md` | ✅ | [[07_POI/Context_BIAS_POI]] (новая заметка) |
| F4 | `Trading_Strategy_by_Isqra.md` | ✅ | [[09_Setups/Isqra_Strategy]] (новая заметка) |
| F5 | `Quarterly_Theory_Materials_1.md` | 🔗 | [[06_Bias_Templates/Quarterly_Theory]] (merged с F6+F7; stub → defined) |
| F6 | `Quarterly_Theory_Materials_2.md` | 🔗 | [[06_Bias_Templates/Quarterly_Theory]] (merged с F5+F7) |
| F7 | `Qarterly_Theory_Materials_3.md` | 🔗 | [[06_Bias_Templates/Quarterly_Theory]] (merged с F5+F6) |
| F8 | `How_to_Create_Static_Setup.md` | 🔗 | [[01_Concepts/Static_vs_Dynamic]] (раздел «Как создать Static Setup» добавлен) |

Дополнительно (от автора, не из файлов):
| — | ICT Intraday Templates (6 шаблонов) | ✅ | [[06_Bias_Templates/ICT_Intraday_Templates]] (stub → defined) |
| — | FTA — определение | ✅ | [[99_Glossary/Glossary]] (FTA 🔴→🟢) |

## Group 16 — Новые статьи (2026-04-25) → `09_Setups/` ✅

| # | Файл | Статус | Target |
|---|------|--------|--------|
| N1 | FDAX_Bell_system.md | ✅ | [[09_Setups/FDAX_Bell_System]] (stub — статистика и параметры выходов в источнике не указаны) |
| N2 | Aress_x_Finetiq_VWAP.md | ✅ | [[09_Setups/VWAP_Momentum_QQQ]] |
| N3 | ETH_Breakout_system_AI.md | ✅ | [[09_Setups/ETH_Breakout_AI_Filter]] |
| N4 | Aress_x_Finetiq_ORB.md | ✅ | [[09_Setups/ORB_QQQ]] |
| N5 | Seasonal_strategies.md | ✅ | [[09_Setups/Seasonal_Strategies]] |

---

## Служебные / пустые файлы (skipped, но темы добавлены в [[_Ambiguities]])

Все 8 файлов содержат только заголовок страницы Notion и URL — контент не был извлечён скрейпером. Темы перечислены, чтобы при будущем дополнении источников их можно было досканировать.

| # | Файл | Статус | Тема Notion-страницы (отсутствует контент) |
|---|------|--------|--------------------------------------------|
| 139 | Notion.md | ❌ | DARK-TRADER-VISION (корневая) |
| 140 | Notion_2.md | ❌ | Inducement |
| 141 | Notion_3.md | ❌ | TGIF-Setup |
| 142 | Notion_4.md | ❌ | Trading-Strategy-by-Isqra |
| 143 | Notion_5.md | ❌ | How-to-Create-Static-Setup |
| 144 | Notion_6.md | ❌ | Day-Types-For-What |
| 145 | Notion_7.md | ❌ | ICT-INTERVIEW: How to Retire at 40 |
| 146 | Notion_8.md | ❌ | BIAS-POI |

---

## Сводка

- Всего исходных файлов: **151** (raw_notion: 146 + 5 новых) + **8** (raw_failed)
- Проанализировано (✅ + 🔗): **143** (Groups 1–16) + **8** (raw_failed) = **151**
- Слито (merged 🔗): **79**
- Пропущено (skipped ❌): **9**
- Осталось: **0** 🎉🎉

### Прогресс по группам

- ✅ Group 1 — Global Concepts & Visions (11/11)
- ✅ Group 2 — Wyckoff / Фазы рынка (3/3)
- ✅ Group 3 — Структура рынка (9/9)
- ✅ Group 4 — Инструменты анализа графика (22/22)
- ✅ Group 5 — Market Profile / VWAP (21/21)
- ✅ Group 6 — Open Types / Day Types (18/18)
- ✅ Group 7 — Сессии / Тайминги (7/7)
- ✅ Group 8 — Bias / Templates (7/7)
- ✅ Group 9 — POI (6/6)
- ✅ Group 10 — Entry Models (7/7)
- ✅ Group 11 — Сетапы (6/6)
- ✅ Group 12 — Order Flow / Trade Mgmt (8/8)
- ✅ Group 13 — Проекции / STDV (3/3)
- ✅ Group 14 — Multi-TF / Static vs Dynamic (4/4)
- ✅ Group 15 — Инструменты рынка (6/6)
- ✅ Group 16 — Новые статьи 2026-04-25 (5/5)
- ✅ Group raw_failed — Отсутствующие страницы (8/8)
