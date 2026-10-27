# Program: Alpha 可检验判断与双层输出

- Overall status: `完成`
- Profile: `Lite`
- Contract status: `Confirmed`
- Active plan node: `None`
- Latest evidence: `workspace/tmp/alpha-judgment-validation/final-tests.txt`
- Current blocker: `None`
- Next step: `None`
- Next checkpoint: `None`
- Next human decision: `None`
- Owner: `Codex`
- Last updated: `2026-10-26`
- Clean state: `Not due`
- Last clean: `2026-10-26 / git diff --check；临时验证文件仅位于workspace/tmp，未新增依赖或数据库表`

## Outcome

- Problem: 中国财报原件含三表但标准接口不支持；研究缺少可检验判断、证据关联及跨轮复盘；聊天摘要与完整报告缺少稳定交付约定。
- Success: 当前 coding agent 可读取有效中国财报三表，持久保存收益约定、核心判断与不可变复盘，查询到期判断，并输出简短聊天摘要和有来源的单公司/比较报告至既有Notion发布路径。
- Collaboration intent: 用户已明确要求更新设计与实现；自主完成验证，不重复请示。
- Non-goals: 不依赖Telegram、不执行交易、不部署定时任务、不新增通用工作流、不宣称结构校验能证明投资判断正确；不因本次测试发布真实研究或修改Notion历史页面。

## Constraints

- Strategic defaults: AGENTS.md；UI → Service → Host → Agent；Fins仓储唯一访问原件；中文docstring、严格类型；只修改相关代码。
- Tactical objective: 利用现有不可变工作记录和报告版本保存判断，避免新增并行数据库和复杂状态机。
- Imperative bounds: 修复以真实已入库Docling原件及失败回归为依据；证据链接、研究所有权、信息截止日和原预测不可改写；任何schema变更必须进入init迁移。
- Negotiable space: 模块拆分、工具显式参数及摘要呈现可按现有模式实现，报告章节不机械固定。
- Material assumptions: 到期复盘由coding agent按需查询触发，不承诺关闭客户端后自动执行；正式Notion发布仍需要既有数据验收。
- Active unknowns: 根因已确认并修复：Docling处理器缺标准三表接口，通用读表将续页首行提升为表头；最终全量静态检查及311项回归已通过；任意中国财报格式支持仍不在本次验收范围内。
- Escalate when: 需要新的外部凭据、改变Invest目标、破坏历史研究或执行交易；其它可逆实现选择自主处理。

## Acceptance

| ID | Condition | Verification | Pass condition |
|---|---|---|---|
| A-001 | 中国财报真实三表可读 | 真实紫金入库Docling及CN/HK变体fixture，经Fins标准接口读取 | 有正确期间、币种、单位、数值、表格定位；母公司表不混入合并表，缺失仍报缺口 |
| A-002 | 核心判断可追溯且跨轮不可变 | 工具/仓储测试，断线后新轮读取 | 收益来源、期限、机制、假设、反证及可观察检验完整；无效证据及跨研究引用拒绝 |
| A-003 | 复盘可纠错 | 跨轮复盘与到期查询测试 | 原预测保留；记录实际结果、证据、变化及错误类型，支持信息不足与延期；历史查询不泄漏未来 |
| A-004 | 双层输出有效 | 候选、MCP及Notion模拟旅程 | 摘要突出判断/变化/分歧/需决策项；单公司与比较正文分开，版本/发布状态由可信端提供 |
| A-005 | 质量与使用文档同步 | 受影响pytest、pyright、覆盖率、文档示例核验 | 测试通过，无新增类型错误；新增关键文件覆盖率≥80%；设计与实际入口一致 |

## Plan

| Node | Status | Action | Verification | Evidence | Reflection |
|---|---|---|---|---|---|
| NODE-001 | `完成` | 复现并修复中国财报标准三表 | 真实仓储原件和失败优先回归，核对负号/缩放/期间/合并范围 | workspace/tmp/alpha-judgment-validation/zijin-fins-standard-receipts.json | R-001 |
| NODE-002 | `完成` | 在现有工作记录加入收益约定、判断与证据关联 | 跨轮持久/幂等/所有权/错误引用测试 | tests/research/test_judgments.py | None |
| NODE-003 | `完成` | 增加复盘、到期查询及旧新判断对照 | 原判断不可变、截止与延期等边界测试 | tests/research/test_judgments.py | R-002 |
| NODE-004 | `完成` | 研究报告结构与可信聊天交付摘要 | 候选校验与外部MCP/Notion旅程，保留真实交付状态 | tests/research/test_mcp_entry.py | None |
| NODE-005 | `完成` | 同步设计、skill、README并完成验收 | 专项测试、pyright、覆盖率与文档路径 | workspace/tmp/alpha-judgment-validation/coverage.json | R-003 |

## Reflection Log

| ID | Scope | Evidence | Wrong / changed | Right / preserve | Next rule |
|---|---|---|---|---|---|
| R-001 | NODE-001 | workspace/tmp/alpha-judgment-validation/zijin-fins-standard-receipts.json | 通用读表提升首行、题注遗漏不能满足标准三表 | 复用Fins仓储和原始Docling网格，提取40/65/36行 | 标准接口核验有效值、口径与续页，不把原件存在当验收通过 |
| R-002 | NODE-003 | tests/research/test_judgments.py | 新约定和新预测不能改变历史判断的检验责任 | 固定原约定ID及截止，另存复盘 | 替代预测继续展示原判断的到期责任 |
| R-003 | NODE-005 | workspace/tmp/alpha-judgment-validation/coverage-summary.json | coverage按模块名提前导入会触发第三方重复导入 | 按alpha目录收集再核对目标文件 | 验证工具失败定位工具根因，不通过改生产逻辑绕过 |


## Completion Review

- Final result: coding agent主入口与Notion完整报告输出已接通；收益约定、核心判断、证据关联、原约定绑定、不可变复盘及到期查询已实现。正式交付摘要只采用真实版本和发布状态。中国Docling三表标准接口已修复。
- Evidence: `workspace/tmp/alpha-judgment-validation/final-tests.txt`（311通过；新增真实Docling题注回归见adapter-tests.txt）；`workspace/tmp/alpha-judgment-validation/full-pyright.txt`（0错误；新增测试的最终检查见adapter-pyright.txt）；`workspace/tmp/alpha-judgment-validation/coverage-summary.json`（新增关键文件91.7%—100%）；`workspace/tmp/alpha-judgment-validation/zijin-fins-standard-receipts.json`（利润40行、资产65行、现金36行）。
- Output artifacts: `docs/alpha/design.md`、`docs/alpha/coding-agent-guide.md`、`alpha/research/methods/assets/skills/alpha-research/SKILL.md`；相关包及测试README已同步。
- Unverified / residual risk: Notion新旅程使用真实MCP/Host和模拟远端完成写入与回读，未发布真实测试报告；没有后台定时调度；财报解析不承诺支持任意版式；不会回填或改写历史投研报告。固定方法仅影响新受理输入，已运行MCP客户端需重连加载代码。
- Remaining work: 本次范围内无；真实研究在下一次新轮按更新后的skill执行。
- Completed: 2026-10-26。
