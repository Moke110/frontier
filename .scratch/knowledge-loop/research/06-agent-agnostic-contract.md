# 06 · Agent-agnostic 数据契约与数据布局

Type: research ｜ 对应票：`.scratch/knowledge-loop/issues/06-agent-agnostic-contract.md` ｜ 日期：2026-10-16

> 目标：把「个人知识循环」的**确定性脚本 / agent 提示 / 数据 schema** 三分边界划清，并给出数据布局候选，使系统换 Claude Code / Codex / opencode 也能驱动。
>
> 全部结论均有出处（本地文件路径或 URL），见文末「出处」。

---

## 摘要（先看这三条）

1. **真正 Hermes 专有的只有一层薄薄的「调度胶水」**（script 必须放 `~/.hermes/scripts/`、runpy 真 wrapper、`attach_to_session`、`workdir`/`enabled_toolsets`、`hermes cron` 子命令）。这层之外——纯 stdlib 取数脚本、文件即接口、stdout 传句柄、稳定 ID 去重、状态文件轮换——**全是可移植契约**。换 agent 的成本 = 重写触发层 + 把 prompt 搬进 `AGENTS.md`。
2. **契约要「文件化 + 标准文件化」**：脚本层用 **CLI 契约**（子命令 / `--help` / 退出码 / stdout 句柄行），提示层用 **`AGENTS.md`**（Linux Foundation 托管的开放标准，Claude Code / Codex / opencode / Cursor 均读），数据层用 **JSON Schema**。三层里只有提示层的「触发方式」随 agent 变，脚本层与数据层零改动。
3. **数据布局推荐「混合（候选 C）」并强制异地备份**：契约/代码/文档/schema 在 repo（随 git、可交接），大体积数据（PDF、`archive/*.jsonl`、`digests/`）在独立目录，路径由**单一配置入口**声明（杜绝硬编码 agent 私有路径）；`rotation.json` 等小状态可双落地。旧系统「无备份静默丢失 15 天」是必须显式解决的教训。

---

## ① 旧架构的「通用契约 vs Hermes 专有」逐条分层判定

判定分三档：**通用契约**（换 agent 不改）、**半通用**（思路通用、传输方式随 agent 变）、**Hermes 专有**（换 agent 必须重写）。

| # | 机制 | 判定 | 换 agent 时的影响 | 出处 |
|---|------|------|------------------|------|
| 1 | `fetch_daily.py` 纯 stdlib 取数（读词库→轮换→检索→去重→下载 PDF），无第三方依赖 | **通用契约** | 零改动；任何 agent 只要能跑 shell 即可驱动 | SKILL.md L12/L18-22；instance L20 |
| 2 | **stdout 是注入通道**：脚本把 `CANDIDATES_FILE: <path>` 打进 stdout，日志走 stderr | **半通用** | 「用 stdout 传数据句柄」是通用设计；但「stdout 被自动注入 prompt」是 Hermes cron 的行为，其他 agent 要靠提示里显式 `Bash` 运行再 `Read` | SKILL.md L19/L40 |
| 3 | 数据落盘 JSON：`digests/<date>_<field>_candidates.json`（候选全量记录） | **通用契约** | 零改动；schema 稳定即可 | SKILL.md L20；instance L19 |
| 4 | 去重存档 `archive/papers.jsonl`（append，记录 `source:id`） | **通用契约** | 零改动；**前提是稳定 ID 方案**（`arxiv:xxxx` / `pubmed:PMID`） | SKILL.md L27 |
| 5 | 轮换状态 `rotation.json`（`{"last_index": n}`，`(last+1)%n`） | **通用契约** | 零改动；状态文件是「单一事实源」，多 agent 接力/补跑都安全 | SKILL.md L26 |
| 6 | 词库 `fields.tsv`（`field_id<TAB>显示名<TAB>PubMed查询<TAB>arXiv查询`，`#` 注释） | **通用契约**（自定义格式） | 零改动；建议补一份格式说明/schema，降低重实现风险 | instance L14、L39-42 |
| 7 | 读者模型知识库 `knowledge/<field>.md`（认知摘要/术语表/跟进脉络/盲区） | **通用契约** | 零改动；它是「系统记忆」，与 agent 无关 | SKILL.md L28 |
| 8 | 分层原则：**确定性工作交给脚本，LLM 只做判断与写作** | **通用契约**（架构原则） | 这是整个可移植性的根；换 agent 后原则不变 | SKILL.md L12 |
| 9 | 产出形状：中文日报（`做了什么/发现/为什么重要`）+ 术语表 + 跟进脉络 + 盲区回填 + 归档核对段 | **通用契约** | 零改动；是「写作模板」，可写成 agent 提示里的 checklist | output/20261009 L17-60；output/20260929 L13-49 |
| 10 | 「失败路径」写入 prompt：取数失败/无候选时直接回复原因，**绝不编造论文** | **通用契约** | 零改动；是提示层硬约束 | SKILL.md L42 |
| 11 | cron script 必须放 `~/.hermes/scripts/`，参数**只给文件名**（绝对路径报错） | **Hermes 专有** | 换 agent 需重做触发方式（如 Claude Code 直接在提示里 Bash 绝对路径） | SKILL.md L33 |
| 12 | symlink 被拒（realpath 越界检查），需**真 wrapper 文件 + `runpy`** 指向 canonical 脚本 | **Hermes 专有** | 纯 Hermes 沙箱特性；其他 agent 无此约束 | SKILL.md L33-39 |
| 13 | `attach_to_session=true`（用户可回复追问，DM brief 镜像到 origin 会话） | **Hermes 专有** | 换 agent 需用该 agent 的会话/追问机制替代 | SKILL.md L41；instance L7 |
| 14 | `workdir` 设数据目录、`enabled_toolsets` 只给 file+terminal、限候选数/步骤、3 分钟硬中断 | **Hermes 专有** | 是 Hermes 的资源/超时约束；换 agent 转成该 agent 的等价配置 | SKILL.md L41-42 |
| 15 | `skills=[biomni]` 挂到 job，给总结 agent 领域上下文 | **Hermes 专有** | 换 agent 需把领域上下文并进 `AGENTS.md` / 项目 skill | SKILL.md L43 |
| 16 | 调度与运维：`hermes cron list|run|edit|pause|resume|remove` | **Hermes 专有** | 换 agent 需换成该 agent 的调度（如 systemd timer / GitHub Actions / 手动） | instance L26-29 |

**分层结论**：这 16 条天然分三层——

```
[调度/触发层]   #11-16  ← Hermes 专有（薄胶水）
[契约层]        #2,6,8,10,#7  ← 半通用 + 通用（接口与提示原则）
[数据/状态层]   #1,3,4,5,#9   ← 通用契约（文件即接口，agent 无关）
```

**关键观察**：Hermes 专有的部分几乎全是「怎么启动 / 怎么把结果递进 LLM / 怎么限流」；一旦把「启动」抽象成「跑一个 CLI」、把「递结果」抽象成「读一个文件」，那层胶水就只剩几十行适配代码。

---

## ② 三层契约草案

三层各自是一个**文件化契约**，互不依赖具体 agent。下面每层写清「契约是什么」与「换 agent 时要改什么」。

### 第 1 层：确定性脚本层 —— 契约 = CLI + 流 + 退出码

**契约内容**
- 每个能力是一个**可直接执行的命令**（stdlib / 任意语言），不走 agent 私有 API。
- 统一 CLI：子命令 + 显式参数，例如
  `fetch --field <id> --since <YYYY-MM-DD> --out <path>`、`archive --candidates <path>`、`rotate --state <path>`。
- **`--help` 自描述**：参数、默认值、副作用都写在 help 里（agent 可自助发现，无需读源码）。
- **stdout = 机器可读的句柄行**（如 `CANDIDATES_FILE: /abs/path`），**stderr = 人类日志**。
- **退出码分级**（0 成功 / 2 无候选 / 3 取数失败 / 4 下载失败…），失败信息进 stderr。
- 产物路径**回显到 stdout**，供上层 read_file。

**换 agent 要改什么**：**几乎不用改**。任何 agent「能跑 shell + 能读文件」即可驱动。唯一胶水是「怎么把 stdout 交给 LLM」——各 agent 不同，但都归到第 2 层。

### 第 2 层：agent 提示层 —— 契约 = `AGENTS.md`（开放标准）+ 一个运行手册

**契约内容**
- 把「读候选 JSON → 读知识库 → 选 ≤N 篇 → 写中文日报 → 归档 `papers.jsonl` → 备份 md → 更新知识库 → 最终回复=推送正文」写成一份 **`AGENTS.md`**（进度清单式 procedure）。
- **`AGENTS.md` 是 agent-neutral 的**：`agents.md` 由 Linux Foundation 下的 Agentic AI Foundation 托管，OpenAI Codex、Amp、Jules、Cursor、Factory 等采用；Claude Code 在「无 `CLAUDE.md`」时默认读它（也可用 `/config` 的 `instructionFiles` 设成同时读）；opencode 直接以 `AGENTS.md` 为主、并回退读 `CLAUDE.md`。
- 领域上下文（原 `skills=[biomni]`）也并进这里或引用的子文档。
- 失败路径硬约束（无候选→直说、绝不编造）写死在手册里。

**换 agent 要改什么**：**只改这一层，且只改「触发方式」**。提示文本（procedure）通用；变的是「怎么把它投喂给 agent」：

| Agent | 读指令的方式 | 触发方式 |
|-------|------------|---------|
| Hermes | cron job 的 prompt（脚本 stdout 注入） | `hermes cron` + `attach_to_session` |
| Claude Code | `CLAUDE.md` 或直接 `AGENTS.md`（无 CLAUDE.md 时） | 手动 `/…`、skill、或 hooks |
| Codex | `AGENTS.md` | 手动 / CI |
| opencode | `AGENTS.md`（全局 `~/.config/opencode/AGENTS.md`，回退 `CLAUDE.md`） | 手动 / `/init` |

> **落地建议**：把「任务提示」与「调度触发」**物理分离**——procedure 放 repo 的 `AGENTS.md`（随 git、可交接）；触发（cron / timer / CI / 手动）是各 agent 的薄适配脚本，不进契约。

### 第 3 层：数据 schema 层 —— 契约 = JSON/JSONL + JSON Schema 文件

**契约内容**
- `candidates` JSON：`{schema_version, field_id, run_date, window, items:[{source, source_id, title, authors, abstract, url, pdf_url, pdf_local}]}`
- `archive/papers.jsonl` 每行：`{source, source_id, field_id, pushed_date, title, url}`（**去重键 = `source:source_id`**）
- `rotation.json`：`{schema_version, last_index}`
- `fields.tsv`：定义 + 格式说明（列含义、`{{since}}` 占位、日期规则）
- 一份写入 repo 的 `schema/*.json`（JSON Schema）作为**唯一权威定义**，脚本与提示都引用它。
- 全员带 `schema_version`，便于演进。

**换 agent 要改什么**：**零改动**。schema 是数据契约，与谁在驱动无关。唯一要求：字段用**稳定 ID**（`source:id`），且 JSON 用标准编码。

### 横切建议：状态机 + 状态文件（让「换手」安全）

在数据层之上放一个轻量**状态机**：`fetch → select → write → archive → update_kb → push`，每个阶段把 `Status` 写进 `runs/<date>.json`（对应 issue-tracker 的 `Status:` 行惯例）。好处：任何 agent 读同一份状态即可**幂等续跑 / 接力 / 中断恢复**，不依赖某个 agent 的会话内存。这与「文件即事实源」一致，是 agent-agnostic 的关键一环。

---

## ③ 数据布局候选（含取舍与推荐）

### 候选 A：全部放 repo 内（`frontier/.scratch/knowledge-loop/`）

- **形状**：脚本、schema、`fields.tsv`、`rotation.json`、`knowledge/`、`digests/`、`archive/papers.jsonl`、`archive/pdfs/` 全在 repo。
- **利**：随 git 走，天然版本化 + 异地备份；agent 打开 repo 即见全部；交接零额外说明。
- **弊**：**PDF 与 append 的 JSONL 迅速撑大仓库**（每次 `papers.jsonl` 尾部追加都产生 diff 噪声）；且 `.scratch/` 在本 repo 的语义是 **issue/spec 暂存区**（`docs/agents/issue-tracker.md`），承载长期数据与本意冲突，可能被清理。

### 候选 B：数据全在外（如 `~/knowledge-loop/`），repo 只放说明

- **形状**：数据根 `~/knowledge-loop/`（`fields.tsv`/`rotation.json`/`knowledge/`/`digests/`/`archive/`），repo 只留 README/spec。
- **利**：**天然 agent-agnostic**（不落在任何单一 agent 的私有目录）；数据不撑 git；PDF 可任意大；多 agent 用同一路径。
- **弊**：**不在 git → 无版本、无异地备份**（旧系统正是「无备份静默丢失 15 天」而无人知，见 output/20260925 L13/L62）；交接需额外交代路径；多机同步难。

### 候选 C（推荐）：混合 —— 契约在 repo，数据在独立目录，用单一配置入口连接

- **形状**：
  - **repo 内**（随 git）：`AGENTS.md`、`scripts/`、`schema/*.json`、`docs/`、以及**小体积高价值的状态种子**（`fields.tsv`、首次 `rotation.json`）。
  - **独立数据目录** `~/knowledge-loop/`（路径由**单一配置**声明，如环境变量 `KNOWLEDGE_LOOP_HOME` 或 `config.yaml` 一段，**禁止硬编码 agent 私有路径**）：`digests/`、`archive/papers.jsonl`、`archive/pdfs/`、`knowledge/`。
  - **轮换指针** `rotation.json` 属小状态，可留在数据目录，但建议在 repo 保留一份**冷备/初始种子**。
- **利**：契约可交接、可版本化；大文件不进 git；agent-agnostic 且路径可移植；符合本 repo「`AGENTS.md` 描述约定 + `.scratch` 存 issue」的既有风格。
- **弊**：git 只追契约不追数据 → **备份必须显式做**（加定时异地备份，写进 spec）；需一个「数据根配置」才能让脚本与提示都找到数据。

### 推荐与理由

**选候选 C**，并**把「异地定时备份」列为硬性要求**（旧系统血的教训）。C 的关键设计是**单一数据根配置**：脚本从 `KNOWLEDGE_LOOP_HOME`（或 repo 内 config）取根路径，agent 提示也只引用该变量——这样换 agent 时既不用改脚本、也不用改路径。

> 附：本报告只产出方案，未创建 `~/knowledge-loop/`、未建脚本、未动 git。是否落地由 spec 阶段决定。

---

## ④ 三条最关键结论

1. **Hermes 专有部分只有「调度胶水」一层**——`~/.hermes/scripts/` 位置约束、runpy 真 wrapper、`attach_to_session`、`workdir`/`enabled_toolsets`、`hermes cron` 命令。它上面（提示）和下面（脚本/数据）全是可移植契约。**换 agent 的成本 = 重写这一层 + 把 prompt 搬进 `AGENTS.md`**，而非重写系统。
2. **把契约「文件化 + 标准文件化」是换 agent 成本最低的路线**：脚本层用 **CLI 契约**（子命令 / `--help` / 退出码 / stdout 句柄），提示层用 **`AGENTS.md`**（Linux Foundation 开放标准，Claude Code / Codex / opencode / Cursor 均读），数据层用 **JSON Schema**。三层中**只有提示层的「触发方式」随 agent 变**；脚本层与数据层**零改动**。
3. **数据布局选混合（C），并把异地备份做成硬性要求**：契约/代码/文档/schema 在 repo（随 git、可交接），PDF / `archive/*.jsonl` / `digests/` 在独立目录且路径由**单一配置入口**声明（避免硬编码 agent 私有目录）。「无备份静默丢失 15 天」的旧系统事故必须在 spec 层面被显式解决。

---

## 出处

**本地材料**
- `/home/chang/.hermes/skills/software-development/cron-digest-pipelines/SKILL.md`（旧系统架构与 Hermes cron 部署规则/坑）
- `/home/chang/.hermes/skills/software-development/cron-digest-pipelines/references/paper-digest-instance.md`（`~/paper_digest` 目录布局与维护命令）
- `/home/chang/.hermes/cron/output/5765d8701ebd_20261009_083442.txt`、`..._20260929_083246.txt`、`..._20260925_083559.txt` 等 8 份旧日报（产出形状：中文日报 / 术语表 / 跟进脉络 / 盲区回填 / 归档核对）
- `/home/chang/.hermes/config.yaml`（`mcp_servers`、`terminal`、`platform_toolsets` 段）
- `/home/chang/frontier/AGENTS.md`、`/home/chang/frontier/docs/agents/issue-tracker.md`、`/home/chang/frontier/docs/agents/domain.md`（本 repo 约定：issues/spec 走 `.scratch/`；domain doc 消费规则）

**外部来源（2026-10-16 抓取）**
- `AGENTS.md` 标准：https://agents.md/ —— 「One AGENTS.md works across many agents」；由 Agentic AI Foundation（Linux Foundation）托管；采用者含 OpenAI Codex、Amp、Jules、Cursor、Factory。
- Claude Code 记忆/指令文档：https://docs.claude.com/en/docs/claude-code/memory.md —— 默认在「无 `CLAUDE.md`」时读 `AGENTS.md`；`/config` 的 `instructionFiles`（`claude-md-or-agents-md` 默认 / `claude-md-and-agents-md` / `claude-md` / `managed-only`）；可用 `@path` import 共享一份文件。
- Model Context Protocol：https://modelcontextprotocol.io/docs/getting-started/intro.md —— 开放标准，「AI 应用的 USB-C」，广生态支持（Claude / ChatGPT / VS Code / Cursor 等）。
- opencode 规则文档：https://opencode.ai/docs/rules.md —— 以 `AGENTS.md` 为主；全局 `~/.config/opencode/AGENTS.md`；回退读 `CLAUDE.md`/`~/.claude/CLAUDE.md` 与 Claude Code skills 约定。

> 备注：`web_search`/`web_extract` 在本机未配置（Firecrawl 未设密钥）；以上外部来源经 `curl` 与 biomni MCP 取回原文/`.md` 变体确认。
