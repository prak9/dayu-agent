# alpha Agent — 用户手册

`alpha Agent` 是每个投资者的助理分析师。

**推荐日常入口：当前 coding agent + Alpha MCP；完整报告输出到 Notion Invest。**安装接入、研究提问、多个 session、增量更新及归档故障处理见 [coding agent 与 Notion 使用指南](docs/alpha/coding-agent-guide.md)。这条路径无需 Telegram，分析直接由当前 coding agent 完成。

- `alpha Agent` 是一个面向买方财报分析场景的 Agent 系统，但它不是简单的功能组合，`alpha Agent` 让AI读财报的方式从丢给它整份财报“大海捞针”变成“按图索骥”，让数据有置信度，让投资结论、投资报告可审计、可追踪。
- `alpha Agent` 还具备完整的“宿主强约束下的 LLM in the loop 的能力”，基础架构能力上已经对齐 OpenClaw ，后续会加上现在 OpenClaw 能做的事情。

当前你可以用它完成四类工作：
- 财报数据管线：美股 / A 股 / 港股财报下载，美股 / A 股 / 港股财报上传。
- 投研问答：下载、上传财报后，执行 `prompt` 单次提问、`interactive` 多轮提问、或通过微信向`alpha Agent` 提问。
- 买方分析报告写作：下载、上传财报后，执行 `write` 写作。
- 结果渲染：把 Markdown 报告渲染为 HTML / PDF / Word。

本文档面向读者：
- 最终使用者。

如果你要参与开发，而不是只使用系统：
- 总览开发手册：[alpha/README.md](alpha/README.md)
- Host 手册：[alpha/host/README.md](alpha/host/README.md)
- Engine 手册：[alpha/engine/README.md](alpha/engine/README.md)
- Fins 手册：[alpha/fins/README.md](alpha/fins/README.md)
- 配置手册：[alpha/config/README.md](alpha/config/README.md)
- 贡献指南：[CONTRIBUTING.md](CONTRIBUTING.md)

## 0. 如果你想参与项目
- 定性分析模板 读起来机械感还很强，还没写出差异化：
  - 同一章节里，不同行业公司写出明显不同的判断路径。
  - 同一行业里，不同公司写出公司自己的特殊结构变量。
- 位于 Engine 的 web tools 现在的对抗challenge能力很弱，很多网站无法访问。
- **GUI 尚未实现**；
- **Web UI 已支持自选股、财报下载和交互式分析，仍处于早期阶段**。
- **WeChat UI 仅支持文本消息首版，还可添加更多好玩的功能**。
- 财报电话会议记录音频转录文字后信息提取（起码要区分信息来自提问还是回答）尚未实现。
- 财报presentation信息提取尚未实现。
- 欢迎围绕以下方向提交 issue 或 PR：
  - 普通文件（非财报文件）信息提取还需要优化。
  - 优化 Fins 里的港股/A股/美股财报信息提取。
  - Anthropic 原生 API 支持。
  - Durable memory / Retrieval layer（ Memory只实现了working memory 和 episode summary ）。
  - FMP 工具（调研工作已做，见 [docs/fmp_integration_research.md](docs/fmp_integration_research.md) ）尚未实现。
  - 更多LLM 工具。

## 1. 五分钟快速开始

### 1.1 安装

安装使用 `alpha Agent` 前需安装 Python 3.11。

#### 1.1.1 安装本地 alpha 源码

在已取得本版本源码的仓库目录中安装：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[browser,web]" -c constraints/lock-linux-x64-py311.txt
```

macOS 或 Windows 使用下面对应平台的 constraints。旧产品的远端 Release 文件不会因本地改名自动变成 alpha 安装包；安装本次改造版本请使用这份源码或由它构建的 wheel。

#### 1.1.2 安装本地构建的 wheel

```bash
python -m pip wheel . --no-deps --wheel-dir dist
python -m pip install ./dist/alpha_agent-0.1.4-py3-none-any.whl
```

离线 bundle 的构建和 smoke 入口见开发文档，安装器会随当前源码使用 alpha 命令。

#### 1.1.3 clone 源代码安装

如果你要参与开发或本地调试源码，可以 clone 源代码后使用 editable 安装：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[test,dev,browser,web]" -c constraints/lock-macos-arm64-py311.txt
```

说明：

- macOS Intel 开发环境改用 `constraints/lock-macos-x64-py311.txt`
- Linux 开发环境改用 `constraints/lock-linux-x64-py311.txt`
- Windows 开发环境改用 `constraints/lock-windows-x64-py311.txt`
- `web` extras 启用 `alpha-web`（streamlit）入口；不需要 Web UI 时可从 extras 列表中省略

#### 1.1.4 安装额外依赖

安装完成后，还需要执行一次：  

```bash
playwright install chromium
```

如需使用 `alpha-render` 将 Markdown 导出为 **HTML、Word（.docx）或 PDF**，需要安装 `pandoc`，详见「§6 渲染输出」。可选安装方式：

- macOS：`brew install pandoc`
- Ubuntu / Debian：`sudo apt-get install pandoc`
- Windows：`choco install pandoc` 或从 [pandoc 官网](https://pandoc.org/installing.html) 下载安装

### 1.2 验证安装

安装完成后，先确认命令入口可用：

```bash
alpha --help
alpha-wechat --help
alpha-render --help
```

`alpha-web` 入口需要先安装 `[web]` extras（参考 1.1.3 节示例命令），再执行：

```bash
alpha-web --help
```

### 1.3 初始化工作区与配置

安装后运行一次 `init`，交互式完成配置复制、模型供应商选择和 API Key 设置：

```bash
alpha init
```

从旧命名工作区升级前，先停止旧 CLI/Web/WeChat 进程，再对原工作区运行 `alpha init --base <工作区>`。命名迁移保留原件于 `.alpha_namespace_migration/original/`，将 `.dayu/host/dayu_host.db` 一致性备份为 `.alpha/host/alpha_host.db`，并更新已知配置和恢复路径。新旧目录并存、活跃旧执行或迁移期间配置冲突会明确拒绝；中断后重复执行同一命令可继续，成功后重复运行不再迁移。

`alpha init` 同时初始化独立研究存储，并为已有 Host 库新增持久受理表，保留历史会话和运行记录。

`init` 会依次执行：

1. 复制包内默认配置到 `./workspace/config/` ，复制包内默认写作模板到 `./workspace/assets/` 。
2. 让你选择初始化模型方案（Mimo / DeepSeek / OpenAI / Anthropic / Gemini / 通义千问 / 本地 Ollama / 自定义 OpenAI 兼容 API）。选中 Mimo / DeepSeek / Google Gemini 后会进入二级菜单挑选具体型号：
   - Mimo：Token Plan（默认）/ Token Plan SG / Pro 三档，三档各自独立 API Key
   - DeepSeek：Pro（默认）/ Flash 两档，共享 `DEEPSEEK_API_KEY`
   - Gemini：`gemini-2.5-flash`（默认）/ `gemini-2.5-pro` / `gemini-2.5-flash-lite` / `gemini-3.1-pro-preview` / `gemini-3.1-flash-lite-preview`
3. 输入对应 API Key 并永久写入环境变量。
4. 可选配置联网检索 API Key（TAVILY / SERPER / FMP）
5. 自动检测 HuggingFace 官方 Hub 连通性：不可达时默认启用镜像加速，可达时默认跳过。可选配置 `HF_TOKEN` 提升下载稳定性。
6. 自动配置 `transformers` / `huggingface_hub` / `tqdm` 输出降噪环境变量，避免下载进度打断终端状态栏。


可选参数：

```bash
alpha init --base ./my_workspace    # 指定工作区目录（默认 ./workspace）
alpha init --reset                  # 删除 .alpha / config / assets 后重新初始化
alpha init --overwrite              # 覆盖已有配置
```

API Key 申请地址：
- MIMO_PLAN_API_KEY / MIMO_PLAN_SG_API_KEY / MIMO_API_KEY：https://platform.xiaomimimo.com/#/console/api-keys
- DEEPSEEK_API_KEY：https://platform.deepseek.com/api_keys
- FMP_API_KEY：https://site.financialmodelingprep.com/developer/docs/dashboard
- TAVILY_API_KEY：https://app.tavily.com/home
- SERPER_API_KEY：https://serper.dev/

说明：
- 默认推荐 Mimo Token Plan（mimo-v2.5-pro-plan），性价比最优。（注： MIMO_PLAN_API_KEY / MIMO_API_KEY 是两个不同的KEY，不能混用）。
- 海外用户选Mimo Token Plan SG。
- 如需接入 OpenRouter 等聚合服务，可在 `init` 中选择”自定义 OpenAI 兼容 API”，填写 `CUSTOM_OPENAI_API_KEY`、Base URL、模型 ID 与最大上下文 tokens。
- 本地 Ollama 模型和自定义 OpenAI 兼容 API 在 `init` 时会根据最大上下文 tokens 自动配置 `conversation_memory`（>= 100 万 tokens 扩大工作记忆上限，< 100 万收紧情景记忆预算）；Ollama 的 `write_chapter` 并发 lane 默认设为 2。
- `--reset` 确认后会删除 `workspace/.alpha/`、`workspace/config/`、`workspace/assets/`，再按首次初始化流程重建；它比 `--overwrite` 更彻底，会一并清空运行时状态。
- 升级 alpha 后若运行命令时看到 `HostStore 检测到旧版 SQLite schema 与当前实现不兼容` 报错，按提示处理：优先删除报错信息里 `db_path` 指向的数据库文件后重启（仅丢失 host 运行状态，保留 conversation 历史与 `run.json`）；如果不方便定位也可以直接跑 `alpha init --reset` 完整重建工作区。
- 联网搜索默认可走 `auto`，若配置了 Tavily / Serper，会优先使用对应 provider。
- 若运行环境需要访问 `localhost`、私网 IP 或内网域名，可在 `workspace/config/run.json` 的 `web_tools_config.allow_private_network_url` 中显式打开内网访问开关。
- 修改默认模型请参考 [8. 模型配置](#model-config)。

工作区最重要的目录：

```text
workspace/
├── config/           # 运行时配置（覆盖包内默认配置）
├── assets/           # 定性分析模板（覆盖包内默认模板）
├── .alpha/            # 系统隐藏工作目录（batch 暂存、备份恢复等）
├── portfolio/        # 每个 ticker 的财报与材料
├── draft/            # write 输出目录
└── output/           # tool trace 等辅助输出
```

说明：`workspace/.alpha/` 由系统维护，保存 Host、研究、Telegram 状态及财报批处理恢复数据；请保留并随工作区备份，删除会丢失研究和恢复记录。

### 1.4 跑通第一条命令

推荐先下载一份财报：

```bash
alpha download --ticker AAPL
```

下载完成后，再跑一条单次 prompt：

```bash
alpha prompt "总结最新财报的主要风险" --ticker AAPL
```

如果你已经通过 `download`、`upload_filing` 或 `upload_filings_from` 导入过 AAPL 的财报，也可以直接提问；命令会自动检测本地财报并挂载财报工具后返回结果。

如果你希望先不指定 `ticker`，也可以这样写：

```bash
alpha prompt "总结苹果最新财报的主要风险"
```

> 也可在微信对话或`interactive`里发送"下载苹果财报"进行下载。


## 2. 系统入口总览

### 2.1 CLI 入口

统一入口：

```bash
alpha <subcommand> [参数]
```

直接执行 `alpha` 会打印总帮助和全部子命令简介；需要查看某个子命令的完整参数时，继续使用 `alpha <subcommand> --help`。

当前支持的主命令：

| 命令 | 用途 |
|------|------|
| `prompt` | 单次问答 |
| `interactive` | 交互式终端对话 |
| `write` | 自动逐章写作报告；传 `--summary` 时打印上次写作结果摘要 |
| `download` | 下载 filings |
| `upload_filing` | 上传单份财报 |
| `upload_filings_from` | 扫描目录并生成批量上传脚本 |
| `upload_material` | 上传补充材料 |
| `process` | 全量预处理（最终用户可无视） |
| `process_filing` | 预处理单份 filing（最终用户可无视） |
| `process_material` | 预处理单份 material（最终用户可无视） |
| `conv` | 管理带 label 的可恢复 CLI 对话（最终用户可无视） |
| `sessions` | 列出或关闭宿主会话（最终用户可无视） |
| `runs` | 列出运行记录（最终用户可无视） |
| `cancel` | 取消运行中的 run（最终用户可无视） |
| `host` | 宿主维护（清理孤儿运行/查看状态，最终用户可无视） |
> 注：预处理命令仅供开发使用，最终用户可忽略。

共享参数：

| 参数 | 适用命令 | 说明 |
|------|------|------|
| `--base` | 全部主命令 | 工作区根目录，默认 `./workspace` |
| `--config` | 全部主命令 | 配置目录，默认 `workspace/config` |
| `--ticker` | `prompt` `write` | 股票代码；传入后会把该 `ticker` 作为当前研究对象 |
| `--log-level` | 全部主命令 | 直接指定日志级别，可选 `debug`、`verbose`、`info`、`warn`、`error` |
| `--debug` | 全部主命令 | 把日志级别设为 `DEBUG` |
| `--verbose` | 全部主命令 | 把日志级别设为 `VERBOSE` |
| `--info` | 全部主命令 | 把日志级别设为 `INFO` |
| `--quiet` | 全部主命令 | 把日志级别设为 `ERROR` |
| `--model-name` | `prompt` `interactive` `write` | 指定模型配置名称 |
| `--temperature` | `prompt` `interactive` `write` | 覆盖模型 temperature |
| `--label` | `prompt` `interactive` | 把当前对话绑定到可恢复 label；`prompt` 会进入 labeled multi-turn，对应 scene 为 `prompt_mt` |
| `--new-session` | `interactive` | 不续接上一次 interactive 多轮会话，改为从头开始一个新会话 |
| `--web-provider` | `prompt` `interactive` `write` | 指定联网检索 provider，如 `auto`、`tavily`、`serper`、`duckduckgo` |
| `--enable-tool-trace` | `prompt` `interactive` `write` | 开启工具调用追踪，覆盖 `run.json` 中的 trace 配置 |
| `--tool-trace-dir` | `prompt` `interactive` `write` | 指定 trace 输出目录，覆盖 `run.json` 中的 trace 配置 |
| `--thinking` / `--no-thinking` | `prompt` `interactive` | 控制是否在终端回显模型思考过程 |

说明：
- `--log-level`、`--debug`、`--verbose`、`--info`、`--quiet` 是同一组日志参数，使用其一即可。
- `prompt`、`interactive`、`write` 还支持更多 Agent 运行参数，例如 `--tool-timeout-seconds`、`--max-iterations`、`--doc-limits-json`、`--fins-limits-json`；需要时可用 `alpha <subcommand> --help` 查看完整列表。
- 宿主管理命令同样支持 `--base` / `--config` / 日志参数；例如 `alpha host --base ./workspace status`、`alpha sessions --base ./workspace --source cli --scene interactive`、`alpha conv --base ./workspace list`。
- `interactive` 默认会续接本地绑定的同一个多轮会话；如果上一次回答还没完整回显到终端，重启 CLI 会先把那次回答补完，再进入新的输入循环。

### 2.2 Web 入口（Streamlit）

基于 Streamlit 的 Web UI，可在浏览器中管理自选股、下载财报并进行按 ticker 绑定历史的交互式分析：

```bash
alpha-web
```

也可以用模块入口启动（等价）：

```bash
python -m alpha.web
```

默认使用 `./workspace` 作为工作区

启动后，默认打开 Local URL: http://localhost:8501 （如果 8501 端口被占用将按尝试其他端口）

功能说明：详见[alpha/web/README.md](alpha/web/README.md)

### 2.3 WeChat 入口

统一入口：

```bash
alpha-wechat <command> [参数]
```

直接执行 `alpha-wechat` 会打印总帮助和全部命令简介；需要查看某个命令的完整参数时，继续使用 `alpha-wechat <command> --help`。

当前支持的命令：

| 命令 | 用途 |
|------|------|
| `login` | 扫码建立微信登录态 |
| `run` | 以前台方式运行微信问答 daemon |
| `service install` | 安装后台托管配置 |
| `service start` | 启动后台托管 |
| `service restart` | 重启后台托管 |
| `service stop` | 停止后台托管 |
| `service status` | 查看后台托管状态 |
| `service list` | 列出当前 workspace 下已安装的后台托管实例 |
| `service uninstall` | 删除后台托管配置 |

常用参数：

| 参数 | 适用命令 | 说明 |
|------|------|------|
| `--base` | 全部命令 | 工作区根目录，默认 `./workspace` |
| `--config` | `login` `run` `service install` | 配置目录，默认 `workspace/config` |
| `--label` | 全部命令 | WeChat 实例标签，默认 `default`；状态目录映射到 `<base>/.alpha/wechat-<label>` |
| `--relogin` | `login` | 忽略已有登录态，强制重新扫码 |
| `--qrcode-timeout-sec` | `login` | 扫码登录超时秒数 |
| `--model-name` | `run` `service install` | 指定模型配置名称 |
| `--temperature` | `run` `service install` | 覆盖模型 temperature |
| `--web-provider` | `run` `service install` | 指定联网检索 provider |
| `--debug-sse` | `run` `service install` | 开启 SSE 高频调试日志 |
| `--debug-tool-delta` | `run` `service install` | 开启工具调用参数增量日志 |
| `--debug-sse-sample-rate` | `run` `service install` | 设置 SSE 调试日志采样率 |
| `--debug-sse-throttle-sec` | `run` `service install` | 设置 SSE 调试日志节流窗口 |
| `--tool-timeout-seconds` | `run` `service install` | 覆盖工具超时 |
| `--max-iterations` | `run` `service install` | 覆盖 Agent 最大迭代次数 |
| `--fallback-mode` | `run` `service install` | 覆盖超限处理模式 |
| `--fallback-prompt` | `run` `service install` | 覆盖超限补充提示 |
| `--max-consecutive-failed-tool-batches` | `run` `service install` | 覆盖连续失败工具批次上限 |
| `--max-duplicate-tool-calls` | `run` `service install` | 覆盖重复工具调用连续上限 |
| `--duplicate-tool-hint-prompt` | `run` `service install` | 覆盖重复工具调用提示词 |
| `--enable-tool-trace` | `run` `service install` | 开启工具调用追踪 |
| `--tool-trace-dir` | `run` `service install` | 指定 trace 输出目录 |
| `--doc-limits-json` | `run` `service install` | 覆盖文档工具 limits |
| `--fins-limits-json` | `run` `service install` | 覆盖财报工具 limits |
| `--typing-interval-sec` | `run` `service install` | 控制 typing 提示发送间隔 |
| `--delivery-max-attempts` | `run` `service install` | 控制微信 reply delivery 的最大发送次数 |

说明：
- `login` 用于建立或刷新登录态。
- `run` 用于在当前终端以前台方式运行。
- 同一个 `--label` 对应同一个 `state_dir`；当前实现会对 `state_dir` 加 daemon 单实例锁，避免前台 `run` 和后台 service 或两个前台进程并发运行导致重复补发。
- `service install/start/stop/status/list/uninstall` 用于以后台服务的形式运行。
- Windows 目前不支持 `service` 相关命令；在 Windows 上可继续使用 `login` 和 `run`。

## 3. 最常用工作流

### 3.1 财报下载：`download`

命令用途：
下载美股、A 股或港股财报到本地工作区，供后续问答、对话和写作复用。
A 股使用巨潮主源，港股使用披露易主源。

参数 / 说明：

| 参数 | 说明 |
|------|------|
| `--ticker` | 必填，股票代码，传入半角逗号分隔的股票代码标识有多地上市 |
| `--forms` | 可选，指定表单类型，如 `10K`、`10Q`、`DEF14A` |
| `--start` | 可选，开始日期，支持 `YYYY`、`YYYY-MM`、`YYYY-MM-DD` |
| `--end` | 可选，结束日期，支持 `YYYY`、`YYYY-MM`、`YYYY-MM-DD` |
| `--overwrite` | 可选，覆盖本地已存在结果 |
| `--rebuild` | 可选，只基于本地已下载文件重建 `meta/manifest`，不重新下载 |
| `--infer` | 可选，使用 FMP 推断跨市场 alias；成功时与 SEC alias 合并，失败时回退到 `--ticker` CSV 中的显式 alias |
| `--base` | 可选，工作区根目录，默认 `./workspace` |
| `--config` | 可选，配置目录，默认 `workspace/config` |

命令示例：

```bash
alpha download --ticker AAPL
```

常见命令示例：

```bash
alpha download --ticker AAPL --forms 10K 10Q --start 2024 --end 2025
alpha download --ticker AAPL --forms 10K
alpha download --ticker AAPL --rebuild
alpha download --ticker 600519 --forms FY H1 Q1 Q2 Q3 Q4 --start 2024 --end 2026
alpha download --ticker 0700 --forms FY H1 Q1 Q2 Q3 Q4 --start 2024 --end 2026
alpha download --ticker 0700 --rebuild
alpha download --ticker BABA,9988,9988.HK --infer
```

命令说明：
- `download` 会根据 `ticker` 自动路由到对应市场。
- `download`、`upload_filing`、`upload_material`、`upload_filings_from` 的 `--ticker` 支持 CSV（半角逗号分隔）；CSV 中**每个 token 都会走真源归一化**（如 `9988.HK`→`9988`）后再整体去重。首个归一化结果作为 canonical ticker，其余作为显式 alias 写入 meta，便于工具后续用任意跨市场变形命中同一公司。
- `--ticker` 支持 `0700.HK` / `HK.00700` / `600519.SH` / `sh600519` / `AAPL.US` / `BRK.B` 等常见变形，内部统一归一化到裸码（港 4 位补零、沪深 6 位、美股类股分隔符统一为横杠，如 `BRK.B`→`BRK-B`）。公司名仍可作为 ticker 传入，由仓储 alias 查表兜底。
- 显式传 `--infer` 时，CLI 会把 `--ticker` 里的显式 alias 与 FMP infer 结果合并；`download` 场景下 pipeline 还会继续与 SEC 返回的 alias 合并。
- 美股下载未显式传 `--start` 时，年报（`10-K`/`20-F`）默认覆盖 5 年，季报（`10-Q`/季报型 `6-K`）默认覆盖 2 年；`8-K`、SC13 等事件类表单仍按各自默认窗口处理。
- A 股下载当前使用巨潮主源，港股下载当前使用披露易主源，默认 forms 均为 `FY H1 Q1 Q2 Q3 Q4`；未显式传 `--start` 时，年报默认覆盖 5 年，半年报/季报默认覆盖 2 年；`Q2` 与 `H1`、`Q4` 与 `FY` 均作为独立期间处理，不互相归一。下载完成定义为 PDF 落盘、`_docling.json` 落盘、source meta `ingest_complete=True` 且 `primary_document` 指向 `_docling.json`。中断后再次运行会优先复用已落盘 PDF，避免重复下载；`--rebuild` 只基于本地已下载的 PDF + Docling JSON 重建 meta/manifest，不访问主源。
- 港股 ticker 示例 `0700` / `00700` / `700.HK` 会归一化到同一 canonical ticker；A 股/港股缺失的独立季度报告会按 skipped 统计而不是 failed。
- 使用 `--infer` 功能需要申请FMP_API_KEY。
- 首次写入时会自动创建 `workspace/portfolio/{ticker}` 下的源文档目录，不要求你预先手动建好 `filings/`。
- `prompt`、`interactive` 在 `filings/` 缺失时不会直接退出；CLI 会提示当前无本地财报，并继续执行问答。
- 美股 / A 股 / 港股下载分别使用独立并发 lane；默认配置下同一市场下载串行执行，不同市场互不占用对方的下载许可。
- **也可在interactive / wechat中发送`下载xx公司财报`进行下载**

### 3.2 上传本地文件

命令用途：
上传本地下载好的财报。（A 股可通过 `download` 直接从巨潮下载；港股可通过 `download` 直接从披露易下载，也仍可上传本地整理的文件。）
把你已经准备好的补充材料纳入工作区，适合手动整理 PDF、电话会纪要、演示材料等场景。

参数 / 说明：

| 命令 | 关键参数 | 说明 |
|------|------|------|
| `upload_filing` | `--ticker` `--files` `--fiscal-year` `--fiscal-period` | 上传单份财报；`--action` 可选，默认按 document_id 自动判定 |
| `upload_filings_from` | `--ticker` `--from` | 扫描目录并生成批量上传脚本 |
| `upload_material` | `--ticker` `--forms` `--material-name` `--files` | 上传补充材料；`--action` 可选，`--fiscal-year/--fiscal-period` 可选并参与稳定 document_id 生成 |

命令示例：

```bash
alpha upload_filing \
  --ticker 0300 \
  --files ./tmp/美的2025Q1.pdf \
  --fiscal-year 2025 \
  --fiscal-period Q1 \
  --company-name 美的集团
```

常见命令示例：

```bash
alpha upload_filings_from \
  --ticker 0300 \
  --from ./workspace/source

alpha upload_filing \
  --ticker BABA,9988 \
  --files ./tmp/alibaba_2025_q1.pdf \
  --fiscal-year 2025 \
  --fiscal-period Q1 \
  --infer

alpha upload_material \
  --ticker AAPL \
  --forms EARNINGS_CALL \
  --material-name deck \
  --files ./tmp/deck.pdf
```

命令说明：
- `upload_filing` 和 `upload_material` 的 `--action` 现在都可省略；省略时会先按稳定 `document_id` 查工作区：不存在则 `create`，存在则 `update`，若原始上传文件指纹未变化则会在 Docling convert 前直接 `skip`。自动判定只覆盖 `create/update`；若要删除，必须显式传 `--action delete`。
- `upload_filing` 适合单份补录；每个 `ticker` 第一次上传财报时需要 `--company-name`，若显式传 `--infer`，则在工作区缺少公司级 `meta.json` 时可省略 `--company-name`，由 FMP 推断后补齐；若同时传了 `--company-name`，则以你显式传入的值为准；若 infer 失败且仍缺 `--company-name`，命令会直接失败。
- `upload_material` 的稳定 `document_id` 默认由 `form_type + material_name` 生成；若显式提供 `--fiscal-year/--fiscal-period`，它们也会参与 ID 生成。material 场景下 `document_id` 与 `internal_document_id` 恒等；显式传 `--document-id/--internal-document-id` 时，必须与这套稳定规则一致。
- `upload_filings_from` 不直接上传文件，而是先生成一份适配当前运行平台的可执行脚本；macOS / Linux 默认生成 `.sh`，Windows 默认生成 `.cmd`。
- `upload_filings_from` 未传 `--output` 时，默认把脚本写到 `--base` 指向的 workspace 根目录，文件名为 `upload_filings_{ticker}.sh` / `.cmd`。
- `upload_filings_from --infer` 只会在脚本生成阶段调用一次 FMP，并把“显式 CSV alias + infer alias”的合并结果，以及最终公司名直接 bake 到脚本正文；脚本头部的重生成命令仍会保留原始 `--ticker` 输入和 `--infer`。
- 使用 `--infer` 功能需要申请FMP_API_KEY。
- 生成脚本头部会附带一条注释形式的 `python -m alpha.cli upload_filings_from ...` 重跑命令；脚本正文里的批量上传命令也统一使用 `python -m alpha.cli`，这样在源码工作区里执行时不会依赖外部 `alpha` entrypoint。
- `upload_filings_from` 默认不会在脚本正文里写死 `--action`，这样每条命令都会在执行时按当前工作区状态自动判定 `create/update/skip`；只有你显式传了 `--action`，生成脚本才会固定动作。
- 生成脚本中的每条上传命令都会透传脚本调用时的额外参数；macOS / Linux 使用 `"$@"`，Windows 使用 `%*`，因此可直接执行 `./upload_filings_xxx.sh --overwrite` 之类的批量覆盖调用。
- `upload_filing --overwrite` 和 `upload_material --overwrite` 会先重置当前 `document_id` 的源文档存储，再完整重建该文档；不会像 SEC download 的 ticker 级 overwrite 那样清空同 ticker 下的其他文档。
- `upload_filing` 和 `upload_material` 在首次实际写入时会自动创建 `workspace/portfolio/{ticker}` 下的源文档目录；`upload_filings_from` 只生成批量上传脚本，不直接写入源文档。

### 3.3 单次问答：`prompt`

命令用途：
执行一次性提问，适合快速验证观点、提炼结论或补充某个具体问题。

参数 / 说明：

| 参数 | 说明 |
|------|------|
| `prompt` | 必填，单次执行的问题文本 |
| `--ticker` | 可选，指定研究对象 |
| `--label` | 可选，把本次提问绑定到可恢复 conversation；首次创建时 scene 为 `prompt_mt` |
| `--model-name` | 可选，指定模型配置 |
| `--temperature` | 可选，覆盖模型 temperature |
| `--thinking` / `--no-thinking` | 可选，控制是否回显模型思考过程 |
| `--debug` / `--verbose` | 可选，仅调整日志级别，不改变会话行为 |

命令示例：

```bash
alpha prompt "总结苹果最新财报中的主要风险"
```

常见命令示例：

```bash
alpha prompt "总结最新财报中的主要风险" --ticker AAPL
alpha prompt "总结苹果最新财报中的主要风险" --thinking
alpha prompt --label apple "先总结苹果最新财报中的主要风险"
alpha prompt "总结苹果最新财报中的主要风险" --model-name mimo-v2.5-pro
alpha prompt "总结苹果最新财报中的主要风险" --debug
```

命令说明：
- 使用之前请先下载/上传财报。
- 两种写法都可以：要么在问题里直接写公司名或股票代码，要么用 `--ticker` 明确指定研究对象；一般不需要两边重复写。
- 不带 `--label` 时，`prompt` 保持 one-shot，不承诺后续恢复；带 `--label` 时，本次提问会挂到该 label 对应的可恢复 conversation 上，后续可继续用 `prompt --label <label>` 或 `interactive --label <label>` 接着问。
- 带 `--label` 的 prompt 在本轮拿到最终回答前会独占该 label；如果另一个进程此时也尝试复用同一个 label，CLI 会直接报错并提示等待当前对话结束，或改用新的 `--label`。
- 默认不回显模型思考过程；如需在终端查看，显式传 `--thinking`。

### 3.4 交互式对话：`interactive`

命令用途：
启动一个终端会话，多轮会话连续追问，适合逐步拆解问题。

参数 / 说明：

| 参数 | 说明 |
|------|------|
| `--model-name` | 可选，指定模型配置 |
| `--temperature` | 可选，覆盖模型 temperature |
| `--thinking` / `--no-thinking` | 可选，控制是否回显模型思考过程 |
| `--label` | 可选，恢复或创建指定 label 的可复用 conversation；首次创建时 scene 为 `interactive` |
| `--new-session` | 可选，不续接上一次多轮会话，改为从头开始一个新会话 |
| `--debug` / `--verbose` | 可选，仅调整日志级别，不改变会话行为 |

命令示例：

```bash
alpha interactive
```

常见命令示例：

```bash
alpha interactive --model-name mimo-v2.5-pro
alpha interactive --temperature 0.2
alpha interactive --thinking
alpha interactive --label apple
alpha interactive --new-session
alpha sessions --source cli --scene interactive
alpha conv status --label apple
alpha interactive --verbose
```

命令说明：
- 使用之前请先下载/上传财报。
- `interactive` 默认每次进入都会续接同一个多轮会话，适合连续追问。
- `interactive` 会把当前会话绑定保存在 `<workspace>/.alpha/interactive/state.json`，重新启动时默认续接上一次会话历史。
- 如果你想从头开始一轮新的对话，显式传 `--new-session`；它会丢弃本地保存的旧会话绑定，改为新开一个会话。
- 如果你想显式复用某条长期对话，使用 `--label`。同一个 label 可在 `prompt --label` 与 `interactive --label` 之间互通；第一次通过 `prompt --label` 创建的会话底层 scene 为 `prompt_mt`，第一次通过 `interactive --label` 创建的会话底层 scene 为 `interactive`，之后恢复时沿用首次创建时的 scene。
- 带 `--label` 的 CLI 启动时，会明确提示当前是“新创建标签”还是“恢复标签”；`prompt --label` 在回答末尾还会再次打印标签提示框，方便你后续继续复用同一个 label。
- 同一个 label 在任意时刻只能被一个 CLI 进程占用：`interactive --label` 会在整个 REPL 生命周期内持有该 label，直到双 `Ctrl+D` 完整退出；`prompt --label` 会在本轮返回最终回答前持有该 label。若命中占用中的 label，CLI 会提示你等待当前对话结束后重试，或改用新的 `--label`。
- 如果你在 workspace 本地覆写了 `prompt_mt` 或其他带 label 会命中的 scene manifest，必须保留 `conversation.enabled=true`；否则 CLI 会直接拒绝执行该 labeled conversation。
- 如果某个 label 对应的底层 session 已经被 `alpha sessions close` 关闭，下次再用同名 `--label` 时，CLI 会先提示“旧对话已关闭”，再按全新对话重新创建该 label；如果你是通过 `conv remove --label` 主动释放 label，则下次直接按普通新建处理，不额外提示。
- 如果你想查看底层 Host session，可用 `alpha sessions --source cli --scene interactive` 或 `alpha sessions --source cli --scene prompt_mt`；如果你想查看或释放 label 到会话的映射，使用 `alpha conv list`、`alpha conv list --all`、`alpha conv status --label <label>` 与 `alpha conv remove --label <label>`。其中 `conv list` 默认只展示 active 的 labeled conversation，`conv list --all` 额外包含已关闭对话；若某个 label 的 registry record 已漂移到不存在的 Host session，CLI 会先自动清理再继续执行，不再展示 `missing`。`conv remove --label` 会先关闭底层 session（若仍存在），再释放该 label；之后同名 `--label` 会从全新对话开始。若你通过 `sessions close` 关闭了某个带 label 的底层 session，下次同名 `--label` 会在提示后创建新的会话，而不是恢复旧 transcript。若你需要诊断底层 `session_id`，请用 `conv status --label <label>` 或直接查看 `sessions`。
- 默认不回显模型思考过程；如需在终端查看，显式传 `--thinking`。

### 3.5 微信对话 daemon：

命令用途：
以ClawBot的形式运行微信问答通道。

参数 / 说明：

| 命令 | 关键参数 | 说明 |
|------|------|------|
| `login` | `--label` `--relogin` `--qrcode-timeout-sec` | 建立或刷新登录态 |
| `run` | `--model-name` `--temperature` `--web-provider` `--debug-sse` `--fallback-mode` `--enable-tool-trace` | 在当前终端以前台方式运行 |
| `service install` | `--label` `--model-name` `--temperature` `--web-provider` `--debug-sse` `--fallback-mode` `--enable-tool-trace` | 安装后台服务 |
| `service start` | `--label` | 启动后台服务 |
| `service restart` | `--label` | 重启后台服务 |
| `service stop` | `--label` | 停止后台服务 |
| `service status` | `--label` | 查看后台服务状态 |
| `service list` | 无 | 列出当前 workspace 下已安装的后台服务实例 |
| `service uninstall` | `--label` | 删除后台服务 |

说明：
- 使用之前请先下载/上传财报。
- 首次使用时，一般先执行 `login`，再执行 `run` 或 `service install`。
- `run` 直接在命令行窗口前台运行。
- `service` 适合长期后台运行。
- `service` 相关命令目前支持 macOS 和 Linux；Windows 暂未支持。
- 用不同的 `--label`，并分别由不同扫码主体执行 `login`，可以多开。默认实例标签是 `default`，对应状态目录 `workspace/.alpha/wechat-default`。一个完整例子如下：

```bash
# 实例 A：扫码主体 A 登录，安装并启动 service
alpha-wechat login --label a
alpha-wechat service install --label a --model-name mimo-v2.5-pro-thinking
alpha-wechat service start --label a

# 实例 B：扫码主体 B 登录，安装并启动 service
alpha-wechat login --label b
alpha-wechat service install --label b --model-name deepseek-v4-flash-thinking
alpha-wechat service start --label b

# 列出当前 workspace 下已安装的实例
alpha-wechat service list
```

- 多开后，`start` / `restart` / `stop` / `status` / `uninstall` 都要继续带对应实例的同一个 `--label`，这样命中的才是同一个后台 service；忘记有哪些实例时可直接执行 `alpha-wechat service list`。

命令示例：

```bash
alpha-wechat login
alpha-wechat run
```

常见命令示例：

```bash
alpha-wechat login --relogin
alpha-wechat run --model-name mimo-v2.5-pro-thinking --temperature 0.4
alpha-wechat run --enable-tool-trace
alpha-wechat service install
alpha-wechat service start
alpha-wechat service restart
alpha-wechat service stop
alpha-wechat service status
alpha-wechat service list
alpha-wechat service uninstall
```

命令说明：
- 同一微信会话里的连续追问会自动延续上下文，适合做多轮分析。
- 当前版本主要支持文本问答；更适合问财报、公司、行业和研究相关问题。
- 首次使用时先执行 `alpha-wechat login`；命令会打印并尝试打开登录二维码链接，用手机微信扫码确认即可。若你在管理多实例，统一用 `--label` 指定实例标签。
- `alpha-wechat run` 依赖本地已有登录态；若登录态失效，重新执行同一个 `--label` 的 `login` 即可。
- 同一个 `--label` 的前台 `run` 和后台 service 不能并发运行；新的 daemon 若发现该 `state_dir` 已被占用，会直接拒绝启动。
- macOS / Linux：如果你希望它长期后台运行，先执行 `alpha-wechat service install`，再执行 `alpha-wechat service start`。后续可用 `service restart`、`service stop`、`service status`、`service list`、`service uninstall` 管理。
- `service install` 会把当前 shell 里已设置的关键环境变量快照进后台 service 定义，包括配置文件里 `{{ENV_VAR}}` 占位符引用到的变量，以及少量代码直读变量（如 `SEC_USER_AGENT`、联网检索/FMP API key）。如果你后来改了 API key，需要重新执行一次 `alpha-wechat service install`；若后台 service 已在运行，再执行 `alpha-wechat service restart` 让新配置生效。
- `alpha-wechat service status --label <name>` 会直接打印日志定位信息：macOS 打印 stdout/stderr 文件路径；Linux 打印 `journalctl --user -u <label>.service -f` 查看命令。
- `alpha-wechat service list` 只列出当前 workspace 下已安装的实例，并回显实例标签、状态目录、系统 service label、运行状态和是否已有登录态。
- macOS 下默认日志分流语义是：stdout 文件保留全量运行日志，stderr 文件额外记录真正错误与异常堆栈；因此 ERROR 会同时出现在两边。
- Windows：目前没有后台托管命令，使用方式是先执行 `alpha-wechat login`，再执行 `alpha-wechat run`，需要持续运行时请保持终端窗口开启。
- 若需要重新扫码登录，可重启命令并加上 `--relogin`。

### 3.6 自动写作：`write`

命令用途：
基于模板逐章生成买方分析报告，适合在财报与补充材料准备好后批量写作。

参数 / 说明：

| 参数 | 说明 |
|------|------|
| `--ticker` | 必选，指定研究对象 |
| `--chapter` | 可选，只写指定章节 |
| `--fast` | 可选，只执行写作，不运行 `audit` / `confirm` / `repair` |
| `--force` | 可选，允许1-9章audit失败也能写作第 0 章和第 10 章 |
| `--infer` | 可选，只执行公司级 facet 归因并写回 manifest |
| `--summary` | 可选，只打印上次写作结果摘要，不进入写作 |
| `--resume` / `--no-resume` | 可选，控制是否断点恢复 |
| `--template` | 可选，写作模板路径，默认 `workspace/assets/定性分析模板.md`，回退 `alpha/assets/定性分析模板.md` |
| `--output` | 可选，输出目录，默认 `workspace/draft/{ticker}` |
| `--model-name` | 可选，主写作模型配置 |
| `--audit-model-name` | 可选，审计模型配置 |
| `--debug` / `--verbose` | 可选，仅调整日志级别，不改变会话行为 |

命令示例：

```bash
alpha write --ticker AAPL
```

常见命令示例：

```bash
alpha write --ticker AAPL --chapter "公司做的是什么生意"
alpha write --ticker AAPL --chapter "经营表现与核心驱动" --fast
alpha write --ticker AAPL --infer
alpha write --ticker AAPL --summary
alpha write --ticker AAPL \
  --template ./workspace/assets/定性分析模板.md \
  --output ./workspace/draft/AAPL \
  --enable-tool-trace
```

命令说明：
- 写任何章节前，系统都会先检查当前 `ticker` 的写作 manifest 是否已有“公司级 facets”结果；若缺失，会自动先推理一次，再继续写作。
- 默认会复用 manifest 中已有的“公司级 facets”，不会每次重跑。
- 显式传 `--infer` 时，只会强制重跑一次“公司级 facets”并写回 manifest，随后立即退出，不进入章节写作。
- 按场景使用参数：
  - 第一次完整写报告：直接运行 `alpha write --ticker AAPL`。
  - 上次写到一半中断，想从已有结果继续：直接重新运行同一条命令即可；默认就是 `--resume`。
  - 只想快速出初稿，不想等待审查和修复：加 `--fast`。
  - 上一次是用 `--fast` 跑的，想继续沿用这套“只写正文”的方式：继续加 `--fast` 再运行。
  - 只想重写某一章正文：用 `--chapter "章节名" --fast`。
  - 前面章节还没完全通过检查，但你仍然想先生成第 0 章或第 10 章看结果：加 `--force`。
  - 只想刷新公司级归因，不进入正式写作：用 `--infer`。
- 章节不满意时，推荐这样处理：
  - 正常模式 `write` 写完后，发现第 8 章不满意：先运行 `alpha write --ticker AAPL --chapter "第8章的章节名"` 重写这一章；再运行 `alpha write --ticker AAPL`，把新章节应用到整份报告。
  - `write --fast` 写完后，发现第 8 章不满意，且你还想继续保持“快速草稿”模式：先运行 `alpha write --ticker AAPL --chapter "第8章的章节名" --fast` 重写这一章；再运行 `alpha write --ticker AAPL --fast`，把新章节应用到整份草稿报告。
  - 单独重写某一章时，不会自动重建第 0 章和第 10 章。
  - 重写某一章后，再跑一次全文 `write` 时，系统会重新生成整份报告文件；但默认 `--resume` 会跳过当前模式下已经完成的章节，所以第 0 章和第 10 章如果已完成，通常不会自动重写。
  - 如果你改动了中间章节后，希望第 0 章和第 10 章也反映新的内容，建议依次重跑该中间章节、第 10 章、第 0 章，最后再运行一次全文 `write`。

### 3.7 财报预处理：`process`

命令用途：
把已下载或已上传的财报做结构化预处理，并导出快照。

参数 / 说明：

| 参数 | 说明 |
|------|------|
| `--ticker` | 必填，股票代码 |
| `--document-id` | 可选，仅处理指定文档 ID；可重复传入，也支持单个参数中用逗号分隔多个 ID |
| `--overwrite` | 可选，覆盖已存在结果 |
| `--ci` | 可选，额外导出 `search_document` 与 `query_xbrl_facts` 快照 |
| `--base` | 可选，工作区根目录，默认 `./workspace` |
| `--config` | 可选，配置目录，默认 `workspace/config` |

命令示例：

```bash
alpha process --ticker AAPL --overwrite
```

常见命令示例：

```bash
alpha process --ticker AAPL
alpha process --ticker AAPL --ci
alpha process --ticker AAPL --ci --document-id fil_001 --document-id fil_002
```

命令说明：
- 预处理命令主要供开发和数据准备场景使用，最终用户通常不需要手动执行。
- 快照会写入 `workspace/portfolio/{ticker}/processed`。
- 传入 `--document-id` 时，只会重建这些文档的快照；不会清空同一 ticker 下其它 processed 结果。

## 4. 自动写作详解

`write` 命令怎么用，在前面已经说明清楚。  
这一节更关心另一件事：

- 当你想把报告写成自己满意的样子时，应该怎么理解写作流程
- 理解流程后，应该优先改模板的哪里

### 4.1 写作流程

自动写作的顺序可以先记成一条主线：

1. `infer`
2. 第 1-9 章
3. 第 10 章
4. 第 0 章
5. 来源清单（如果模板中存在）

你可以这样理解这条流程：

- `infer` 先判断这家公司属于什么业务类型、有哪些关键约束。
- 第 1-9 章先把主体分析写出来，这部分是整份报告的事实和判断基础。
- 第 10 章再基于前面各章，回答“是否值得继续深研与待验证问题”。
- 第 0 章最后回填“投资要点概览”，它不是独立开写，而是对前面结果做浓缩。
- 来源清单最后统一整理，不需要你手写。

为什么先理解这个流程很重要：
- 因为模板不是“想到什么就加什么”。
- 某个内容应该放在第 1-9 章、第 10 章，还是第 0 章，取决于它在这条流程里承担什么作用。
- 你先知道系统怎么写，再去改模板，通常会少走很多弯路。

### 4.2 第 10 章、第 0 章和来源清单有什么特殊性

这三个部分和普通章节不一样，改模板时要单独看待。

第 10 章 `是否值得继续深研与待验证问题`：
- 它不是普通分析章，而是“研究决策章”。
- 它更适合回答：现在值不值得继续投入研究资源；如果继续，接下来最该验证什么。
- 这章的重点不是重复前文，而是基于前文做取舍和排序。
- 标题不要改。你可以改内容框架，但不要把它改名成别的标题。

第 0 章 `投资要点概览`：
- 它是整份报告最后给读者看的“快速入口”。
- 这章更适合浓缩结论、核心判断和最重要的不确定性，不适合再铺一遍细节。
- 标题不要改。你可以改里面的小节和表达方式，但不要改一级标题。

来源清单：
- 它是末章，用来汇总整份报告的证据出处。
- 这章主要是为了让你快速检查“这份报告到底引用了什么”，不是拿来承载新的分析。
- 标题也不要改。

一级章节修改时，建议记住这条边界：
- `投资要点概览`、`是否值得继续深研与待验证问题`、`来源清单` 这三个一级标题保留原名。
- 修改 `是否值得继续深研与待验证问题` 标题会使这一章变成普通章节。
- 删除 `来源清单` 报告里就没有 `来源清单` 。
- 除这三个之外，其它一级章节的标题、顺序和数量都可以按你的研究框架调整。

### 4.3 什么时候应该改模板

如果你遇到下面这些情况，优先改模板，而不是先改 prompt：

- 报告整体导向不对，例如总在证明公司“为什么好”
- 某一章总是写偏，例如写成竞争百科、管理层赞歌或财务复述
- 某些信息对你很重要，但模型总是不写
- 某些内容只适合少数公司，但模型总是机械地写出来

你可以把模板理解成几层：

- high level：整篇文章怎么组织
- detail level：每一章内部怎么展开
- 条件项：什么内容只在特定公司、特定证据条件下才写

先想清楚自己不满意的是哪一层，再动模板，会比“到处加规则”更有效。

### 4.4 怎么改模板：先改文章骨架

如果你对整份报告都不满意，先改 high level，也就是整篇文章骨架。

**这里最重要的一点是：**

- 第 1-10 章不是固定编制。
- 你完全可以把普通分析章节改成 3 章、4 章、6 章，或者按你自己的研究框架重排。
- 系统并不要求你必须保留“第 1 章到第 10 章”这种数量和顺序。

你可以把“改文章骨架”理解成：决定整份报告一共要有哪些一级章节，以及这些一级章节按什么顺序出现。

最常见的文章骨架修改有：

- 调整一级章节顺序
- 新增或删除普通一级章节
- 把原来的 1-10 章改成更少或更多章
- 让报告更偏“继续研究 / 暂缓 / 放弃”的筛选框架
- 让报告更偏“重建公司全貌”，而不是“归纳优点”

适合先改文章骨架的场景：

- 报告整体方向不对
- 每一章都在写，但串起来不是你想要的研究路径
- 你希望读者先看到“值不值得继续看”，还是先看到“公司到底是什么”

改文章骨架时，优先问自己三个问题：

1. 这份报告最后要帮我做什么判断？
2. 我希望读者按什么顺序建立判断？
3. 哪些一级章节是真正必要的，哪些只是习惯性保留？

改文章骨架时，一级章节标题可以分成两类看：

- 普通一级章节：可以随便改标题、顺序和数量。你想保留 3 章、4 章、7 章都可以。
- 特殊一级章节：`投资要点概览`、`是否值得继续深研与待验证问题`、`来源清单` 建议保留原名。

其中最需要记住的是：

- `是否值得继续深研与待验证问题` 这个标题如果改掉，就会变成普通章节，不再按“研究决策章”处理。

如果这三个问题没想清楚，直接去改某一章的小节，通常只会把局部修得更复杂，不能真正改善整份报告。

### 4.5 怎么改模板：再改章节骨架

当整篇文章方向没问题，但某一章总是写偏时，再改 detail level，也就是章节骨架。

你可以把“改章节骨架”理解成：一级章节已经定了，现在再决定这一章里面具体怎么展开。

章节骨架通常包括：

- 本章目标
- 固定小节
- 小节标题
- 每个小节想回答的问题

适合先改章节骨架的场景：

- 标题看起来没问题，但模型总是抓错本章主问题
- 你希望模型固定输出某几个关键判断
- 你想删掉长期低价值的小节
- 你想把某一章从“信息罗列”改成“研究判断”

一个简单判断法：

- 如果你不满意的是“整份报告该有哪些章、这些章怎么排”，先改文章骨架。
- 如果你不满意的是“某一章里面该分哪几个小节、每个小节回答什么”，先改章节骨架。

### 4.6 条件项怎么用

条件项适合表达“只对某类公司才有意义”的补充内容。

例如：

- 只有平台公司才适合写网络效应
- 只有跨区域经营的公司才值得写重要 geography
- 只有证据足够精确时，才值得写更细的 segments、份额、客户集中度

经验法则：

- 所有公司都该写的，放进文章骨架或章节骨架
- 只有部分公司才该写的，放进条件项
- 某类行业优先看的判断入口，放进 `preferred_lens`
- 某类行业才值得补充的局部内容，放进 `ITEM_RULE`

`preferred_lens` 和 `ITEM_RULE` 可以这样理解：

- `preferred_lens`：这一章优先从什么视角进入判断
- `ITEM_RULE`：在特定条件下，额外补哪些局部内容

不要把写法技巧、句式要求、修辞规则塞进条件项。条件项更适合管“写不写什么”，不适合管“怎么写得好看”。

### 4.7 实用原则

好的模板，不是让模型“写更多”，而是让模型：

- 更快抓住这章真正要回答的问题
- 更少写偏
- 在证据不够时宁可少写，也不硬写

如果某条模板规则只是让报告更花哨、看起来更专业，但不帮助你更快做“继续研究 / 暂缓 / 放弃”的判断，通常就不值得加。

改模板时，一个很实用的顺序是：

1. 先改文章骨架
2. 再改章节骨架
3. 最后才补条件项

如果报告方向不对，通常先改“结构”和“本章问题”，效果会比一开始就堆很多条件规则更明显。

### 4.8 自动写作会产出什么

自动写作会在输出目录下按章节落盘。常见文件包括：

- `manifest.json`：记录章节状态，以及当前公司的“公司级 facets”等写作上下文
- 每章最终的 `.md`：这是你最该优先看的正文结果
- 对应的 `*_audit.json`：如果你想知道某章为什么没写好，可以看这里
- `run_summary.json`：整次写作的结果摘要

如果你只关心结果，优先看：

- 每章最终的 `.md`
- `alpha write --summary --ticker AAPL` 的摘要输出
- 需要排查问题时，再看对应的 `*_audit.json`

## 5. tool trace 分析

如果你在 `prompt` / `interactive` / `write` 时开启了 trace：

```bash
alpha prompt \
  "总结最新财报风险" \
  --ticker AAPL \
  --enable-tool-trace
```

trace 默认写入 `workspace/output/tool_call_traces`。分析命令：

```bash
python -m utils.analyze_tool_trace \
  --input ./workspace/output/tool_call_traces \
  --ticker AAPL \
  --output ./workspace/trace_analysis_AAPL.md
```

这个脚本会输出：
- 工具级诊断总表（成功率、截断率、载荷大小、错误分布）
- 详细失败签名（例如 URL 拦截、HTTP 状态、超时等），而不只停留在粗粒度 `error_code`
- 单独汇总 `sse_protocol_error`，直接展示 `partial_tool_name`、失败时的 `arguments` 前缀以及对应 `sse_error_*.json` 冷存路径
- 围绕“降低模型认知负担”的信号分析
- 截断续读、重复调用、上下文负担、失败与降级诊断
- 各 run / turn 的工具调用链与 trace 完整性检查
- 面向工具设计的优化建议

### 5.1 网页抓取诊断

当你遇到“浏览器能打开，但 `fetch_web_page` / `requests` / Playwright 访问失败”的 URL 时，可以用下面的脚本把同源证据导出成 JSON：

```bash
python -m utils.diagnose_web_access \
  --url "https://investor.pddholdings.com/news-releases/news-release-details/pdd-holdings-announces-fourth-quarter-2025-and-fiscal-year-2025" \
  --output ./workspace/output/web_diagnostics/pdd-ir.json
```

如需用有界面 Chrome 观察实际打开过程：

```bash
python -m utils.diagnose_web_access \
  --url "https://example.com" \
  --headed \
  --channel chrome
```

如需在人工完成验证后导出可复用的浏览器状态：

```bash
python -m utils.diagnose_web_access \
  --url "https://www.reuters.com/..." \
  --headed \
  --channel chrome \
  --manual-wait-seconds 30 \
  --pause-before-snapshot \
  --storage-state-out ./workspace/output/web_diagnostics/storage_states/www.reuters.com.json
```

仓库内也提供了更省事的包装脚本：

```bash
./utils/diag_web.sh "https://www.reuters.com/..."
```

它默认会用有界面 Chrome 打开页面，并等待 30 秒供你人工操作；30 秒到达后会自动继续采样页面状态并保存诊断结果。

它也会按 host 自动读写 `workspace/output/web_diagnostics/storage_states/<host>.json`：
- 第一次运行时，若状态文件不存在，只会导出新的 state，不会报错
- 后续再运行同一 host 时，会自动把已有 state 喂回诊断脚本

脚本会导出：
- 浏览器主文档 request headers 与导航结果
- 当前仓库 `fetch_web_page` 的调用结果，以及工具层 `extra.internal_diagnostics`
- `requests` 将发送的 headers 与实际 GET 结果
- Playwright 观察到的网络请求摘要
- 浏览器页面的文本/HTML 前缀，便于判断 challenge/access gate

若某些受保护站点只能靠人工浏览器通过验证，可把导出的 state 文件放进 `run.json.web_tools_config.playwright_storage_state_dir` 指向的目录；`fetch_web_page` 会按 host 自动复用对应的 `<host>.json`。

### 5.2 批量诊断与 CI

如果你的目标不是“修一个站点”，而是让 CI 持续产出一批可分析的 `web_diagnostics` 原始证据，再由后续分析去定位 `fetch_web_page` 的 root cause，推荐直接使用 `diagnose_web_access` 的批量模式：

```bash
python -m utils.diagnose_web_access \
  --url-file ./utils/web_ci_urls.jsonl \
  --run-label 20260406-sample \
  --storage-state-dir ./workspace/output/web_diagnostics/storage_states
```

仓库里已经附带了一份 sample corpus：`./utils/web_ci_urls.jsonl`。它覆盖常见新闻网站、财经网站和政府/监管组织，并包含中国与海外站点，可直接作为第一轮诊断样本。

如果你直接使用仓库内的包装脚本：

```bash
./utils/diag_web_batch.sh ./utils/web_ci_urls.jsonl
```

它默认也会开启有界面 Chrome，并为每条 URL 等待 30 秒供你人工操作；30 秒到达后会自动继续采样并保存诊断结果。

它会对每个 URL 逐条导出同源诊断 JSON，单条诊断里默认包含三条访问路径：
- 人工/自动浏览器侧的 Playwright 诊断
- `requests` 侧的实际请求结果
- 当前仓库 `fetch_web_page` 的调用结果

如果你需要人工浏览器先完成验证，再采样页面状态并保存可复用 cookie / local storage，可在批量模式下继续加：

```bash
python -m utils.diagnose_web_access \
  --url-file ./utils/web_ci_urls.jsonl \
  --run-label 20260406-manual \
  --headed \
  --channel chrome \
  --manual-wait-seconds 30 \
  --pause-before-snapshot \
  --storage-state-dir ./workspace/output/web_diagnostics/storage_states
```

只有显式传入 `--pause-before-snapshot` 时，脚本才会在等待结束后继续要求你按回车确认。

默认每条 URL 都会在独立子进程里执行，并在执行前删除 `workspace/.alpha/session`，避免进程内 Session、warmup host 和 Playwright 单例污染下一条 URL。这样 CI 侧只需要稳定地产出 `web_diagnostics`，后续分析和优化可以基于这些原始结果继续进行。

URL 文件支持两种格式：

1. JSONL：适合带元数据的长期基准集

```json
{"url":"https://finance.yahoo.com/quote/AAPL/","label":"Yahoo Finance AAPL","region":"foreign","category":"quote"}
{"url":"https://www.reuters.com/markets/companies/AAPL.OQ/","label":"Reuters AAPL","region":"foreign","category":"company-page"}
{"url":"https://www.stcn.com/article/detail/1568835.html","label":"证券时报示例","region":"china","category":"news"}
```

2. TXT：每行一个 URL，适合快速试跑

```text
https://finance.yahoo.com/quote/AAPL/
https://www.reuters.com/markets/companies/AAPL.OQ/
```

常用参数：
- `--storage-state-dir`：按 host 自动读写 storage state 目录
- `--headed`：启用有界面浏览器，便于人工观察和手工通过验证
- `--manual-wait-seconds`：导航后先额外等待多少秒
- `--pause-before-snapshot`：人工确认完成后，再按回车继续采样和保存 state
- `--skip-playwright`：只跑 `requests` 与 `fetch_web_page`
- `--skip-tool-fetch`：只收集浏览器与 `requests` 诊断，不调用 `fetch_web_page`

输出目录默认写到 `workspace/output/web_diagnostics/<run_label>/`，其中包括：
- `corpus.normalized.jsonl`：本轮归一化后的样本集
- `diagnostics/`：每条 URL 的完整诊断 JSON
- `results.jsonl`：从完整诊断提炼出的批量索引，便于后续程序分析
- `summary.json` / `summary.md`：本轮批量诊断汇总

如果你希望我直接参与 CI 优化流程，那么 CI 侧只需要跑完这一步并保留 `workspace/output/web_diagnostics/<run_label>/`，后续我就可以基于这批 `web_diagnostics` 结果做差异分析、找 root cause，并继续优化 `fetch_web_page`。

## 6. 渲染输出

Markdown 报告渲染入口：

```bash
alpha-render <输入文件.md> [输出文件]
```

常见示例：

```bash
alpha-render workspace/draft/AAPL/AAPL_qual_report.md
alpha-render workspace/draft/AAPL/AAPL_qual_report.md report.pdf
alpha-render workspace/draft/AAPL/AAPL_qual_report.md report.html
```

支持格式：
- `.docx`（默认）
- `.html`
- `.pdf`

说明：
- 生成 **HTML**、**Word（.docx）** 需要 `pandoc`；生成 **PDF** 需要 `pandoc`（先由 Pandoc 生成 HTML）以及 Chrome（Headless 打印为 PDF）
- 若 Chrome 不在标准位置，可设置 `PUPPETEER_EXECUTABLE_PATH`
- 渲染器会保留 Markdown 里的普通换行；例如列表项里单独一行的“标签”与下一行正文，在 `.docx` 中会继续换行显示

## 7. 配置文件从哪里改

大多数用户只需要关注这三个位置：

| 文件/目录 | 用途 |
|-----------|------|
| `workspace/config/llm_models.json` | 模型配置、API Key 占位符 |
| `workspace/config/run.json` | Agent 行为、Host 配置、工具超时、trace、budget、limits；CLI / WeChat 的 chat 与 prompt 默认执行参数也在运行时由 Host 基于这里继续收敛 |
| `workspace/config/prompts/` | prompt 资产 |

建议修改方式：
- 想换模型：改 `llm_models.json`
- 想新增自定义模型：先在 `workspace/config/llm_models.json` 里添加模型配置；再把该模型加入对应 scene manifest 的 `workspace/config/prompts/manifests/*.json -> model.allowed_names`，必要时改 `model.default_name`；如果该模型要长期参与 `interactive` 多轮会话，建议同时给该模型补 `runtime_hints.conversation_memory`
- 想调 Agent 行为：改 `run.json`；其中 `conversation_memory` 控制 `interactive` 多轮会话的历史预算与压缩策略
- 想改系统提示词和任务提示词：改 `prompts/`

配置说明请看：
- [alpha/config/README.md](alpha/config/README.md)

<a id="model-config"></a>

## 8. 模型配置

如果你只是临时切换模型，最简单的办法是在命令里直接传 `--model-name`。  
如果你想长期修改默认模型，或者接入一个新的模型，再改配置文件。

最常用的两个位置是：

- `workspace/config/llm_models.json`：定义“有哪些模型可以用”
- `workspace/config/prompts/manifests/*.json`：定义“每个场景默认用哪个模型”

### 8.1 怎么修改默认模型

每个场景都有自己的默认模型，配置在对应 scene manifest 里。

最常改的几个文件：

- `workspace/config/prompts/manifests/prompt.json`
- `workspace/config/prompts/manifests/interactive.json`
- `workspace/config/prompts/manifests/prompt_mt.json`
- `workspace/config/prompts/manifests/write.json`
- `workspace/config/prompts/manifests/audit.json`
- `workspace/config/prompts/manifests/confirm.json`

你主要看这一段：

```json
"model": {
  "default_name": "mimo-v2.5-pro",
  "allowed_names": [
    "mimo-v2.5-pro",
    "mimo-v2.5-pro",
    "deepseek-v4-flash"
  ],
  "temperature_profile": "write"
}
```

改默认模型时，通常只需要两步：

1. 把 `default_name` 改成你想用的模型名
2. 确认这个模型名已经出现在 `allowed_names` 里

例如：

- 想把 `write` 默认模型从 `mimo-v2.5-pro` 改成 `gpt-5.4`，就改 `workspace/config/prompts/manifests/write.json`
- 想把 `interactive` 默认模型改成 `qwen-plus-thinking`，就改 `workspace/config/prompts/manifests/interactive.json`
- 想把 `audit` / `confirm` 默认模型换掉，就分别改 `audit.json` 和 `confirm.json`

一个简单理解：

- `default_name`：这个场景默认会用谁
- `allowed_names`：这个场景允许切换到哪些模型
- `temperature_profile`：这个场景默认使用哪组温度参数，一般不用改

### 8.2 怎么添加新模型

如果现有模型不够用，你可以自己往 `workspace/config/llm_models.json` 里加一个新条目。

最简单的做法是：

1. 先复制一个最接近的现有模型配置
2. 改模型名、接口地址、鉴权头和能力参数
3. 再把这个模型名加入对应 scene manifest 的 `allowed_names`
4. 如果希望它成为默认模型，再修改 `default_name`

例如，你可以复制一段现有配置，改成这样：

```json
"my-model": {
  "runner_type": "openai_compatible",
  "name": "my-model",
  "endpoint_url": "https://api.example.com/v1/chat/completions",
  "model": "my-model",
  "headers": {
    "Authorization": "Bearer {{MY_API_KEY}}",
    "Content-Type": "application/json"
  },
  "timeout": 3600,
  "supports_stream": true,
  "supports_tool_calling": true,
  "max_context_tokens": 128000,
  "runtime_hints": {
    "temperature_profiles": {
      "write": {
        "temperature": 0.8
      },
      "audit": {
        "temperature": 0.2
      }
    }
  }
}
```

加完之后，再去对应 scene manifest，例如 `workspace/config/prompts/manifests/write.json`，把 `"my-model"` 加进 `allowed_names`。如果你想让它直接成为默认模型，再把 `default_name` 改成 `"my-model"`。

### 8.3 模型参数怎么理解

对最终用户来说，下面这些参数最重要：

- `name`：配置名。你在 `--model-name`、`default_name`、`allowed_names` 里写的就是它。
- `endpoint_url`：模型服务地址。
- `model`：真正发给服务商的模型标识。
- `headers`：鉴权和请求头，通常在这里放 API Key 占位符。
- `timeout`：单次请求超时时间，单位秒。
- `supports_stream`：是否支持流式输出。
- `supports_tool_calling`：是否支持工具调用。用于 `prompt`、`interactive`、`write` 的模型通常需要支持。
- `max_context_tokens`：模型可用上下文上限。

`runtime_hints.temperature_profiles` 里最常看到的是 `temperature`：

- `temperature` 越低，输出通常越稳、更保守
- `temperature` 越高，输出通常越发散、更有变化

通常可以这样理解：

- `write`：正文写作时的参数
- `overview`：第 0 章概览时的参数
- `audit`：审计场景的参数
- `decision`：第 10 章研究决策场景的参数
- `prompt`：单轮问答场景的参数
- `interactive`：交互对话场景的参数
- `infer`：公司类型与关键约束判断场景的参数

如果你只是新增一个模型，最稳的办法不是从零设计全部参数，而是复制一个相近模型，再按你的服务商要求做最小改动。

### 8.4 一个推荐顺序

如果你准备调整模型配置，建议按这个顺序来：

1. 先临时用 `--model-name` 试跑
2. 满意后再改 scene manifest 的 `default_name`
3. 如果现有模型都不合适，再去 `llm_models.json` 新增模型

这样做的好处是：

- 先验证效果，再改默认配置
- 不容易一上来改太多，最后不知道是哪一步导致结果变化

## 9. 文档导航

- 用户手册（当前文档）：[README.md](README.md)
- 开发手册总览：[alpha/README.md](alpha/README.md)
- Engine 包开发手册：[alpha/engine/README.md](alpha/engine/README.md)
- Fins 包开发手册：[alpha/fins/README.md](alpha/fins/README.md)
- 配置说明手册：[alpha/config/README.md](alpha/config/README.md)
- 贡献指南：[CONTRIBUTING.md](CONTRIBUTING.md)

## 10. 开源与许可证

本仓库采用 `Apache License 2.0` 开源协议发布。

你在分发或修改本项目时，至少需要注意三件事：

- 保留仓库中的 [LICENSE](LICENSE) 和 [NOTICE](NOTICE)
- 对你修改过的文件添加明确变更说明
- 不要把仓库名称、作者名称或项目商标暗示成对你分发版本的背书

如果你准备贡献代码、文档或测试，请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

### 问题驱动研究

同一公司可以建立多项独立研究；每项研究复用自己的会话，报告按版本保留。本地 Codex 已登录时，先运行 `alpha init --base ./workspace --codex`，直接复用 Codex 的模型与推理配置，无需模型 API Key；然后执行：

```bash
alpha research --owner local new "苹果的现金流质量是否改善？" --subjects AAPL --key apple-cashflow
alpha research --owner local list
alpha research --owner local ask <research_id> "开始研究，说明证据和缺口" --key first-input --run
alpha research --owner local status <research_id>
alpha research --owner local report <revision_id>
alpha research --owner local stop <research_id> --key stop-1
alpha research --owner local resume <turn_id> --key resume-1 --run
alpha research --owner local archive <research_id>
alpha research --owner local open <research_id>
```

`--base`、`--owner`、`--model-name` 放在 `research` 后、操作名前。`ask` 不加 `--run` 只持久接受输入；之后用 `run <research_id>` 执行。创建、输入、停止和恢复的 `--key` 是各自稳定请求键，相同键重试不会重复受理。历史研究可在 `new` 时传含时区的 `--as-of`；每轮固定方法与执行规格。恢复适用于失败、孤立或超时输入，主动停止不会自动恢复。正式版本需模型提交报告工具且 Host 成功；纯文本回答不会冒充报告。

`--subjects` 表示证券代码：证券研究默认要求实际读取利润表、资产负债表和现金流表，纯 PDF 文本阅读不满足覆盖。需要指定文档或跨期范围时，将要求保存为 JSON 文件并传给 `ask --financial-requirements ./requirements.json`，例如：

```json
[{"ticker":"BABA","document_ids":["fil_0001193125-26-231755"],"minimum_periods":2}]
```

省略 `statement_types` 时使用三张核心报表。研究会保存实际读取结果及原件、解析产物哈希；缺少必需数据、币种或单位时不能完成报告。先保存候选稿，再查看字段错误、局部修订并按候选 ID/hash 提交，正式版本保留原稿与校验证据。

### 用当前 coding agent 直接研究

这是推荐的日常研究入口；完整操作与可复制提问示例见 [coding agent 与 Notion 使用指南](docs/alpha/coding-agent-guide.md)。

安装后可运行 `alpha-mcp --base /绝对路径/workspace --owner local`。它使用官方 MCP Python SDK 的 stdio 传输，将工具执行交给同一个 Host；分析使用当前 coding agent，无需再次调用本地 Codex 模型。按 [Codex MCP 配置说明](https://learn.chatgpt.com/docs/extend/mcp?surface=cli) 接入，例如：

```bash
codex mcp add alpha -- /绝对路径/.venv/bin/alpha-mcp --base /绝对路径/workspace --owner local
```

财报解析可能超过客户端默认工具时限，可在 Codex 的 `[mcp_servers.alpha]` 中设置 `tool_timeout_sec = 600`，并限定下载日期和报告类型；该时限不保证所有文档都能处理完成。本仓库提供 `$alpha-research` skill；也可直接按以下工具工作：

| 工具 | 用途 |
|---|---|
| `alpha_sessions` | 分页查看多个主题、执行状态、输入 ID 和最近版本 |
| `alpha_create` / `alpha_begin` | 创建主题并开始本轮；返回执行句柄及业务工具目录 |
| `alpha_call` | 调用财报读取、方法、计算、笔记、检查点和候选稿工具 |
| `alpha_finish` | 按候选 ID/hash 原子提交并结束本轮 |
| `alpha_abort` / `alpha_resume` | 停止或显式恢复失败、孤立、超时输入 |
| `alpha_publish` / `alpha_publications` | 发布固定版本，查看状态与链接 |
| `alpha_delivery` | 读取正式正文绑定的聊天摘要、真实版本及 Notion 交付状态 |

财报工具按 `research_download_filings → research_prepare_source → research_read_financial` 使用；已下载的源文档可直接准备。用 `research_checkpoints` 查看原笔记、计算和候选稿索引，再用 `research_read_checkpoint` 读取完整内容。跨研究隔离；同一 session 同时只允许一个写执行。断开连接会请求 Host 取消本连接的未完成执行并保留检查点；外部 IDE 的思考过程仍由 IDE 管理。

### Telegram 多研究入口

研究工具支持保存收益约定、核心判断及证据链，按需查看到期判断并追加经营复盘。完整单公司/比较报告由 `research_compose_report` 组装，聊天通过 `alpha_delivery` 查看主要结论、变化和已确认的 Notion 链接。旧预测和原约定不会因后续修改而覆盖；比较允许并列，并列明改变顺序的条件。具体用法见 [使用指南](docs/alpha/coding-agent-guide.md)。

Telegram 是可选渠道，不是 coding agent 研究或 Notion 报告归档的前置条件。

先在 BotFather 启用 Bot 私聊话题模式。默认复用 `$CODEX_HOME/config.toml`（未设置时为 `~/.codex/config.toml`）中 `mcp_servers.telegram.env.TELEGRAM_BOT_TOKEN`，支持已有 `BOT_TOKEN`/`TELEGRAM_TOKEN`；`ALPHA_TELEGRAM_BOT_TOKEN` 可显式覆盖。没有 Telegram MCP 连接时，可在 Codex 用户目录下的 `alpha/credentials.toml` 配置 `[telegram]` 表的 `bot_token` 字符串，文件权限设为 `0600`；这是 alpha 专用本地凭据，不需注册 MCP 服务。在 `workspace/config/telegram.json` 的 `allowed_user_ids` 数组中填写允许的 Telegram user ID，也可用 `--user` 显式覆盖。

```bash
alpha-telegram --base ./workspace --check --user 123456789
alpha-telegram --base ./workspace --user 123456789
```

`--check` 只预检 Bot 和长轮询条件，不创建研究。正式启动后，在私聊中发送 `/new 研究问题` 新建原生话题，发送 `/researches` 查看分页研究列表；在话题内直接输入可续研究。`/status` 查看进度，`/stop` 请求协作停止。报告卡提供摘要和 Markdown 文件；归档/重新打开保留原研究和会话。

话题创建结果未知时，在已经创建的话题内用 `/bind <research_id>` 明确绑定。失败或中断输入可用 `/resume <turn_id>` 显式恢复。未知发送结果不会自动重复发送；请先核对 Telegram 中的实际消息。在研究话题内可发送 PDF、TXT、Markdown 或 HTML（20 MiB 上限，文本须 UTF-8）。财报附件说明用 `/filing AAPL 10-K 核对收入`，由 Fins 仓储保存；普通附件进入当前研究材料库。接收只表示原件保存，后续模型用材料工具逐页提取和核验。PDF 文本读取需系统安装 Poppler `pdftotext`，扫描件需另外 OCR；本轮截止后导入的材料只进入后续研究，旧报告不回填。

### 将指定报告版本推送到 Notion Invest

默认复用 Codex 配置中 `mcp_servers.notion.env.NOTION_TOKEN`（也支持 `NOTION_API_KEY`），无需再填一份 token；`ALPHA_NOTION_TOKEN` 可显式覆盖。该 connection 需有 Invest 页面读取、插入及必要更新权限。`workspace/config/notion.json` 的 `parent_page_id` 默认指向已确认的 [🌾 Invest](https://www.notion.so/8b6f0c8fc1264555b531281fbb0b96bc)。目标使用固定 ID，不按页面同名搜索。

```bash
alpha research --owner local publish <revision_id> --key publish-1 --run
alpha research --owner local publication <publication_id>
```

`publish` 返回前保存明确授权的版本和正文；`--run` 处理队列中最早的一项已授权发布。MCP 常驻连接配置 token 后会独立消费发布队列，通过 `alpha_publications` 查询状态和链接，无需 Telegram。使用可选 Telegram 入口时，报告卡的“推送到 Invest”绑定原版本；后续研究生成 v2 不会改变旧 v1 按钮的目标，`/publication <publication_id>` 可查询状态并把链接发回原话题。

目录结构为 `Invest → 研究主题页 → 不可变版本页`。主题按稳定 `research_id` 绑定，显示标题变化不会另建主题。异步任务必须完成且回读通过，才显示已推送。重复已完成请求返回原页面，后台不覆盖人工编辑后的已发布页。主题或版本创建结果未知时先核对原标记，未找到也不会自动重建。权限失败修复后可点“重试推送”，或使用新的 `--key` 明确重试；重放旧失败键只返回原状态。

默认手动发布。用户明确要求本轮完成后归档时，可使用 `ask --publish-on-complete --run`，或在 `alpha_begin` 中设置 `publish_on_complete=true`。策略和目标在本轮接受时固定，只有正式版本才进入发布队列；报告正文不能授权发布。MCP/Telegram 常驻入口会独立消费队列；CLI 也会在执行完成后处理到期意图。归档失败可单独重试，不重新跑研究。

已有工作区先执行 `alpha init --codex`，它会补齐新配置并按明确选择将各 scene 切到本地 Codex；不带该选项的迁移仅补齐缺失定义，保留已有默认选择。研究停止与独立发布是不同操作；应用退出时会请求 Host 取消当前发布尝试并等待 HTTP 线程收尾。

本地材料可用 `alpha research --owner local material <research_id> ./note.pdf --key material-1 --caption "核对原文" --run` 导入；财报将 caption 换成 `/filing AAPL 10-K 核对收入`。PDF 单次读取连续 1–5 页，正文保留原页码，原件 hash 与来源引用可追溯。结构化财报先用 `research_prepare_filing` 按需生成 Docling 结构，再用已有 Fins 工具读取；转换期间协作取消会等待当前转换收尾。

Notion 大报告按固定正文预先分段，代码块和表格保持完整；单段超过 128 KiB 会明确拒绝。续写使用一次性分段标记替换，回读通过后记录进度；未知追加先回读，不重复追加。人工改动、截断和标记冲突保留待核对，已发布页不覆盖写。

本次实现范围、离线验证和部署后的真实账号烟测清单见 [alpha 验收记录](docs/alpha/acceptance.md)。

本地 Codex 使用官方 app-server 动态工具协议（当前验证版本 0.162.1）；研究只暴露 alpha 已接受的工具，每批执行后回到 Host 的迭代、停止和重复调用治理。Codex 登录文件和密钥不复制到工作区，Notion/Telegram 已保存 token 仅在相应入口装配时读取。仅有 Codex 的 ChatGPT 登录并不等于保存了 Telegram Bot token；未找到渠道凭据时会明确报错。
