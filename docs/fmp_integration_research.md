# FMP（Financial Modeling Prep）集成调研报告

**日期**：2026-03-04  
**目标**：将 FMP REST API 封装为 ToolRegistry 工具，供 LLM Agent 查询财务数据与市场数据。

---

## 1. FMP 能力概览

FMP 提供以下核心数据类别，均以 REST JSON API 对外暴露：

| 类别 | 说明 | 用途 |
|------|------|------|
| **财务报表（标准化）** | 利润表、资产负债表、现金流量表（年报/季报/TTM） | 基本面分析 |
| **财务报表（As Reported）** | 原始 XBRL 数据，直接来自 SEC 申报，未经 FMP 标准化 | 原始数据核对 |
| **关键指标** | EV、ROIC、FCF Yield、Graham Number 等 50+ 指标 | 质量分析 |
| **财务比率** | P/E、P/B、D/E、毛利率、ROE 等 40+ 比率 | 估值对比 |
| **收入拆分** | 按产品线/地区拆分收入（Segmentation） | 业务结构分析 |
| **市场行情** | 实时报价、历史日线、盘后数据 | 行情研究 |
| **外汇/汇率** | 主要货币对实时报价与历史 EOD 数据 | 汇率研究 |
| **财务预测** | 分析师收入/EPS/净利润预测（年度/季度） | 预期分析 |
| **电话会议记录** | 财报电话会议完整文字记录 | 管理层分析 |
| **内部人交易** | 高管/董事 SEC Form 4 申报数据（买卖行为） | 管理层信号分析 |
| **DCF 估值** | 高级 DCF（WACC、FCFF/FCFE、终值） | 内在价值 |
| **公司概况** | 行业、市值、员工数、交易所、描述 | 基本信息 |
| **公司搜索** | 按 symbol/名称/CIK 搜索公司，返回 symbol、companyName、exchange | pipeline 前置步骤，分析输入解析 |
---

## 2. 支持的国家与交易所

FMP 覆盖**全球主要交易所**，通过 `/stable/available-exchanges` 可获取完整列表。
以下为截至调研时已确认支持的主要交易所（部分）：

| 交易所代码 | 全称 | 国家/地区 | 数据延迟 |
|-----------|------|----------|--------|
| **NYSE** | New York Stock Exchange | 美国 | 实时 |
| **NASDAQ** | NASDAQ Stock Market | 美国 | 实时 |
| **AMEX** | NYSE American (AMEX) | 美国 | 实时 |
| **LSE** | London Stock Exchange | 英国 | 延迟 |
| **XETRA** | Deutsche Börse XETRA | 德国 | 延迟 |
| **EURONEXT** | Euronext（巴黎/阿姆斯特丹/布鲁塞尔/里斯本） | 欧洲 | 延迟 |
| **TSX** | Toronto Stock Exchange | 加拿大 | 延迟 |
| **HKSE** | Hong Kong Stock Exchange | 香港 | 延迟 |
| **SHH** | Shanghai Stock Exchange | 中国大陆（沪） | 延迟 |
| **SHZ** | Shenzhen Stock Exchange | 中国大陆（深） | 延迟 |
| **JPX** | Japan Exchange Group | 日本 | 延迟 |
| **ASX** | Australian Securities Exchange | 澳大利亚 | 延迟 |
| **BSE** | Bombay Stock Exchange | 印度 | 延迟 |
| **NSE** | National Stock Exchange of India | 印度 | 延迟 |
| **PNK** | OTC Pink Sheets | 美国（OTC） | 实时 |

**Ticker 格式说明**：

| 市场 | 格式示例 | 说明 |
|------|---------|------|
| 美股 | `AAPL`, `MSFT` | 无后缀 |
| 港股 | `9988.HK`, `0700.HK` | `.HK` 后缀 |
| A 股 | `600519.SS`（沪）, `000001.SZ`（深） | Yahoo Finance 兼容格式 |
| 英股 | `SHEL.L` | `.L` 后缀 |
| 德股 | `SAP.DE` | `.DE` 后缀 |

> **注意**：FMP 对 A 股、港股中文公司财报数据覆盖质量弱于美股，
> 季报/电话会议记录的可用性视公司而定，建议实际调用验证后再依赖。

**获取完整交易所列表**：
```
GET https://financialmodelingprep.com/stable/available-exchanges
```

---

## 3. 核心端点清单

FMP 官方文档全面采用 `/stable/` 端点（`api/v3` 已为旧接口，不再维护）。  
**所有工具实现均使用 `/stable/` 路径**，不回退 `/api/v3/`。

### 3.1 财务报表（标准化）

#### 利润表

```
GET https://financialmodelingprep.com/stable/income-statement
参数：symbol（必填）、period（annual|quarter，默认 annual）、limit（默认 10）
```

关键字段：`date`, `fiscalYear`, `period`, `reportedCurrency`,
`revenue`, `costOfRevenue`, `grossProfit`, `grossProfitRatio`,
`researchAndDevelopmentExpenses`, `operatingExpenses`, `operatingIncome`,
`operatingIncomeRatio`, `ebitda`, `ebitdaratio`,
`interestExpense`, `incomeTaxExpense`,
`netIncome`, `netIncomeRatio`,
`eps`, `epsdiluted`,
`weightedAverageShsOut`, `weightedAverageShsOutDil`

#### 资产负债表

```
GET https://financialmodelingprep.com/stable/balance-sheet-statement
参数：symbol（必填）、period（annual|quarter）、limit
```

关键字段：`date`, `period`,
`cashAndCashEquivalents`, `shortTermInvestments`, `accountsReceivable`,
`inventory`, `totalCurrentAssets`,
`propertyPlantEquipmentNet`, `goodwill`, `intangibleAssets`, `totalAssets`,
`accountsPayable`, `shortTermDebt`, `totalCurrentLiabilities`,
`longTermDebt`, `totalLiabilities`,
`totalStockholdersEquity`, `retainedEarnings`

#### 现金流量表

```
GET https://financialmodelingprep.com/stable/cash-flow-statement
参数：symbol（必填）、period（annual|quarter）、limit
```

关键字段：`date`, `period`,
`netIncome`, `depreciationAndAmortization`, `stockBasedCompensation`,
`changesInWorkingCapital`, `operatingCashFlow`,
`capitalExpenditure`, `freeCashFlow`,
`cashFlowFromInvesting`, `cashFlowFromFinancing`,
`dividendsPaid`, `commonStockRepurchased`, `netChangeInCash`

---

### 3.2 财务报表（As Reported）

As Reported 端点返回**原始 XBRL 数据**，即公司向 SEC/监管机构申报时的原始数字，
未经 FMP 标准化处理。适用于需要与原始申报数字完全一致的场景（如学术研究、审计对账）。

```
GET https://financialmodelingprep.com/stable/income-statement-as-reported
GET https://financialmodelingprep.com/stable/balance-sheet-statement-as-reported
GET https://financialmodelingprep.com/stable/cash-flow-statement-as-reported
参数：symbol（必填）、period（annual|quarter）、limit（默认 1000）
```

**响应结构**（每期为数组元素）：`symbol`, `fiscalYear`, `period`, `reportedCurrency`, `date`,
`data`（嵌套对象，键为 XBRL concept 名称全小写，如 `netincomeloss`, `grossprofit`）

**与标准化版本的核心差异**：

| 维度 | 标准化版本 | As Reported 版本 |
|------|-----------|-----------------|
| 字段名 | FMP 统一命名（camelCase） | 原始 XBRL concept 名称 |
| 数值口径 | FMP 标准化处理后 | 原始申报数字 |
| 字段数量 | 固定约 30-50 个字段 | 字段数量因公司而异 |
| 适用场景 | 跨公司横向对比 | 原始数据核对、学术研究 |

> **注意**：As Reported 字段名不统一（各公司 XBRL tag 不同），LLM 直接消费时
> 需在 Tool Guidance 中提示这一差异。

---

### 3.3 关键指标（Key Metrics）

```
GET https://financialmodelingprep.com/stable/key-metrics
参数：symbol（必填）、period（annual|quarter|FY|Q1-Q4）、limit（默认 1000）
```

关键字段：`marketCap`, `enterpriseValue`,
`evToSales`, `evToEBITDA`, `evToFreeCashFlow`, `evToOperatingCashFlow`,
`netDebtToEBITDA`, `currentRatio`,
`returnOnEquity`, `returnOnAssets`, `returnOnInvestedCapital`,
`earningsYield`, `freeCashFlowYield`,
`capexToOperatingCashFlow`, `capexToRevenue`,
`researchAndDevelopementToRevenue`, `stockBasedCompensationToRevenue`,
`daysOfSalesOutstanding`, `cashConversionCycle`,
`grahamNumber`, `workingCapital`, `investedCapital`

---

### 3.4 财务比率（Financial Ratios）

```
GET https://financialmodelingprep.com/stable/ratios
参数：symbol（必填）、period（annual|quarter|FY|Q1-Q4）、limit（默认 1000）
```

关键字段：`date`, `fiscalYear`, `period`, `reportedCurrency`,
`grossProfitMargin`, `ebitMargin`, `ebitdaMargin`, `operatingProfitMargin`, `netProfitMargin`,
`receivablesTurnover`, `payablesTurnover`, `inventoryTurnover`, `assetTurnover`, `fixedAssetTurnover`,
`currentRatio`, `quickRatio`, `cashRatio`, `solvencyRatio`,
`priceToEarningsRatio`, `priceToBookRatio`, `priceToSalesRatio`,
`priceToFreeCashFlowRatio`, `priceToOperatingCashFlowRatio`,
`debtToEquityRatio`, `debtToAssetsRatio`, `debtToCapitalRatio`, `financialLeverageRatio`,
`dividendYield`, `dividendPayoutRatio`,
`revenuePerShare`, `netIncomePerShare`, `bookValuePerShare`, `freeCashFlowPerShare`,
`effectiveTaxRate`, `enterpriseValueMultiple`

---

### 3.5 收入拆分（Revenue Segmentation）

#### 产品线拆分

```
GET https://financialmodelingprep.com/stable/revenue-product-segmentation
参数：symbol（必填）、period（annual|quarter）、structure（flat 可选）
```

响应结构：
```json
[{
  "symbol": "AAPL",
  "fiscalYear": 2024,
  "period": "FY",
  "reportedCurrency": null,
  "date": "2024-09-28",
  "data": {
    "iPhone": 201183000000,
    "Service": 96169000000,
    "Mac": 29984000000,
    "iPad": 26694000000,
    "Wearables, Home and Accessories": 37005000000
  }
}]
```

> `data` 的键名因公司而异，无法预定义，LLM 需动态解析键名。

#### 地区拆分

```
GET https://financialmodelingprep.com/stable/revenue-geographic-segmentation
参数：symbol（必填）、period（annual|quarter）、structure（flat 可选）
```

响应结构：
```json
[{
  "symbol": "AAPL",
  "fiscalYear": 2024,
  "period": "FY",
  "reportedCurrency": null,
  "date": "2024-09-28",
  "data": {
    "Americas Segment": 167045000000,
    "Europe Segment": 101328000000,
    "Greater China Segment": 66952000000,
    "Japan Segment": 25052000000,
    "Rest of Asia Pacific": 30658000000
  }
}]
```

> 与产品线拆分同样，地区名称是动态键，且各公司口径不同
>（有的直接按国家，有的按大区）。

---

### 3.6 财务预测（Financial Estimates）

```
GET https://financialmodelingprep.com/stable/analyst-estimates
参数：symbol（必填）、period（annual|quarter）、page（默认 0）、limit（默认 10）
```

关键字段：`symbol`, `date`,
`revenueLow`, `revenueHigh`, `revenueAvg`,
`ebitdaLow`, `ebitdaHigh`, `ebitdaAvg`,
`ebitLow`, `ebitHigh`, `ebitAvg`,
`netIncomeLow`, `netIncomeHigh`, `netIncomeAvg`,
`sgaExpenseLow`, `sgaExpenseHigh`, `sgaExpenseAvg`,
`epsLow`, `epsHigh`, `epsAvg`,
`numAnalystsRevenue`, `numAnalystsEps`

---

### 3.7 财报电话会议记录（Earnings Transcript）

#### 查询可用记录列表（先查后读）

```
GET https://financialmodelingprep.com/stable/earning-call-transcript-dates
参数：symbol（必填）
```

返回该公司所有可用记录的 `fiscalYear`, `quarter`, `date` 列表（无 `content`），响应极小，
不截断。**LLM 应先调用此工具，再按需获取具体季度全文。**

#### 获取某季度电话会议全文

```
GET https://financialmodelingprep.com/stable/earning-call-transcript
参数：symbol（必填）、year（必填，如 2024）、quarter（必填，1-4）、limit（默认 1）
```

返回字段：`symbol`, `period`, `year`, `date`, `content`

- `content` 是完整会议记录全文，典型长度 **10,000～50,000 字符**（中等规模公司）。
- **截断策略**：必须使用 `text_chars`（content 是单字符串，非数组），
  建议默认 `max_chars=40000`。

---

### 3.8 内部人交易（Insider Trading）

> **什么是内部人交易数据？**
>
> 美国证券法规定，公司内部人（董事、高管、持股 ≥10% 的大股东等）
> 每次买卖本公司股票后必须在 **2 个工作日内**向 SEC 申报（提交 **Form 4**）。
> FMP 汇总这些公开申报数据，提取买方/卖方身份、交易股数、成交价等信息。
>
> **实用价值**：
> - 内部人**大规模买入** → 管理层认为股价被低估，历史上是看涨信号。
> - 内部人**集中卖出** → 需结合背景分析（可能是套现，也可能是财务需求）。
> - 结合财报数据一起喂给 LLM，可辅助判断管理层对公司前景的真实态度。
>
> **注意**：覆盖范围主要是在美国上市/有 SEC 申报义务的公司；A 股/港股无此数据。

#### 搜索内部人交易明细

```
GET https://financialmodelingprep.com/stable/insider-trading/search
参数：symbol（可选）、transactionType（S-Sale|P-Purchase）、
      reportingCik、companyCik、page（默认 0）、limit（默认 100，最大 1000）
```

关键字段：`symbol`, `filingDate`, `transactionDate`,
`reportingName`（内部人姓名）, `typeOfOwner`（director|officer|10% owner）,
`transactionType`（S-Sale / P-Purchase）,
`securitiesTransacted`（交易股数）, `price`（成交价）,
`acquisitionOrDisposition`（A=买入 / D=卖出）,
`directOrIndirect`（D=直接持有 / I=间接）,
`reportingCik`（盳论申证人 CIK）, `companyCik`（公司 CIK）,
`formType`（通常为 "4"）, `securityName`（如 "Common Stock"）,
`securitiesOwned`（交易后持股数）, `url`（SEC 归档原文链接）

#### 内部人交易统计（按季度聚合）

```
GET https://financialmodelingprep.com/stable/insider-trading/statistics
参数：symbol（必填）、limit（默认 100）
```

关键字段：`year`, `quarter`, `purchases`, `sales`,
`buySellRatio`, `totalBought`, `totalSold`,
`averageBought`, `averageSold`

---

### 3.9 外汇/汇率（Forex & Currency）

#### 实时外汇报价

```
GET https://financialmodelingprep.com/stable/quote?symbol={pair}
示例：/stable/quote?symbol=EURUSD
```

返回字段：`symbol`, `price`, `open`, `high`, `low`,
`previousClose`, `change`, `changesPercentage`

**主要货币对**：
`EURUSD`, `GBPUSD`, `USDJPY`, `USDCNY`, `USDHKD`,
`AUDUSD`, `USDCAD`, `USDCHF`, `USDKRW`, `USDINR`

#### 历史外汇 EOD 数据

```
GET https://financialmodelingprep.com/stable/historical-price-eod/full
参数：symbol（必填，如 EURUSD）、from（YYYY-MM-DD）、to（YYYY-MM-DD）
```

返回字段（数组）：`date`, `open`, `high`, `low`, `close`, `adjClose`,
`volume`, `change`, `changePercent`, `vwap`

> Forex 与股票历史数据共用同一 endpoint，ticker 格式为 6 位货币对（如 `EURUSD`）。

---

### 3.10 实时/历史股票行情

#### 实时报价

```
GET https://financialmodelingprep.com/stable/quote?symbol={symbol}
```

返回字段：`symbol`, `name`, `price`, `changePercentage`, `change`,
`volume`, `dayLow`, `dayHigh`, `yearHigh`, `yearLow`,
`marketCap`, `priceAvg50`, `priceAvg200`,
`exchange`, `open`, `previousClose`, `timestamp`

#### 历史日线价格

```
GET https://financialmodelingprep.com/stable/historical-price-eod/full?symbol={symbol}
参数：from（YYYY-MM-DD）、to（YYYY-MM-DD）
```

返回字段（数组）：`date`, `open`, `high`, `low`, `close`, `adjClose`,
`volume`, `change`, `changePercent`, `vwap`

---

### 3.11 公司概况

```
GET https://financialmodelingprep.com/stable/profile?symbol={symbol}
```

返回字段（36 个字段）：`symbol`, `companyName`, `price`, `marketCap`, `beta`,
`lastDividend`, `range`, `change`, `changePercentage`, `volume`, `averageVolume`,
`currency`, `cik`, `isin`, `cusip`, `exchangeFullName`, `exchange`,
`industry`, `website`, `description`, `ceo`, `sector`, `country`,
`fullTimeEmployees`, `phone`, `address`, `city`, `state`, `zip`,
`image`, `ipoDate`, `defaultImage`,
`isEtf`, `isActivelyTrading`, `isAdr`, `isFund`

---

### 3.12 公司搜索（Symbol / Name / CIK）

用于已知任意一个标识符（Ticker、公司名、SEC CIK）时对其它两种进行分解/映射。
**Pipeline 典型用法**：用户提供 ticker → 调用 `fmp_search_by_symbol` 获取 `companyName` →
后续工具得到可读公司名，不依赖额外配置或硬编磁。

#### 按 Symbol 搜索

```
GET https://financialmodelingprep.com/stable/search-symbol
参数：query（必填，如 "AAPL"）、limit（默认 50）、exchange（可选，如 "NASDAQ"）
```

响应结构：
```json
[{"symbol": "AAPL", "name": "Apple Inc.", "currency": "USD",
  "exchangeFullName": "NASDAQ Global Select", "exchange": "NASDAQ"}]
```

> 输入 ticker 可匹配同一公司在多个交易所的不同 symbol。
>
> **symbol 推导 companyName 模式**：`query=AAPL` + `limit=1` 即可以最低消耗拿到 `name`。

#### 按公司名搜索

```
GET https://financialmodelingprep.com/stable/search-name
参数：query（必填，如 "Apple"）、limit（默认 50）、exchange（可选）
```

响应结构与 `search-symbol` 相同：`symbol`, `name`, `currency`, `exchangeFullName`, `exchange`

> 模糊匹配，输入公司名关键词即可返回候选列表。

#### 按 CIK 搜索

```
GET https://financialmodelingprep.com/stable/search-cik
参数：cik（必填，如 "320193"）、limit（默认 50）
```

响应结构：
```json
[{"symbol": "AAPL", "companyName": "Apple Inc.", "cik": "0000320193",
  "exchangeFullName": "NASDAQ Global Select", "exchange": "NASDAQ", "currency": "USD"}]
```

> 与 `search-symbol` 的区别：响应字段为 `companyName`（不是 `name`）。
> 可将 SEC EDGAR 内内部人交易/屏异所记录的 CIK 映射回 ticker。

---

## 4. 认证机制

所有请求均在 Query String 附加 `apikey` 参数：

```
https://financialmodelingprep.com/stable/income-statement?symbol=AAPL&apikey=YOUR_KEY
```

密钥通过 `{{FMP_API_KEY}}` 环境变量注入（见第 5 节配置方案）。

---

## 5. API Key 配置方案（方式 B：配置文件，与 llm_models.json 一致）

参照 `llm_models.json` 中的 `{{ENV_VAR_NAME}}` 替换模式，在 `alpha/config/run.json` 增加
`fmp` 配置块，由 `alpha/config.py` 统一解析后注入 `FmpToolService`：

```json
{
  "fmp": {
    "api_key": "{{FMP_API_KEY}}",
    "limits": {
      "statements_max_items": 20,
      "key_metrics_max_items": 20,
      "ratios_max_items": 20,
      "segmentation_max_items": 20,
      "historical_price_max_items": 90,
      "forex_history_max_items": 90,
      "analyst_estimates_max_items": 12,
      "transcript_max_chars": 40000,
      "insider_trades_max_items": 50,
      "insider_stats_max_items": 20,
      "http_timeout": 30.0
    }
  }
}
```

`alpha/config.py` 已有 `{{ENV_VAR_NAME}}` 替换机制，`FMP_API_KEY` 从环境变量注入，
无需修改现有替换逻辑，只需在解析 `run.json` 时额外读取 `fmp` 字段。

---

## 6. 套餐与速率限制

> 数据来源：[FMP Pricing](https://site.financialmodelingprep.com/developer/docs/pricing)（2026-03-04）

| 套餐 | 价格（年付） | 调用限制 | 历史数据 | 地区覆盖 |
|------|------------|---------|---------|--------|
| **Basic** | 免费 | 250 次/天 | 5 年 EOD | 样本 symbols |
| **Starter** | $19/月 | 300 次/分钟 | 5 年 | 仅美国 |
| **Premium** | $49/月 | 750 次/分钟 | 30+ 年 | 美国/英国/加拿大 |
| **Ultimate** | $99/月 | 3,000 次/分钟 | 30+ 年 | 全球 |

**带宽限制**（30 天滚动窗口）：Free=500MB，Starter=20GB，Premium=50GB，Ultimate=150GB

**关键功能与套餐门槛**（影响工具可用性）：

| 功能 | Basic | Starter | Premium | Ultimate |
|------|-------|---------|---------|---------|
| 三表（标准化） | 样本 | 美国年报 | 美/英/加 | 全球 |
| As Reported 三表 | — | 美国 | 美/英/加 | 全球 |
| Key Metrics / Ratios | 样本 | 美国 | 美/英/加 | 全球 |
| Revenue Segmentation | 样本 | 美国 | 美/英/加 | 全球 |
| Analyst Estimates | 样本 | 美国 | 美/英/加 | 全球 |
| **Earnings Transcript** | ❌ | ❌ | ❌ | ✅ 全球 |
| **Insider Trades** | ❌ | 美国 | 美/英/加 | 全球 |
| Stock Quote（实时） | 样本 | ✅ 美国 | 美/英/加 | 全球 |
| Historical Price | 样本 | ✅ 美国 | 美/英/加 | 全球 |
| Forex | 样本 | ✅ | ✅ | ✅ |
| Custom DCF Advanced | 样本 | — | ✅ | ✅ |

> ⚠️ **`fmp_earnings_transcript` 和 `fmp_transcript_dates` 仅 Ultimate 套餐（$99/月）可用。**
> **`fmp_insider_trades` 和 `fmp_insider_statistics` 初步 Starter 套餐（$19/月）。**
> 订阅不足时调用上述工具，FMP 返回 **402 Payment Required**，响应体为
> `"Restricted Endpoint: This endpoint is not available under your current subscription..."`。
> 需在工具 description 中注明套餐要求。

- 超限返回 **HTTP 429**，响应头可能包含 `Retry-After`。
- 历史类端点默认 limit 为 1000，**须在请求参数显式指定 limit** 避免过大响应体。

---

## 7. 错误码归一方案

### 7.1 HTTP 错误映射

| HTTP 状态码 | FMP 含义 | 归一错误码 |
|-------------|---------|-----------|
| 400 | 参数非法（symbol 缺失/格式错误） | `fmp_bad_request` |
| 401 | API Key 无效或过期 | `fmp_unauthorized` |
| 402 | 当前套餐不包含此端点（Restricted Endpoint） | `fmp_plan_restricted` |
| 403 | 请求被拒绝（IP 封禁 / 访问控制） | `fmp_forbidden` |
| 404 | symbol 不存在或无数据 | `fmp_not_found` |
| 429 | 超出速率限制 | `fmp_rate_limit` |
| 500/502/503 | FMP 服务端错误 | `fmp_server_error` |

### 7.2 网络/解析错误

| 场景 | 归一错误码 |
|------|-----------|
| 连接超时 | `fmp_timeout` |
| 网络中断 | `fmp_connection_error` |
| 响应非 JSON | `fmp_parse_error` |
| 响应为空数组 | 正常返回，上层由 `items=[]` 判断 |

### 7.3 与 ToolRegistry 的对接规范

ToolRegistry `execute()` 要求工具函数不抛异常，失败通过返回值表达：

```python
# 成功
{"success": True, "data": {"type": "json", "value": [...]}}

# 失败
{"success": False, "error": {"code": "fmp_not_found", "message": "..."}}
```

`FmpToolService` 的所有方法统一捕获异常并返回归一化字典，工具函数直接
`return service.get_xxx(...)` 即可，**不需要二次 try/except**。

---

## 8. 截断机制匹配方案

现有截断策略见 `alpha/agent/engine/tools/limits.py`：

| 策略名 | limit_key | 适用场景 |
|--------|-----------|---------|
| `text_chars` | `max_chars` | 大段文本 |
| `list_items` | `max_items` | JSON 数组 |

### FMP 各工具截断方案

| 工具 | 策略 | 建议默认值 | 说明 |
|------|------|----------|------|
| `fmp_income_statement` | `list_items` | `max_items=20` | 约 5 年季报 |
| `fmp_balance_sheet` | `list_items` | `max_items=20` | 同上 |
| `fmp_cash_flow` | `list_items` | `max_items=20` | 同上 |
| `fmp_income_statement_reported` | `list_items` | `max_items=20` | As Reported 字段较多，更需截断 |
| `fmp_balance_sheet_reported` | `list_items` | `max_items=20` | 同上 |
| `fmp_cash_flow_reported` | `list_items` | `max_items=20` | 同上 |
| `fmp_key_metrics` | `list_items` | `max_items=20` | FMP 默认返回 1000 条，必须截断 |
| `fmp_financial_ratios` | `list_items` | `max_items=20` | 同上 |
| `fmp_revenue_by_product` | `list_items` | `max_items=20` | 按日期条目 |
| `fmp_revenue_by_geography` | `list_items` | `max_items=20` | 同上 |
| `fmp_analyst_estimates` | `list_items` | `max_items=12` | 近 3 年预测 |
| `fmp_transcript_dates` | `list_items` | `max_items=50` | 仅日期列表，较小 |
| `fmp_earnings_transcript` | `text_chars` | `max_chars=40000` | 全文可达 50,000 字符 |
| `fmp_insider_trades` | `list_items` | `max_items=50` | 每条含较多字段 |
| `fmp_insider_statistics` | `list_items` | `max_items=20` | 季度聚合 |
| `fmp_historical_price` | `list_items` | `max_items=90` | 约 3 个月日线 |
| `fmp_forex_history` | `list_items` | `max_items=90` | 约 3 个月 EOD |
| `fmp_quote` | 不截断 | — | 单 symbol，响应极小 |
| `fmp_forex_quote` | 不截断 | — | 同上 |
| `fmp_company_profile` | 不截断 | — | 单对象 |

> 历史类端点的 `max_items` 应**同时写入 HTTP 请求的 `limit` 参数**，
> 减少不必要的数据传输，实现双重限制。

---

## 9. 集成架构设计

### 9.1 文件结构

```
alpha/agent/fins/fmp_tools/
├── __init__.py           # 导出 register_fmp_tools
├── limits.py             # FmpToolLimits dataclass
├── cache.py              # FmpCache（永久硬盘缓存）
├── service.py            # FmpToolService（HTTP 调用 + 错误归一）
└── tools.py              # register_fmp_tools + 工具工厂函数
```

独立模块目录 `fins/fmp_tools/` 而非混入 `fins/tools/` 或 `engine/tools/`，原因：
FMP 是独立的外部 API 集成（含 API Key、速率限制、专属错误码），
与现有 SEC 本地文件工具（`fins/tools/fins_tools.py`）职责完全分离，
且与 engine 的业务中立原则不符。

### 9.2 FmpToolLimits

```python
@dataclass
class FmpToolLimits:
    """FMP 工具截断与请求限制配置。"""
    statements_max_items: int = 20          # 三表（含 as-reported）最大返回期数
    key_metrics_max_items: int = 20         # 关键指标最大期数
    ratios_max_items: int = 20              # 比率最大期数
    segmentation_max_items: int = 20        # 收入拆分（产品/地区）最大期数
    historical_price_max_items: int = 90    # 历史价格最大天数
    forex_history_max_items: int = 90       # 历史外汇数据最大天数
    analyst_estimates_max_items: int = 12   # 分析师预测最大条数
    transcript_max_chars: int = 40000       # 电话会议记录文字截断阈值
    insider_trades_max_items: int = 50      # 内部人交易明细最大条数
    insider_stats_max_items: int = 20       # 内部人统计最大期数
    http_timeout: float = 30.0              # HTTP 请求超时（秒）
    cache_dir: str | None = None            # 缓存目录（None 表示不启用缓存）
```

### 9.3 FmpToolService 接口草图

```python
class FmpToolService:
    """FMP API HTTP 调用服务层，负责认证、错误归一。"""

    BASE_URL = "https://financialmodelingprep.com"

    def __init__(self, api_key: str, limits: FmpToolLimits) -> None: ...

    def _get(self, path: str, params: dict) -> dict:
        """GET 请求，注入 apikey，捕获所有异常，返回归一化结果。
        成功：{"ok": True, "data": <parsed_json>}
        失败：{"ok": False, "error": {"code": "fmp_*", "message": "..."}}
        """

    # 财务报表（标准化）
    def get_income_statement(self, symbol: str, period: str, limit: int) -> dict: ...
    def get_balance_sheet(self, symbol: str, period: str, limit: int) -> dict: ...
    def get_cash_flow(self, symbol: str, period: str, limit: int) -> dict: ...

    # As Reported
    def get_income_statement_reported(self, symbol: str, period: str, limit: int) -> dict: ...
    def get_balance_sheet_reported(self, symbol: str, period: str, limit: int) -> dict: ...
    def get_cash_flow_reported(self, symbol: str, period: str, limit: int) -> dict: ...

    # 指标与比率
    def get_key_metrics(self, symbol: str, period: str, limit: int) -> dict: ...
    def get_financial_ratios(self, symbol: str, period: str, limit: int) -> dict: ...

    # 收入拆分
    def get_revenue_by_product(self, symbol: str, period: str) -> dict: ...
    def get_revenue_by_geography(self, symbol: str, period: str) -> dict: ...

    # 股票行情
    def get_quote(self, symbol: str) -> dict: ...
    def get_historical_price(self, symbol: str, from_date: str, to_date: str, limit: int) -> dict: ...

    # 外汇
    def get_forex_quote(self, pair: str) -> dict: ...
    def get_forex_history(self, pair: str, from_date: str, to_date: str) -> dict: ...

    # 预测
    def get_analyst_estimates(self, symbol: str, period: str, limit: int) -> dict: ...

    # 电话会议
    def get_transcript_dates(self, symbol: str) -> dict: ...
    def get_earnings_transcript(self, symbol: str, year: int, quarter: int) -> dict: ...

    # 内部人交易
    def get_insider_trades(self, symbol: str, transaction_type: str, limit: int) -> dict: ...
    def get_insider_statistics(self, symbol: str, limit: int) -> dict: ...

    # 公司
    def get_company_profile(self, symbol: str) -> dict: ...

    # 公司搜索
    def search_by_symbol(self, query: str, limit: int, exchange: str | None) -> dict: ...
    def search_by_name(self, query: str, limit: int, exchange: str | None) -> dict: ...
    def search_by_cik(self, cik: str, limit: int) -> dict: ...
```

### 9.4 工具清单（共 23 个）

| 工具名 | 对应端点 | tags | 截断策略 |
|--------|---------|------|---------|
| `fmp_income_statement` | `/stable/income-statement` | `fins,fmp,statement` | list_items/20 |
| `fmp_balance_sheet` | `/stable/balance-sheet-statement` | `fins,fmp,statement` | list_items/20 |
| `fmp_cash_flow` | `/stable/cash-flow-statement` | `fins,fmp,statement` | list_items/20 |
| `fmp_income_statement_reported` | `/stable/income-statement-as-reported` | `fins,fmp,statement,reported` | list_items/20 |
| `fmp_balance_sheet_reported` | `/stable/balance-sheet-statement-as-reported` | `fins,fmp,statement,reported` | list_items/20 |
| `fmp_cash_flow_reported` | `/stable/cash-flow-statement-as-reported` | `fins,fmp,statement,reported` | list_items/20 |
| `fmp_key_metrics` | `/stable/key-metrics` | `fins,fmp,metrics` | list_items/20 |
| `fmp_financial_ratios` | `/stable/ratios` | `fins,fmp,metrics` | list_items/20 |
| `fmp_revenue_by_product` | `/stable/revenue-product-segmentation` | `fins,fmp,segmentation` | list_items/20 |
| `fmp_revenue_by_geography` | `/stable/revenue-geographic-segmentation` | `fins,fmp,segmentation` | list_items/20 |
| `fmp_analyst_estimates` | `/stable/analyst-estimates` | `fins,fmp,estimates` | list_items/12 |
| `fmp_transcript_dates` | `/stable/earning-call-transcript-dates` | `fins,fmp,transcript` | list_items/50 |
| `fmp_earnings_transcript` | `/stable/earning-call-transcript` | `fins,fmp,transcript` | text_chars/40000 |
| `fmp_insider_trades` | `/stable/insider-trading/search` | `fins,fmp,insider` | list_items/50 |
| `fmp_insider_statistics` | `/stable/insider-trading/statistics` | `fins,fmp,insider` | list_items/20 |
| `fmp_quote` | `/stable/quote?symbol=` | `fins,fmp,market` | 无 |
| `fmp_historical_price` | `/stable/historical-price-eod/full?symbol=` | `fins,fmp,market` | list_items/90 |
| `fmp_forex_quote` | `/stable/quote?symbol=` | `fins,fmp,forex` | 无 |
| `fmp_forex_history` | `/stable/historical-price-eod/full` | `fins,fmp,forex` | list_items/90 |
| `fmp_company_profile` | `/stable/profile?symbol=` | `fins,fmp,company` | 无 |
| `fmp_search_by_symbol` | `/stable/search-symbol` | `fins,fmp,search` | list_items/10 |
| `fmp_search_by_name` | `/stable/search-name` | `fins,fmp,search` | list_items/10 |
| `fmp_search_by_cik` | `/stable/search-cik` | `fins,fmp,search` | list_items/10 |

DCF 工具可在后续迭代加入。

#### Pipeline 用法：Symbol 推导 Company Name

当 pipeline 只持有 ticker（如 `AAPL`）而需要公司名称时，可通过以下两种方式低消耗获取：

| 方式 | 工具 | 参数 | 返回字段 | 说明 |
|------|------|------|---------|------|
| 方法 A | `fmp_search_by_symbol` | `query=AAPL&limit=1` | `name` | 轻量，仅返回 symbol+name |
| 方法 B | `fmp_company_profile` | `symbol=AAPL` | `companyName` | 顽丰，同时获取行业/交易所/币种等 |

> 推荐默认使用方法 A（`fmp_search_by_symbol` + `limit=1`）：
> 响应极小，尔后费用也更低。若 pipeline 后续已需调用 `fmp_company_profile`（如需要 sector、exchange 等），则直接从其结果取 `companyName`。
>
> **CIK 映射**：屏彂处理/内部人交易任务中如已知 CIK，可用 `fmp_search_by_cik` 获取对应 ticker，
> 再进入其他财务报表工具生产查询。

---

### 9.5 永久缓存机制（FmpCache）

#### 设计动机

FMP 按调用次数计费（免费套餐 250 次/天）。历史财务数据一旦公布就不会变化（过去期的财务报表、历史价格、电话会议记录等），
容许对这类数据进行永久缓存——即写入一次，后续不再重新拉取，显著降低 API 调用消耗。

#### 缓存策略分类

> **关于追加历史数据的设计考量**
>
> 过去的财务期数据不会变更，但**未来会不断新增**：年报每年新增一期，日线价格每天新增一条。
> 若缓存键包含日期范围（如 `AAPL_2024-01-01_2024-06-30`），将来请求范围掩盖已缓存范围时必然 miss，远端数据全局重拉。
> 若指定 `PERMANENT` 不失效，年报发布后旧缓存永远读不到新期数据。
>
> 两条解决原则：
> 1. **财务报表**：缓存键不含 limit，一次读全量并存。缓存策略改用 **TTL_QUARTERLY**（年报）/ **TTL_MONTHLY**（季报），每次失效后拉取最新全量缓存。
> 2. **历史价格**：改用 **monthly-tile** 模式，每个已关闭月份为一个 PERMANENT 文件，当月为切工 TTL_DAILY。请求跜越多个月时，仅补拉未有缓存的月份，尝过所有历史数据。

| 类型 | 策略 | 失效逐辑 | 适用工具 | 理由 |
|------|------|-----------|----------|------|
| **TTL_QUARTERLY** | 90 天失效 | 拉全量重新写入 | 年报三表、As Reported、Key Metrics、Ratios、收入拆分 | 年报每年一期，90 天足够捕捉 |
| **TTL_MONTHLY** | 30 天失效 | 拉全量重新写入 | 季报三表、As Reported季报 | 季报每季岡一期，30 天迷失强局 |
| **PERMANENT_TILE** | 已关闭月不失效 | 仅补封未有的月份 | 历史价格、历史外汇 | 过去月份不可变，封居追加无需整体重拉 |
| **TTL_DAILY_TILE** | 24h 失效 | 单个月片重写 | 当月价格、当月外汇 | 当月甲板尚未关闭，数据日日新增 |
| **TTL_DAILY** | 24h 失效 | 文件整体重写 | 分析师预测、内部人统计、展示转日期列表 | 定期更新，不实时 |
| **NO_CACHE** | 不缓存 | — | 实时报价、外汇实时报价、公司概况 | 需要即时性 |

#### 缓存目录结构

```
{workspace_root}/.fmp_cache/
├── statements/         # 三表（年报/季报）TTL_QUARTERLY / TTL_MONTHLY
│   ├── AAPL_annual_income-statement.json
│   ├── AAPL_quarter_balance-sheet.json
│   └── AAPL_annual_income-statement_as-reported.json
├── metrics/            # Key Metrics / Ratios  TTL_QUARTERLY
│   ├── AAPL_annual_key-metrics.json
│   └── AAPL_annual_ratios.json
├── segmentation/       # 收入拆分  TTL_QUARTERLY
│   ├── AAPL_annual_product.json
│   └── AAPL_annual_geography.json
├── transcript/         # 电话会议记录  PERMANENT（单期文件）
│   ├── AAPL_2024_Q1.json
│   └── AAPL_2023_Q4.json
├── insider/            # 内部人交易  TTL_DAILY
│   ├── AAPL_trades_P.json
│   └── AAPL_trades_all.json
├── price/              # 历史价格   monthly-tile
│   ├── AAPL_2024-01.json  ← PERMANENT_TILE（已关闭月）
│   ├── AAPL_2024-02.json
│   ├── AAPL_2025-02.json  ← TTL_DAILY_TILE（当月）
│   ├── EURUSD_2024-01.json
│   └── EURUSD_2025-02.json
└── ttl/                # TTL_DAILY 类
    ├── AAPL_estimates_annual.json
    ├── AAPL_insider_stats.json
    └── AAPL_transcript_dates.json
```

> **monthly-tile 如何支持追加：**
> - 请求 AAPL 2024-01-01 到 2025-02-28：检查 2024-01 到 2025-02 共 14 个月片
> - 已缓存的月片直接读内存，2025-02（当月）检查 TTL
> - 仅对缺失月片远程请求；获取后写入对应月片文件
> - 组装全部月片 → 按日期排序 → 截取用户请求的精确范围

#### 缓存键设计

缓存键为文件名，由请求参数确定性拼接，**禁止使用 MD5/哈希**（确保可读、可手动删除、便于调试）：

| 工具 | 缓存键格式 | 示例 | TTL |
|------|----------|------|-----|
| 三表（年报） | `{SYMBOL}_annual_{endpoint}` | `AAPL_annual_income-statement` | TTL_QUARTERLY |
| 三表（季报） | `{SYMBOL}_quarter_{endpoint}` | `AAPL_quarter_balance-sheet` | TTL_MONTHLY |
| As Reported 年报 | `{SYMBOL}_annual_{endpoint}_as-reported` | `AAPL_annual_income-statement_as-reported` | TTL_QUARTERLY |
| As Reported 季报 | `{SYMBOL}_quarter_{endpoint}_as-reported` | `AAPL_quarter_cash-flow_as-reported` | TTL_MONTHLY |
| Key Metrics / Ratios | `{SYMBOL}_{period}_{key}` | `AAPL_annual_key-metrics` | TTL_QUARTERLY |
| 收入拆分 | `{SYMBOL}_{period}_{product\|geography}` | `AAPL_annual_product` | TTL_QUARTERLY |
| 电话会议 | `{SYMBOL}_{year}_Q{quarter}` | `AAPL_2024_Q1` | PERMANENT |
| 内部人交易 | `{SYMBOL}_trades_{type\|all}` | `AAPL_trades_P` | TTL_DAILY |
| 内部人统计 | `{SYMBOL}_insider_stats` | `AAPL_insider_stats` | TTL_DAILY |
| 历史价格（tile） | `{SYMBOL}_{YYYY-MM}` | `AAPL_2024-01` | PERMANENT_TILE / TTL_DAILY_TILE |
| 历史外汇（tile） | `{PAIR}_{YYYY-MM}` | `EURUSD_2024-01` | 同上 |
| 分析师预测 | `{SYMBOL}_{period}_estimates` | `AAPL_annual_estimates` | TTL_DAILY |
| 展示转日期列表 | `{SYMBOL}_transcript_dates` | `AAPL_transcript_dates` | TTL_DAILY |

> **财务报表缓存键不含 limit**：第一次拉取时以 `limit=1000`（实际可用期数上限）
> 写入全量缓存；后续请求无论 limit 多小，从缓存到内存裁切返回。

#### FmpCache 接口设计

```python
class FmpCache:
    """基于本地文件系统的 FMP 缓存。

    财务报表类：单一文件存全量期数数据，按 TTL_QUARTERLY/MONTHLY 失效。
    历史价格类： monthly-tile 模式，每个已关闭月为 PERMANENT 片，当月为 TTL_DAILY 片。
    不缓存类：直接过穿指 _get()。
    """

    BUCKET_STATEMENTS   = "statements"
    BUCKET_METRICS      = "metrics"
    BUCKET_SEGMENTATION = "segmentation"
    BUCKET_TRANSCRIPT   = "transcript"
    BUCKET_INSIDER      = "insider"
    BUCKET_PRICE        = "price"
    BUCKET_TTL          = "ttl"         # TTL_DAILY 类全部写此目录

    TTL_DAILY_SECONDS      = 86_400          # 1 天
    TTL_MONTHLY_SECONDS    = 30 * 86_400     # ~30 天
    TTL_QUARTERLY_SECONDS  = 90 * 86_400     # ~90 天

    def __init__(self, cache_dir: str) -> None:
        """初始化缓存，自动创建各桶目录。"""

    def read(self, bucket: str, key: str, ttl: int | None = None) -> list | dict | None:
        """读取单一文件缓存。

        Args:
            bucket: 缓存桶名。
            key: 缓存键（不含 .json 后缀）。
            ttl: 失效秒数，None 表示永久缓存。

        Returns:
            缓存命中返回数据，未命中或已失效返回 None。
        """

    def write(self, bucket: str, key: str, data: list | dict) -> None:
        """将响应数据写入缓存（原子写入：tmpfile + os.replace）。"""

    # --- monthly-tile 全局接口 ---

    def read_tiles(
        self,
        bucket: str,
        symbol: str,
        from_date: str,
        to_date: str,
    ) -> tuple[list, list[str]]:
        """读取覆盖 [from_date, to_date] 的月片缓存。

        Returns:
            (cached_rows, missing_months)
            - cached_rows: 已北月的合并数据（未加过日期范围过滤）
            - missing_months: 尚无缓存或已过期的月展列表，格式 'YYYY-MM'
        """

    def write_tile(self, bucket: str, symbol: str, month: str, data: list) -> None:
        """将单个月片数据写入缓存。

        Args:
            month: 'YYYY-MM' 格式。
        """

    def invalidate(self, bucket: str, key: str) -> bool:
        """删除指定缓存条目。返回是否实际删除。"""

    def invalidate_all(self, bucket: str | None = None) -> int:
        """清除指定桶的所有缓存，bucket=None 时清除全部。返回删除条数。"""

    def stats(self) -> dict:
        """统计各桶缓存条目数量与占用空间（字节）。"""
```

#### 与 FmpToolService 的集成方式

`FmpToolService._get_cached()` 作为带缓存的请求入口，工具层完全无感知：

```python
def _get_cached(
    self,
    path: str,
    params: dict,
    bucket: str,
    cache_key: str,
    ttl: int | None = None,
) -> dict:
    """带缓存的 GET 请求。

    流程：读缓存 → 命中直接返回 → 未命中则调 _get() → 写缓存 → 返回。
    """
    if self._cache is not None:
        cached = self._cache.read(bucket, cache_key, ttl=ttl)
        if cached is not None:
            return {"ok": True, "data": cached, "from_cache": True}

    result = self._get(path, params)
    if result["ok"] and self._cache is not None:
        self._cache.write(bucket, cache_key, result["data"])
    return result
```

各业务方法按策略选择调用方式：

| 方法 | 调用方式 | TTL |
|------|----------|-----|
| `get_income_statement` | `_get_cached(bucket="statements", ttl=TTL_QUARTERLY)` | 90 天 |
| `get_balance_sheet` | `_get_cached(bucket="statements", ttl=TTL_QUARTERLY)` | 90 天 |
| `get_cash_flow` | `_get_cached(bucket="statements", ttl=TTL_QUARTERLY)` | 90 天 |
| `get_income_statement_reported` | `_get_cached(bucket="statements", ttl=TTL_QUARTERLY¹)` | 90/30 天 |
| `get_balance_sheet_reported` | `_get_cached(bucket="statements", ttl=TTL_QUARTERLY¹)` | 90/30 天 |
| `get_cash_flow_reported` | `_get_cached(bucket="statements", ttl=TTL_QUARTERLY¹)` | 90/30 天 |
| `get_key_metrics` | `_get_cached(bucket="metrics", ttl=TTL_QUARTERLY)` | 90 天 |
| `get_financial_ratios` | `_get_cached(bucket="metrics", ttl=TTL_QUARTERLY)` | 90 天 |
| `get_revenue_by_product` | `_get_cached(bucket="segmentation", ttl=TTL_QUARTERLY)` | 90 天 |
| `get_revenue_by_geography` | `_get_cached(bucket="segmentation", ttl=TTL_QUARTERLY)` | 90 天 |
| `get_earnings_transcript` | `_get_cached(bucket="transcript", ttl=None)` | 永久 |
| `get_insider_trades` | `_get_cached(bucket="insider", ttl=TTL_DAILY)` | 1 天 |
| `get_historical_price` | `_get_cached_tiles(bucket="price")` | 月片策略 |
| `get_forex_history` | `_get_cached_tiles(bucket="price")` | 月片策略 |
| `get_transcript_dates` | `_get_cached(bucket="ttl", ttl=TTL_DAILY)` | 1 天 |
| `get_analyst_estimates` | `_get_cached(bucket="ttl", ttl=TTL_DAILY)` | 1 天 |
| `get_insider_statistics` | `_get_cached(bucket="ttl", ttl=TTL_DAILY)` | 1 天 |
| `get_quote` | `_get()`（不缓存） | 无 |
| `get_forex_quote` | `_get()`（不缓存） | 无 |
| `get_company_profile` | `_get()`（不缓存） | 无 |

> ¹ As Reported 年报用 TTL_QUARTERLY；季报用 TTL_MONTHLY（根据 `period` 参数在调用时动态选择）。

#### `_get_cached_tiles` 的工作流程

```python
def _get_cached_tiles(
    self,
    path: str,
    symbol: str,
    from_date: str,
    to_date: str,
    bucket: str,
) -> dict:
    """带 monthly-tile 缓存的历史价格请求。

    流程：
    1. read_tiles() 获取已缓存数据 + 缺少月別列表。
    2. 对每个缺少月庞程拿到当月，按月片担取各月数据并写入 write_tile。
    3. 将全部月片合并、按 date 排序，截取 [from_date, to_date] 精确范围。
    4. 返回 {ok: True, data: [...], from_cache: bool}。
    """
```

> **按月片担取的 API 策略**：对最少缺少岖0 年、平均尚快的情况，也可以和并所有缺少月庞为一个展宽的日期范围以减少 HTTP 请求次数。

#### 缓存目录配置

在 `run.json` 中增加 `cache_dir` 字段：

```json
{
  "fmp": {
    "api_key": "{{FMP_API_KEY}}",
    "cache_dir": "{workspace}/.fmp_cache",
    "limits": { ... }
  }
}
```

- `{workspace}` 由 `config.py` 在加载时替换为实际 workspace 路径，与 SEC 缓存目录 `.sec_cache/` 保持一致的位置约定。
- 若未配置 `cache_dir`，`FmpCache` 不实例化，`FmpToolService` 直接走 HTTP 路径。

#### 原子写入安全

`FmpCache.write()` 必须使用原子写入（`tmpfile + os.replace()`），防止并发写入时读到半成文件：

```python
def _write_atomic(path: pathlib.Path, data: object) -> None:
    """将 data 原子性写入 JSON 文件。"""
    tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp_path, path)  # 原子替换
    except Exception:
        os.unlink(tmp_path)         # 写入失败时清理临时文件
        raise
```

---

## 10. HTTP 客户端

`requirements.txt` 已包含 `httpx>=0.27.0`，**直接使用 `httpx`（同步模式）**，无需新增依赖：

```python
import httpx

with httpx.Client(timeout=self._limits.http_timeout) as client:
    resp = client.get(url, params=params)
    resp.raise_for_status()
```

工具执行场景为同步上下文（ToolRegistry.execute），保持同步调用即可；
未来如有异步需求，`httpx.AsyncClient` 接口完全兼容，迁移成本极低。

---

## 11. 与现有 fins_tools.py 的关系

| 工具集 | 数据来源 | 核心依赖 | 典型使用场景 |
|--------|---------|---------|------------|
| `fins_tools.py` | 本地 SEC 文件（已下载处理） | `DocumentRepository` + `ProcessorRegistry` | 读原文、查章节、搜文档 |
| `fins/fmp_tools/`（新） | FMP REST API（实时拉取） | `FmpToolService`（HTTP） | 查结构化财务数字、行情、分析师预测 |

两套工具**互补不冲突**，在同一个 `ToolRegistry` 实例上分别注册即可。
典型工作流：用 fins_tools 读 10-K 原文分析具体段落，用 fmp_tools 拉历史财务数字做横向对比。

---

## 12. Tool Guidance Prompt 设计建议

在 `alpha/config/prompts/` 中新增 `fmp_tool_guidance.md`，使用现有 `<when_tag fmp>` 语法：

```markdown
<when_tag fmp>
## FMP 工具使用规则

**通用参数**：`period` = `annual`（年报）或 `quarter`（季报）；
`limit` 控制返回期数（默认 8 期：近 2 年季报 / 近 8 年年报）。

**必须先查再读**：电话会议先调 `fmp_transcript_dates` 确认可用季度，
再调 `fmp_earnings_transcript`。

**收入拆分**：`fmp_revenue_by_product` / `fmp_revenue_by_geography` 的字段名
是动态业务标签（如 "iPhone"、"Americas Segment"），需直接读取键名。

**内部人交易**：优先使用 `fmp_insider_statistics`（季度聚合买卖比），
需要具体明细时再调 `fmp_insider_trades`。

**As Reported 报表**：字段名为原始 XBRL tag，跨公司比较请用标准化版本；
仅在需要与 SEC 原始申报数字完全一致时使用 As Reported。
</when_tag>
```

---

## 13. 建议实现顺序

1. `fins/fmp_tools/limits.py` — `FmpToolLimits` dataclass。
2. `fins/fmp_tools/cache.py` — `FmpCache`（read/write/invalidate/stats）+ 单测。
3. `fins/fmp_tools/service.py` — `FmpToolService._get()` + `_get_cached()` + 所有业务方法 + 错误归一单测。
4. `fins/fmp_tools/tools.py` — `register_fmp_tools` + 20 个工具工厂函数。
5. `alpha/config/run.json` — 增加 `fmp` 配置块（`{{FMP_API_KEY}}`、`cache_dir`）。
6. `alpha/config.py` — 解析 `run.json` 的 `fmp` 字段并创建 `FmpToolService`。
7. `tests/fins/test_fmp_cache.py` + `test_fmp_service.py` + `test_fmp_tools.py` — 覆盖缓存命中/未命中/TTL失效/并发写入、错误归一、截断。
8. `alpha/config/prompts/fmp_tool_guidance.md` — 更新 Tool Guidance。

---

## 14. 待确认事项

- [ ] A 股/港股实际可用性验证（建议用 `0700.HK` / `600519.SS` 测试三表返回情况）。
- [ ] 电话会议记录覆盖范围：美股 8,000+ 公司，港股/A 股覆盖待实测。
- [ ] `fmp_revenue_by_product` 的 `structure=flat` 参数行为需实测（FMP 文档对 flat 结构的具体返回格式描述不一致）。
