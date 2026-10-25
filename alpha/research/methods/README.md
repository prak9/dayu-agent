# invest 方法与确定计算

`alpha_invest` 是不依赖 alpha 主进程的强类型标准库计算包，输入与输出均为递归 JSON 类型。当前开发入口：

```python
from alpha.research.methods.alpha_invest.pe_implied_growth import calculate

result = calculate({
    "base_eps": 1, "years": 5, "cost_of_equity": 0.1,
    "cash_conversion": 1, "terminal_cash_conversion": 1,
    "terminal_growth": 0, "growth": 0,
})
assert result["status"] == "ok"
```

命令入口为 `python -m alpha.research.methods.alpha_invest METHOD INPUT.json`，`METHOD` 支持下列四种固定方法；它不执行任意代码。

- `pe_implied_growth.calculate` 保留 invest 的 `conditional-pe-fcfe-v1`。它给出固定股数及现金转化假设下的条件 EPS 增长门槛，支持基期/显式远期 EPS 桥接及敏感性分析。求根边界不包根会返回 `unbracketed`；不能解释为经济不可能。缺数、非有限数、非法增长/现金转化率和混合口径会失败。
- `option_distribution.calculate` 保留 `discrete-call-spread-risk-neutral-v1` 的价差方法，只接受已经清洗且口径统一的欧式等价看涨期权网格。输出是风险中性终价分布，边缘区间只表示网格以外的质量，不估计尾部内部形状。期限、时点和价格口径在输出中保留。
- `gf_dma.calculate` 保留 `gf-dma-v1` 模块映射，缺失或不满足门槛的输入保留 N/A。即使模块齐全，未经校准的总分也保持禁用。
- `validate_data.validate` 检查 invest v1/v2 的数字来源、口径、来源时间精度、历史截止日及声明的加总、增长、概率、期间差分。它不能证明原始材料支持数字，也不能证明预测可靠。其命令方法名为 `validate_data`；退出码 0 只表示报告生成，自动调用方必须另外要求 `status == "pass"`。

期权实现修复了原脚本的一处数值边界：容差内极微小的上尾概率上升原先可产生负的区间概率。现在将这种舍入噪声夹至前一上尾，并显式记录 `rounding_adjustment`；超过容差的凸性违反仍直接失败，不对不可用报价进行经济修复。

`resources.read_packaged_method_files` 只读取随 wheel 分发的资源：invest 与实际 writing/研究参考引用闭包、运行约定、适配来源清单和独立计算代码，不访问开发机 skill 目录。首次入口载入运行约定与 invest，其余文档按需读取。研究报告在保存或直接聊天交付前，必须读取本轮固定方法中的 writing 与修订清单；分析论证另读论证指南，并完成全文修辞复核。纯计算、原始摘录和简短状态答复不要求扩写为报告。未分发的历史评测样例和研究飞轮专用执行器在引用处明确标注。

`FsResearchMethodStore` 按内容哈希提交资源快照，旧研究可按原哈希恢复。文件缺失、改写、额外代码或符号链接会明确失败；不会退回当前软件版本的方法包。目录提交后的确认中断可复用原快照，临时目录不参与读取。快照中的计算包可独立运行，执行时使用 `-B` 避免生成未纳入哈希的字节码文件。

`research.calculations.run_research_calculation` 在独立 Python 子进程中执行固定方法，使用 stdin 传入 JSON，叠加调用预算与 Host 取消令牌，限制 stdout/stderr 大小。非零退出、坏 JSON 和失败状态均拒绝；校验器退出码为零但 `status=fail` 时保留结构化报告并抛出拒绝异常。终止路径先结束进程并排空管道，再等待回收，避免输出超限时被暂停的管道阻塞收尾。启动中或运行中的外层任务取消也回收真实进程。

`tests/research/` 的计算与方法包测试覆盖正逆算、原脚本冻结样例、无套利、缺数、时点、舍入、引用闭包、旧方法保留和隔离运行。`tests/fixtures/invest/` 保留来源脚本 SHA256 及纯假设结果，运行不依赖开发机原 skill 路径。算术一致性不证明输入获得原始证据支持。
