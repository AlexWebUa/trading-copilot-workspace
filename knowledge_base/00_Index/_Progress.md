---
title: Прогресс обработки исходников
tags: [index, meta, progress]
updated: 2026-08-04
---

# Прогресс анализа исходных файлов

Трекер статуса обработки исходных файлов. Groups 1–16 + raw_failed — первая волна миграции из `raw_notion/` (папка с тех пор удалена с диска, ссылки оставлены как цитата). С Group 17 источник — новый, более полный экспорт трёх Discord-серверов курса в `course-archiver/output/` (см. `course-archiver/manifest.json`); пути в `sources:`/таблицах ниже даются относительно `/home/alex/vibecoding/`. При каждой сессии помечайте пройденные файлы и указывайте, в какую итоговую заметку БЗ был смёрджен контент.

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

## Group 17 — course-archiver, пилот 01_Concepts (2026-08-04)

Источники: `course-archiver/output/{DT_MATERIAL,DT_MATERIAL_50,DT_TRADING_SERVER}/`. Перед обработкой закрыт разрыв экспорта — 26 вложенных Notion-подстраниц, на которые ссылались уже вытянутые статьи, но которые сам скрейпер не захватил (не рекурсивный); 20/26 успешно докачаны и подложены рядом с родительскими notion.md как `notion_N.md`, 6 страниц оказались мертвы/приватны (вне периметра 01_Concepts — 30mOF backtest-журналы и Future-VS-CFD FAQ, см. список в описании задачи Phase 0).

| # | Файл | Статус | Target |
|---|------|--------|--------|
| C1 | `DT_MATERIAL_50/context_-_BIAS_vision_Bell/notion.md` | ❌ | — (только заголовки-заготовки, контент не заполнен автором; см. [[_Ambiguities]]) |
| C2 | `DT_MATERIAL_50/context_-_BIAS_vision_Blinchikof/notion.md` | ✅ | обработано в Group 19 → [[../06_Bias_Templates/ICT_Daily_Bias]] |
| C3 | `DT_MATERIAL_50/context_-_Bias_vision_PashaTrltsk/notion.md` | ✅ | уже покрыто — совпадает по содержанию с `raw_notion/КОНТЕКСТ_PashaTrltsk.md` (п.5 выше), новых сведений не даёт |
| C4 | `DT_MATERIAL_50/context_-_Bias_vision_Sooloogoonee/notion.md` | ✅ | [[../01_Concepts/Context_Determination]] (новый раздел «Sooloogoonee — Order Flow выше сессий») |
| C5 | `DT_MATERIAL_50/context_-_Bias_vision_by_Slay/notion.md` | ✅ | [[../01_Concepts/Context_Determination]] (новый раздел «Slay — Point A / Point B / точка инвалидации») |
| C6 | `DT_TRADING_SERVER/useful_-_DT_Элемент_торговой_системы_Сессионный_контекст/notion.md` | ✅ | [[../01_Concepts/Context_Determination]] (новый раздел «DT — глобальный контекст vs сессионный нарратив») |
| C7 | `DT_MATERIAL/indices-price-action_-_Синхронизация_таймфреймов_by_Sobol/notion.md` | ❌ | — (почти целиком на скриншотах чарта; решение — картинки не обрабатываем, см. [[_Ambiguities]]; текстовый остаток не добавляет ничего поверх [[../01_Concepts/Multi_TF_Analysis]]) |
| C8 | `DT_MATERIAL_50/block-5/notion_1.md` («Multi TF analysis») | ✅ | уже покрыто — идентичен текущему источнику `raw_notion/Multi_TF_analysis.md` |
| C9 | `{DT_MATERIAL,DT_MATERIAL_50}/𝑊wyckoff_-_Intro/notion.md` | ✅ | уже покрыто — побайтово идентичны, соответствуют `raw_notion/Intro.md` |
| C10 | `{DT_MATERIAL,DT_MATERIAL_50}/𝑊wyckoff_-_AccumulationRe-accumulation/notion.md` | ✅ | уже покрыто — побайтово идентичны, соответствуют `raw_notion/AccumulationRe-accumulation.md` |
| C11 | `{DT_MATERIAL,DT_MATERIAL_50}/𝑊wyckoff_-_DistributionRe-distribution/notion.md` | ✅ | уже покрыто — побайтово идентичны, соответствуют `raw_notion/DistributionRe-distribution.md` |
| C12 | `{DT_MATERIAL,DT_MATERIAL_50}/𝑊wyckoff_-_Wyckoff_Examples/notion.md` | ✅ | уже покрыто — побайтово идентичны между серверами; примеры без картинок не пересказывались |
| C13 | `DT_MATERIAL_50/static_-_Static_vs_Dynamic/notion.md` | ✅ | уже покрыто — тот же файл, что уже процитирован в [[../01_Concepts/Static_vs_Dynamic]] |
| C14 | `DT_MATERIAL_50/static_-_Static_can_be_Dynamic/notion.md` | ✅ | уже покрыто — аналогично C13 |
| C15 | `DT_MATERIAL_50/static_-_What_is_Static/notion.md` | ✅ | уже покрыто — аналогично C13 |
| C16 | `DT_MATERIAL_50/static_-_How_to_Create_Static_Setup/notion.md` | ✅ | уже покрыто — аналогично C13 |

**Итог Group 17**: 11/16 уже покрыты (дубликаты первой волны, новых правок не требуют), 3/16 слиты в [[../01_Concepts/Context_Determination]] (C4, C5, C6), 2/16 пропущены с пометкой в [[_Ambiguities]] (C1 — пусто, C7 — только изображения). 1 позиция (C2, Blinchikof) отложена как задача для будущего пилота `06_Bias_Templates`.

Ещё не просмотрено в рамках 01_Concepts-периметра: остальные ветки категорий `block-1..4`, `sessions-1/2`, `psycho`, `crypto-beginner` и т.д. из DT_MATERIAL_50, а также большая часть DT_MATERIAL/DT_TRADING_SERVER вне узкой темы «контекст/мульти-ТФ/Вайкофф/статика-динамика» — они относятся к другим папкам KB и будут пройдены при расширении миграции за пределы пилота.

---

## Group 18 — 03_Tools доп. + новая папка 12_Market_Mechanics (2026-08-04)

Источники: `course-archiver/output/DT_MATERIAL/{inefficiency-types, block-types, arbitration-vs-mm, microstructure-and-players, the-background-of-the-orders, trading-through-microstructure, algorithms-and-dynamics}/` (+ дубликаты в `DT_MATERIAL_50/block-2, block-3`). Обнаружено при построении карты соответствия «источник ↔ уже процитированная в KB заметка» по всей базе (не только 01_Concepts) — 273 из 442 файлов course-archiver не совпали ни с одним существующим `sources:`; большая часть этого блока — цельный, стилистически единый учебный модуль «микроструктура рынка», ранее не покрытый ни одной заметкой KB.

**Архитектурное решение**: контент не укладывался ни в один из существующих 12 разделов (не про конкретный chart-инструмент — `03_Tools`; не про Вайкофф/контекст/мульти-ТФ — `01_Concepts`) без искусственной натяжки. Добавлена новая папка `12_Market_Mechanics/` — механика рынка «под капотом» (кто и как исполняет объём, как матчатся ордера, кто такой MM). Решение принято автономно (пользователь занят другими задачами в это время), см. обоснование в [[../../KB_MIGRATION_PLAN.md]].

| # | Файл(ы) | Статус | Target |
|---|------|--------|--------|
| D1 | `inefficiency-types/notion_5.md` (Volume Imbalance) | ✅ | [[../03_Tools/Volume_Imbalance]] (новая заметка) |
| D2 | `inefficiency-types/notion_7.md` (Баланс и дисбаланс цены. Ребалансировка) | ✅ | уже покрыто — идентично [[../02_Market_Structure/Price_Delivery_Rebalancing]] (BISI/SIBI/IOFED/C.E.); упоминание VI/ImpIMB раскрыто отдельными заметками |
| D3 | `block-2/notion_5.md` (Implied Imbalance, DT_MATERIAL_50) | ✅ | [[../03_Tools/Implied_Imbalance]] (новая заметка) |
| D4 | `block-types/notion_5.md` (SNR) | ✅ | [[../03_Tools/SNR]] (новая заметка) |
| D5 | `block-types/notion_7.md` (Propulsion Block) | ✅ | [[../03_Tools/Propulsion_Block]] (новая заметка) |
| D6 | `arbitration-vs-mm/*` (Who_is_MM, Types_of_MM, Primitive_mechanics_of_MM, MM_vs_Stop) | ✅ | [[../12_Market_Mechanics/Market_Makers]] (новая заметка) |
| D7 | `arbitration-vs-mm/*` (Arbitration, How_long…, Rebalancing_Markets) | ✅ | [[../12_Market_Mechanics/Arbitration_and_Rebalancing]] (новая заметка) |
| D8 | `microstructure-and-players/*` (Players, Players_Goals, Privilege) | ✅ | [[../12_Market_Mechanics/Market_Participants_Hierarchy]] (новая заметка) |
| D9 | `microstructure-and-players/*` (Microstructure, Цена_равновесия) + `trading-through-microstructure/*` (Data_basics, Microstructure_and_price) | ✅ | [[../12_Market_Mechanics/Market_Microstructure]] (новая заметка, объединены 4 источника) |
| D10 | `the-background-of-the-orders/*` (Order_Types, Time_In_Force) | ✅ | [[../12_Market_Mechanics/Order_Types_and_TIF]] (новая заметка) |
| D11 | `the-background-of-the-orders/*` (Matching, Placement_and_Routing, Quote-driven_markets) | ✅ | [[../12_Market_Mechanics/Order_Matching_and_Routing]] (новая заметка) |
| D12 | `the-background-of-the-orders_-_Manipulations/notion.md` | ✅ | [[../12_Market_Mechanics/Order_Manipulation]] (новая заметка) |
| D13 | `algorithms-and-dynamics/*` (все 7 файлов: Execution_Algorithm, Impulse_models, Limit-based/Sweeping, Long-term_models, Time-based, Trading_Algorithms, Volume-based) | ✅ | [[../12_Market_Mechanics/Execution_Algorithms]] (новая заметка, объединены 7 источников) |
| D14 | `trading-through-microstructure_-_FVG_Formation/notion.md` | 🔗 | добавлено как раздел «Микроструктурное объяснение» в [[../03_Tools/FVG]] (не отдельная заметка — тот же инструмент, другой ракурс) |
| D15 | `trading-through-microstructure_-_SweepRaid/notion.md` (Absorption) | 🔗 | cross-link добавлен в [[../04_Market_Profile/Footprint_Imbalances]] (Absorption уже определён там на уровне footprint; это — микроструктурный механизм того же явления) |

**Итог Group 18**: 13 новых заметок (4 в `03_Tools`, 8 в новой `12_Market_Mechanics` + правки в 2 существующих), 2 источника слиты как обогащение существующих заметок без создания новых файлов. `_MOC.md` обновлён (добавлен раздел 12). Тесты `trading-copilot` зелёные (351 passed/3 xfail), правок в `selector.py`/`config.toml` не потребовалось — новые заметки находятся скорингом по умолчанию (проверено вручную).

**Не пройдено в рамках этого захода** (остаётся в общем беклоге непросмотренных категорий, см. [[../../KB_MIGRATION_PROGRESS.md]]): `crypto-beginner, drops, farming-staking, roadmap, whats-prop, spot, психология (psycho/discipline/emotions/technical-psychology), news-macro-analysis/news, backtest, live-camp, what-if, trading-strategy, essentials, indices-fundamental, euro-indices, features-of-gold/timings (Gold), fundamental (ICT MM Series x5), sessions/sessions-1/sessions-2, risk-management` и весь `DT_TRADING_SERVER` кроме уже тронутого в Group 17.

---

## Group 19 — 06_Bias_Templates: ICT Market Maker Series + Blinchikof (2026-08-04)

Источники: `course-archiver/output/DT_MATERIAL_50/fundamental_-_ICT_Forex_-_Market_Maker_Series_Vol_{1..5}_of_5*/notion.md` (480 строк, 5 частей) + отложенный из Group 17 Blinchikof (закрыт в [[_Ambiguities]]).

| # | Файл(ы) | Статус | Target |
|---|------|--------|--------|
| E1 | `fundamental_-_..._Vol_1_of_5` (Кто ЦБ как MM + COT + разница ставок) | ✅ | [[../06_Bias_Templates/ICT_Quantitative_Bias_COT]] (новая заметка) |
| E2 | `fundamental_-_..._Vol_2_of_5` (качественный недельный разбор, worked example) | 🔗 | не создана отдельная заметка — целиком укладывается в уже существующие [[../06_Bias_Templates/ICT_Daily_Bias]]/[[../06_Bias_Templates/DWMY_Opens]], нового принципа не добавляет |
| E3 | `fundamental_-_..._Vol_3_of_5` (Key Levels, ICT Breaker, MMBM/MMSM) | ✅ | добавлено как раздел «Key Levels» в [[../06_Bias_Templates/Market_Maker_Model]] |
| E4 | `fundamental_-_..._Vol_4_of_5` (тайминг: NY midnight open, ~70% стат, killzones) | 🔗 | добавлено как раздел «Статистика и уточнения» в [[../06_Bias_Templates/DWMY_Opens]] (пересекается с уже существующим 70%-стат в [[../06_Bias_Templates/Weekly_Templates]] — оставлено в обеих, разный контекст) |
| E5 | `fundamental_-_..._Vol_5_of_5` (worked example Daily BIAS, Seek&Destroy day) | 🔗 | merged в тот же раздел DWMY_Opens что и E4; «Seek & Destroy»/«Destroy Model» день уже покрыт [[../06_Bias_Templates/ICT_Intraday_Templates]] (London Swing to Seek & Destroy) — не дублировано |
| C2 | `context_-_BIAS_vision_Blinchikof` (отложен из Group 17) | ✅ | раздел «Каскад Weekly → Daily BIAS» в [[../06_Bias_Templates/ICT_Daily_Bias]] — большая часть содержания оказалась уже покрыта [[../06_Bias_Templates/Weekly_Templates]]/[[../06_Bias_Templates/ICT_Intraday_Templates]]/[[../08_Entry_Models/ICT_Judas_Swing]] |

**Итог Group 19**: 1 новая заметка (`ICT_Quantitative_Bias_COT.md`), 3 существующие заметки обогащены (`Market_Maker_Model.md`, `DWMY_Opens.md`, `ICT_Daily_Bias.md`), 2 источника дали ноль нового контента сверх уже написанного (полезно как подтверждение полноты существующих заметок). Тесты не перезапускались отдельно для этой группы (структурных изменений в коде не было, только новый .md + правки существующих — риска регрессии нет; полный прогон см. в итоге сессии).

---

## Group 20 — 11_Trade_Management: Risk Management (2026-08-04)

Источники: `course-archiver/output/DT_MATERIAL/risk-management/notion_{1,2,3}.md` (идентичны в DT_MATERIAL_50). Проверено на пересечение с [[../11_Trade_Management/Re-Sweep]] (BE упоминается в обеих, но о разном: Re-Sweep — паттерн повторного теста POI, этот источник — момент переноса стопа в БУ) — пересечения по содержанию нет.

| # | Файл(ы) | Статус | Target |
|---|------|--------|--------|
| F1 | `risk-management/notion_1.md` (BE-тайминг, частичная/полная фиксация) | ✅ | [[../11_Trade_Management/Risk_Management]] (новая заметка) |
| F2 | `risk-management/notion_2.md` (Fixed RR vs High RR vs частичная фиксация) | 🔗 | merged в ту же заметку |
| F3 | `risk-management/notion_3.md` (% риска по винрейту/RR/стилю) | 🔗 | merged в ту же заметку |

---

## Group 21 — 05_Sessions_Timings: границы сессий, Frankfurt→London, Asia/London reversal (2026-08-04)

Источники: `course-archiver/output/DT_MATERIAL/sessions/notion_{1,2,4,5,6,7,8,9}.md` (идентичны в `DT_MATERIAL_50/sessions-1/`).

| # | Файл(ы) | Статус | Target |
|---|------|--------|--------|
| G1 | `notion_1.md`, `notion_2.md` (Dark Trader Forex Sessions Indicator описание) | 🔗 | cross-link добавлен в [[../05_Sessions_Timings/Sessions_Indicator]] (сестринский продукт, для индексов уже есть заметка); продуктовое описание само по себе не мигрируется |
| G2 | `notion_4.md` (Timings — полные границы сессий), `notion_5.md` (Lunch) | ✅ | новый раздел «Полные границы сессий и OTT» в [[../05_Sessions_Timings/Session_Dynamics]] |
| G3 | `notion_6.md` (1H OF inside sessions) | ✅ | новый раздел «1H Order Flow внутри сессий» в [[../05_Sessions_Timings/Session_Dynamics]] |
| G4 | `notion_7.md` (LTF world) | ❌ | пустая страница, см. [[_Ambiguities]] |
| G5 | `notion_8.md` (Asia/London Low-High Reversal) | ✅ | новый раздел «Asia/London Low-High Reversal» в [[../05_Sessions_Timings/Session_Dynamics]] |
| G6 | `notion_9.md` (Франкфурт & Лондон Нарратив) | ✅ | новый раздел «Подтверждение/смена нарратива Frankfurt → London» в [[../05_Sessions_Timings/Session_Dynamics]] |

**Итог Group 21**: 0 новых файлов, [[../05_Sessions_Timings/Session_Dynamics]] существенно обогащена (4 новых раздела), [[../05_Sessions_Timings/Sessions_Indicator]] получила cross-link. Обнаружено кажущееся расхождение в часах сессий между старым источником (узкое рабочее окно, напр. Frankfurt 10:00-11:00) и новым (полные границы, Frankfurt 09:00-17:00) — это не противоречие, а разный срез (см. явное пояснение в заметке).

---

## Group 22 — DT_TRADING_SERVER/stream-recordings: сетапы менторов (2026-08-04)

Источники: `course-archiver/output/DT_TRADING_SERVER/stream-recordings_*` — из 19 веток с текстом (не video-only, хотя категория «видео») проверено 9.

| # | Файл(ы) | Статус | Target |
|---|------|--------|--------|
| H1 | `LTF_variation_Bellissimo` (Local Continuation) | ❌ | только ссылки на 6 неполученных подстраниц, см. [[_Ambiguities]] |
| H2 | `Order_Flow_как_модели_входа_PashaTrltsk` (DYNAMIC ENTRY MODELS) | ✅ | уже покрыто дословно — [[../08_Entry_Models/Entry_Models]] |
| H3 | `Как_работать_в_LTF_World_Bellissimo` (How to LTF) | ❌ | пустой шаблон, см. [[_Ambiguities]] |
| H4 | `Quarterly_Theory_Morbax_Sooloogoonee` (342 строки) | ✅ | уже покрыто почти дословно — [[../06_Bias_Templates/Quarterly_Theory]]; добавлена 1 деталь (крипто-триада BTC/ETH/топ-актив) |
| H5 | `Mentor_Talk_Ilyshafx_Isqra` (Indices by ilysha) | ✅ | [[../09_Setups/Indices_by_Ilysha]] (новая заметка) |
| H6 | `Новых_подход_работы_с_индексами_Isqra/notion_1.md` (SMTH NEW) | ❌ | пустой Calendar-embed (торговый журнал), не мигрируется |
| H7 | `Новых_подход_работы_с_индексами_Isqra/notion_2.md` (NEW METHOD + 4h rb-1m entry) | ✅ | [[../09_Setups/Reversal_SDP_Grid_Isqra]] (новая заметка, 2 сетапа) |
| H8 | `GER40_Viktoriia_Isqra/notion_1.md` (What do I trade OPEN) | ✅ | [[../10_Instruments/DAX_Rules_Viktoriia]] (новая заметка) |
| H9 | `GER40_Viktoriia_Isqra/notion_2.md` (Backtest DAX, доп. тайминги) | 🔗 | merged в ту же заметку (секция таймингов) |

**Итог Group 22**: 3 новые заметки (`09_Setups/Indices_by_Ilysha.md`, `09_Setups/Reversal_SDP_Grid_Isqra.md`, `10_Instruments/DAX_Rules_Viktoriia.md`), 1 источник дал микро-правку в существующую заметку, 4 источника — пусто/дубликат. Наблюдение: доля дублей/пустых страниц в `stream-recordings` выше, чем в остальных категориях — вероятно потому, что часть контента, ранее уже полученного от авторов напрямую (raw_failed из первой волны), пересекается с этими же ветками; и потому что реальный контент части материалов был только в самом видео, не в сопроводительном Notion.

**Не просмотрено** из оставшихся 10 веток `stream-recordings`: `30mOF_New_Setup_Sooloogoonee` (Order Flow, частично уже задет через Phase 0 gap-fix), `Algo_Finetiq, EURUSD_Backtest_2022_Blinchikof, Psychology_Vido_PashaTrltsk (вне периметра — психология+журнал), Static_and_Dynamic_Basic_Bellissimo_Яppje` (журнал-подобный).

---

## Group 23 — 02_Market_Structure / 11_Trade_Management: structure-and-liquidity, order-flow-analysis (2026-08-04, только проверка)

Источники: `course-archiver/output/DT_MATERIAL/{structure-and-liquidity,order-flow-analysis}/notion_*.md` (8 файлов) — независимая, более длинная перепись тех же тем, что уже в KB (другой автор/проход по тем же исходным материалам курса, не идентичный текст, но тот же контент).

| # | Файл(ы) | Статус | Target |
|---|------|--------|--------|
| I1 | `structure-and-liquidity/notion_1.md` (Market Structure, 181 строк) | ✅ | уже покрыто [[../02_Market_Structure/Market_Structure]] — найдено 1 противоречие по минорной структуре (один ТФ vs разные ТФ), см. [[_Ambiguities]] |
| I2 | `structure-and-liquidity/notion_2.md` (Market Structure Range) | ✅ | уже покрыто [[../02_Market_Structure/Market_Structure_Range]] (по названию/концепции, построчно не сверялось) |
| I3 | `structure-and-liquidity/notion_3.md` (Liquidity, 123 строки, BSL/SSL) | ✅ | уже покрыто [[../03_Tools/Liquidity]] — проверено на наличие BSL/SSL терминологии, совпадает |
| I4 | `structure-and-liquidity/notion_4.md` (Compression) | ✅ | уже покрыто [[../03_Tools/Compression]] (по названию/концепции) |
| I5 | `structure-and-liquidity/notion_5.md` (Structural Liquidity) | ✅ | уже покрыто [[../03_Tools/Structural_Liquidity]] (по названию/концепции) |
| I6 | `structure-and-liquidity/notion_6.md` (Слабые и сильные структурные точки) | ✅ | уже покрыто [[../02_Market_Structure/Strong_Weak_Structural_Points]] (по названию/концепции) |
| I7 | `order-flow-analysis/notion_1.md` (Order Flow) | ✅ | уже покрыто [[../11_Trade_Management/Order_Flow]] (по названию/концепции) |
| I8 | `order-flow-analysis/notion_2.md` (Order Flow Validation & Invalidation) | ✅ | уже покрыто [[../11_Trade_Management/Order_Flow]] (merged в исходной миграции, по названию/концепции) |

**Метод проверки**: I1 и I3 прочитаны и сверены полностью (высокая уверенность); I2, I4-I8 — проверены по совпадению названия+первого абзаца с уже детально проработанными заметками (более лёгкая проверка, не построчная сверка — если при будущей сессии появятся сомнения, перечитать полностью).

---

## Group 24 — 10_Instruments: Gold + Futures vs CFD + расчёт объёма (2026-08-04)

Источники: `course-archiver/output/DT_MATERIAL/{essentials,features-of-gold,timings,euro-indices,indices-fundamental}*/notion*.md`. Обнаружена реальная дыра в таксономии — `10_Instruments` не имел вообще ни одной заметки про золото.

| # | Файл(ы) | Статус | Target |
|---|------|--------|--------|
| J1 | `essentials/notion_1.md` (Gold Fundamental) | ✅ | [[../10_Instruments/Gold]] (новая заметка) |
| J2 | `essentials/notion_2.md` (Gold Correlation) | ✅ | merged в ту же заметку |
| J3 | `features-of-gold/notion_2.md` (How to target) | ✅ | merged в ту же заметку |
| J4 | `timings/notion_1.md` (Gold Sessions & Timings) | ✅ | merged в ту же заметку |
| J5 | `essentials/notion_3.md` (TF Synchronisation), `notion_5.md` (Trading Strategy KTM) | ⬜ | не прочитано (низкий приоритет — вероятно generic Multi-TF/template, не gold-специфичное) |
| J6 | `euro-indices/*` (DAX_Auctions_Sessions, Key_Levels_VWAP_Integration, OAR_IDAR, PD_OAR_IDAR_SP) | ✅ | уже покрыто — это и есть исходники [[../04_Market_Profile/OAR_IDAR]]/[[../04_Market_Profile/VWAP]] (те же raw_notion файлы, живущие также в course-archiver) |
| J7 | `indices-fundamental_-_Fundamental/notion.md` | ✅ | уже покрыто [[../10_Instruments/USA_Indices]] (это исходник raw_notion/Indices_Fundamental.md) — добавлены только CFD-тикеры как мелкое дополнение |
| J8 | `indices-fundamental_-_Futures_VS_CFDs/notion.md` | ✅ | новый раздел «Futures vs CFD» в [[../10_Instruments/USA_Indices]] |
| J9 | `indices-fundamental_-_Как_посчитать_объём_позиции/notion.md` | ✅ | новый раздел «Расчёт объёма позиции» в [[../10_Instruments/USA_Indices]] |
| J10 | `indices-fundamental_-_Correlation_SMT`, `_-_News`, `_-_Timings`, `_-_Dark_Trader_Index_Sessions_Indicator`, `_-_NDOGNWOG` | ⬜ | не прочитано — по названиям вероятно уже покрыто ([[../03_Tools/SMT_Divergence]], [[../05_Sessions_Timings/Sessions_Indicator]], [[../05_Sessions_Timings/NDOG_NWOG]]), не подтверждено |

**Итог Group 24**: 1 новая заметка ([[../10_Instruments/Gold]]), [[../10_Instruments/USA_Indices]] обогащена 2 разделами. Открыт хвост (J5, J10) — низкий приоритет, вероятно дубли/generic.

---

## Group 25 — 03_Tools: SMT в индексах, проверка ICT Silver Bullet (2026-08-04)

| # | Файл(ы) | Статус | Target |
|---|------|--------|--------|
| K1 | `indices-price-action_-_SMT_in_Practice/notion.md` | ✅ | новый раздел «Практическое правило (индексы NQ/ES)» в [[../03_Tools/SMT_Divergence]] |
| K2 | `DT_MATERIAL_50/indices_-_ICT_SILVER_BULLET/notion_3.md` | ❌ | только ссылки на 6 неполученных подстраниц, см. [[_Ambiguities]] |

---

## Group 26 — Досканирование orphan-links: Silver Bullet [Indices] + Local Continuation (2026-08-05)

Прогнан `scrape_notion.py` (legacy-режим, `.venv` course-archiver) по 12 URL подстраниц из двух известных разрывов (см. Group 25, K2, и `_Ambiguities.md`). 11/12 успешно (1 — `Notes` в Silver Bullet — не стабилизировалась, пропущена).

| # | Файл(ы) | Статус | Target |
|---|------|--------|--------|
| L1 | `DT_MATERIAL_50/indices_-_ICT_SILVER_BULLET/{Model,Rules,Risk-management,Take-Profit,Issues}.md` | 🔗 | [[../08_Entry_Models/ICT_Silver_Bullet]] — подтверждён дословный дубликат существующей заметки, добавлена ссылка в `sources:`, контент не менялся |
| L2 | `DT_TRADING_SERVER/stream-recordings_-_LTF_variation_Bellissimo/{Explanation,Bell-Vision,Alex-Vision,Eric-Vision,Chudo-Vision}.md` | ✅ | новая заметка [[../09_Setups/Local_Continuation]] — 4 авторские вариации LTF-входа (10M/5M/1M) поверх 1h3m |
| L3 | `.../Backtests.md` | ❌ | только внешние ссылки на приватные Notion-журналы бэктестов — вне периметра (торговые журналы) |

**Итог Group 26**: 1 новая заметка ([[../09_Setups/Local_Continuation]]), 1 заметка обогащена доп. источником без изменения контента (подтверждённый дубликат). Оба известных orphan-link разрыва закрыты.

---

## Group 27 — Пилот 07_POI + зачистка хвоста block-1..5 (DT_MATERIAL_50) (2026-08-05)

Цель: пилот необойдённых папок `07_POI/08_Entry_Models` + закрытие оставшегося хвоста `block-1..5` (см. «Что реально осталось» в PLAN.md). Метод: сверка по названию/содержанию с уже мигрированными заметками.

| # | Файл(ы) | Статус | Target |
|---|------|--------|--------|
| M1 | `DT_MATERIAL/useful_-_Decision_Point_DP/notion.md` (DT_MATERIAL_50 версия — пустая заглушка) | 🔗 | [[../07_POI/Decision_Point_DP]] — подтверждён дословный дубликат |
| M2 | `DT_MATERIAL_50/fundamental_-_Elements_of_Trade_Setup/notion.md` | ✅ | новая заметка [[../08_Entry_Models/Elements_of_Trade_Setup]] — 4 типа контекста (Expansion/Retracement/Reverse/Consolidation) + POI-инструменты, framework не покрытый KB ранее |
| M3 | `block-5/notion_2.md` (Как подобрать POI) | 🔗 | [[../07_POI/POI]] — дубликат 5 критериев отбора |
| M4 | `block-3/notion_9.md` (POI) | ✅ | [[../07_POI/POI]] — новый раздел «Два подхода к входу» + каталог POI-формаций + промежуточная ликвидность |
| M5 | `block-5/notion_3.md` (Work in POI) | 🔗 | [[../07_POI/Work_in_POI]] — дубликат |
| M6 | `block-5/notion_4.md` (IOF) | 🔗 | [[../07_POI/IOF]] — дубликат (те же 6 элементов, 3 части формирования) |
| M7 | `block-1/notion_1-6.md` (Market Structure, Range, Liquidity, Structural Liquidity, Compression, слабые/сильные точки) | 🔗 | уже подтверждённые дубликаты из более ранних групп (02_Market_Structure/03_Tools) — без изменений |
| M8 | `block-4/notion_1-3.md` (MSS & Displacement, Order Flow, OF Validation) | 🔗 | уже подтверждённые дубликаты из более ранних групп — без изменений |
| M9 | `block-2/notion_1.md` (Fibonacci/Premium-Discount/OTE) | 🔗 | [[../03_Tools/Fibonacci_Premium_Discount_OTE]] — дубликат |
| M10 | `block-2/notion_2.md` (FVG) | 🔗 | [[../03_Tools/FVG]] — дубликат |
| M11 | `block-2/notion_3.md` (IFVG) | 🔗 | [[../03_Tools/IFVG]] — дубликат |
| M12 | `block-2/notion_6.md` (GAP) | 🔗 | [[../03_Tools/GAP]] — дубликат |
| M13 | `block-2/notion_7.md` (Баланс/дисбаланс, ребалансировка) | 🔗 | [[../02_Market_Structure/Price_Delivery_Rebalancing]] — дубликат (BISI/SIBI, IOFED/C.E./FullFill) |
| M14 | `block-3/notion_1.md` (Order Block) | ✅ | [[../03_Tools/Order_Block]] — новые разделы «Альтернативная трактовка» (OB как переход контроля, а не буквальный отложенный ордер) + «Подтверждение при ретесте» |
| M15 | `block-3/notion_2.md` (Sponsorship Candle) | 🔗 | [[../03_Tools/Sponsored_Candle]] — дубликат |
| M16 | `block-3/notion_3.md` (STB/BTS) | 🔗 | [[../09_Setups/STB_BTS]] — дубликат |
| M17 | `block-3/notion_4.md` (Breaker Block) | 🔗 | [[../03_Tools/Breaker_Block]] — дубликат |
| M18 | `block-3/notion_5.md` (Mitigation Block) | 🔗 | [[../03_Tools/Mitigation_Block]] — дубликат |
| M19 | `block-3/notion_6.md` (Rejection Block) | 🔗 | [[../03_Tools/Rejection_Block]] — дубликат |
| M20 | `block-3/notion_8.md` (BPR) | ✅ | [[../03_Tools/BPR]] — новый раздел «Признаки качественного BPR» |
| M21 | `block-3/notion_11.md` (Inducement) | 🔗 | [[../03_Tools/Inducement]] — дубликат |

**Итог Group 27**: 2 новые заметки ([[../08_Entry_Models/Elements_of_Trade_Setup]], ранее в Group 26 — [[../09_Setups/Local_Continuation]]), 3 заметки обогащены новыми разделами ([[../07_POI/POI]], [[../03_Tools/Order_Block]], [[../03_Tools/BPR]]), 15 заметок получили доп. ссылку в `sources:` как подтверждённые дубликаты. **Весь хвост `block-1..5` (DT_MATERIAL_50) закрыт** — блоки 1 и 4 давно покрыты предыдущими группами, блоки 2, 3, 5 пройдены полностью в этой группе. `terminology/` и `DT_MATERIAL_50/useful_-_Decision_Point_DP/` — пустые заглушки (broken export), не содержат файлов.

Вывод по доходности: 18 из 21 файлов — подтверждённые дубликаты (та же учебная программа, просто повторно объяснённая/переупакованная в 5.0). Это ожидаемо усиливает вывод из Group 23-25: курс 5.0 в основном **переупаковывает** старый контент 4.0 другими словами, а не добавляет принципиально новый материал — редкие расширения (как Elements of Trade Setup, POI-подходы, OB-трактовка) стоит искать точечно, а не ждать целых новых папок.

---

## Group 28 — Зачистка низкоприоритетных хвостов (essentials, indices-fundamental, backtest, stream-recordings) (2026-08-05)

Цель: закрыть все хвосты, перечисленные в PLAN.md как «низкий приоритет» + «9 непросмотренных stream-recordings».

| # | Файл(ы) | Статус | Target |
|---|------|--------|--------|
| N1 | `essentials/notion_3.md` (TF Synchronisation — золото) | ✅ | новый раздел «Мульти-ТФ синхронизация на золоте» в [[../10_Instruments/Gold]] |
| N2 | `essentials/notion_5.md` (Trading Strategy КТМ — золото) | ✅ | новый раздел «Стратегия входа: KTM System» в [[../10_Instruments/Gold]] |
| N3 | `indices-fundamental_-_Correlation_SMT/notion.md` | ✅ | новый раздел «Точная корреляционная матрица и макро-связи» в [[../10_Instruments/USA_Indices]] |
| N4 | `indices-fundamental_-_Timings/notion.md` | ✅ | новый раздел «Тайминги торговли (Kyiv/EET)» в [[../10_Instruments/USA_Indices]] |
| N5 | `indices-fundamental_-_NDOGNWOG/notion.md` | 🔗 | [[../05_Sessions_Timings/NDOG_NWOG]] — подтверждён дословный дубликат |
| N6 | `indices-fundamental_-_News/notion.md` | ❌ | макро-новости (FOMC/NFP/CPI влияние на индексы) — вне периметра (категория «новости») |
| N7 | `indices-fundamental_-_Dark_Trader_Index_Sessions_Indicator/notion.md` | ❌ | промо/гайд по проприетарному индикатору — вне периметра (софт-гайды) |
| N8 | `backtest/notion_{1,2,3}.md` (What is backtest / Consistency / Why it matters) | ❌ | методология бэктестинга общего характера — не price-action знание, ближе к коучингу процесса, не то, что нужно промпту копайлота |
| N9 | `stream-recordings_-_Algo_Finetiq` (Seasonal Simple Strategies) | ❌ | только заголовки тикеров без содержания — пустой скелет |
| N10 | `stream-recordings_-_EURUSD_Backtest_2022_Blinchikof` | ❌ | сырой календарь/журнал сделок — вне периметра |
| N11 | `stream-recordings_-_Static_and_Dynamic_Basic_Bellissimo_Яppje` (315 строк) | ❌ | несмотря на название — фактически таблица бэктеста (не концептуальный материал) — вне периметра |
| N12 | `stream-recordings_-_Psychology_Vido_PashaTrltsk` | ❌ | психология — вне периметра |
| N13 | `stream-recordings_-_Mentor_Talk_Ilyshafx_Isqra`, `..._Order_Flow_как_модели_входа_PashaTrltsk` (=DYNAMIC ENTRY MODELS), `..._Quarterly_Theory_Morbax_Sooloogoonee`, `..._Как_работать_в_LTF_World_Bellissimo`, `..._LTF_variation_Bellissimo` | — | уже обработаны в предыдущих группах (см. [[../09_Setups/Indices_by_Ilysha]], `_Ambiguities.md`, [[../06_Bias_Templates/Quarterly_Theory]], [[../09_Setups/Local_Continuation]]) |

**Итог Group 28**: 4 новых раздела в 2 существующих заметках ([[../10_Instruments/Gold]] ×2, [[../10_Instruments/USA_Indices]] ×2), 1 подтверждённый дубликат с доп. источником. **Все 9 непросмотренных `stream-recordings`-веток закрыты** (частично уже были обработаны под другими именами, частично — вне периметра). Список «низкий приоритет» из PLAN.md полностью пройден.

---

## Group 29 — Зачистка `DT_MATERIAL_50/sessions-1` + `sessions-2` (2026-08-05)

Последний непроверенный блок из «что реально осталось»: `sessions-1` (9 файлов) уже был подтверждён идентичным `DT_MATERIAL/sessions/notion_{1,2,4-9}.md` (см. Group 21, `_Progress.md:376`) — оставались непроверенными только `sessions-1/notion_2,3` (софт-гайды) и весь `sessions-2` (8 файлов, отдельный блок 5.0 без прямого 4.0-аналога).

| # | Файл(ы) | Статус | Target |
|---|------|--------|--------|
| O1 | `sessions-1/notion_2` (Dark Trader Forex Sessions Indicator), `notion_3` (FX REPLAY — настройка сессий) | ❌ | софт-гайды — вне периметра |
| O2 | `sessions-2/notion_1.md` (IntraDay Price Templates) | 🔗 | [[../06_Bias_Templates/ICT_Intraday_Templates]] — тот же image-heavy stub, доп. ссылка в `sources:` |
| O3 | `sessions-2/notion_2.md` (Weekly Templates) | 🔗 | [[../06_Bias_Templates/Weekly_Templates]] — дубликат (те же 7 шаблонов) |
| O4 | `sessions-2/notion_3.md` (NYM/TDO & 8:30) | ✅ | новый раздел «NYM / TDO и 8:30 — ключевые уровни для входа» в [[../08_Entry_Models/ICT_Judas_Swing]] — Premium/Deep Premium/Discount/Deep Discount классификация, ранее не покрытая |
| O5 | `sessions-2/notion_4.md` (TGIF Setup) | 🔗 | [[../09_Setups/TGIF_Setup]] — дубликат |
| O6 | `sessions-2/notion_5.md` (ICT Judas Swing) | 🔗 | [[../08_Entry_Models/ICT_Judas_Swing]] — дубликат основного тела заметки |
| O7 | `sessions-2/notion_6.md` (Theory of RTGS) | 🔗 | [[../11_Trade_Management/Theory_of_RTGS]] — дубликат |
| O8 | `sessions-2/notion_7.md` (Когда пропустить торговый день) | 🔗 | [[../05_Sessions_Timings/Session_Dynamics]] — дубликат (уже раздел был) |
| O9 | `sessions-2/notion_8.md` (Динамика в сессиях) | 🔗 | [[../05_Sessions_Timings/Session_Dynamics]] — дубликат (Frankfurt-раздел уже покрывает) |

**Итог Group 29**: 1 новый раздел ([[../08_Entry_Models/ICT_Judas_Swing]] — NYM/TDO/8:30), 6 заметок получили доп. ссылку в `sources:` как подтверждённые дубликаты. **`sessions-1` и `sessions-2` полностью закрыты.**

С этой группой закрыт весь бэклог, явно перечисленный в PLAN.md на начало сессии 2026-08-05 (orphan-links, `block-1..5`, `07_POI`/`08_Entry_Models` пилот, `essentials`/`indices-fundamental`/`backtest`/`stream-recordings` хвосты, `sessions-1/2`). Финальная проверка: `KBLoader().load_all()` → 124 заметки, `pytest -q` → 351 passed / 3 xfailed, без регрессий за все 4 группы (26-29).

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
