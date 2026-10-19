# 06 agent-agnostic 数据契约与数据布局

Type: research ｜ Status: resolved ｜ Blocked by: —
Claimed by: Hermes (session 2026-10-16)

## Question

系统要能被**任意 agent 驱动**（本次 Hermes，未来 Claude Code / Codex / opencode）。那么「确定性脚本 / agent 提示 / 数据 schema」的三分边界怎么划，数据放哪？

需要查清 + 提出候选方案：

**① 旧 paper_digest 的分层逐条判定**（读 `cron-digest-pipelines` skill 与其 `references/paper-digest-instance.md`，以及 `~/.hermes/cron/output/` 的 8 份日报正文看产出形状）
- 通用契约：`fetch_daily.py` 纯 stdlib 取数、stdout 注入 `CANDIDATES_FILE:` 路径、LLM 侧只做判断与写作、`archive/papers.jsonl` 去重、`rotation.json` 状态
- Hermes 特有（换 agent 就要改）：cron script 必须放 `~/.hermes/scripts/`、runpy wrapper、`attach_to_session`

**② 同类「agent 可驱动数据管线」的通行做法**
- `AGENTS.md` / `CLAUDE.md` 约定、JSON schema 描述、CLI 契约、MCP —— 哪种让**换 agent 的成本最低**

**③ 数据布局**
- 放 repo 内（`frontier/.scratch/knowledge-loop/`，随 git 走，但 PDF/JSONL 会撑大仓库）vs 独立数据目录（`~/knowledge-loop/`，agent-agnostic 但不在 git 里）vs **混合**（代码与契约在 repo，数据在外）

**产出**：`.scratch/knowledge-loop/research/06-agent-agnostic-contract.md`，含**三层契约草案** + **数据布局的 2–3 个候选（附取舍）**。

## Answer

**结论一：真正 Hermes 专有的只有一层薄薄的「调度胶水」。** 16 条旧机制逐条判定后，只有 5–6 条必须重写（cron script 必须放 `~/.hermes/scripts/`、symlink 被拒需 runpy 真 wrapper、`attach_to_session`、`workdir`/`enabled_toolsets`、`hermes cron` 命令）；其余（纯 stdlib 取数、文件即接口、`CANDIDATES_FILE:` stdout 句柄、`papers.jsonl` 稳定 ID 去重、`rotation.json` 轮换、知识库、日报模板、失败路径约束）**全是可移植契约**。→ **换 agent 的成本 = 重写触发层 + 把 prompt 搬进 `AGENTS.md`，而不是重写系统。**

**结论二：三层契约（文件化 + 标准文件化）**

| 层 | 契约 | 换 agent 要改什么 |
|---|---|---|
| ① 确定性脚本 | **CLI 契约**：子命令 / `--help` 自描述 / stdout = 机器句柄行（`CANDIDATES_FILE: /abs/path`）/ stderr = 人类日志 / **退出码分级**（0 成功、2 无候选、3 取数失败…） | **几乎不用改** —— 任何「能跑 shell + 能读文件」的 agent 即可驱动 |
| ② agent 提示 | **`AGENTS.md`**（Linux Foundation 托管的开放标准；Claude Code 无 `CLAUDE.md` 时默认读它、Codex/opencode 直接读） | **只改这一层，且只改「触发方式」**（Hermes = cron + 脚本 stdout 注入；Claude Code = skill/hooks；Codex/opencode = 手动/CI） |
| ③ 数据 schema | **JSON Schema 文件**（`schema/*.json`）+ 全员带 `schema_version`；去重键 = `source:source_id` | **零改动** |

落地建议：**把「任务提示」与「调度触发」物理分离** —— procedure 进 repo 的 `AGENTS.md`，触发是各 agent 的薄适配脚本、不进契约。

**结论三：数据布局推荐「混合（候选 C）」+ 强制异地备份**

- **repo 内**（随 git，可交接）：`AGENTS.md`、`scripts/`、`schema/*.json`、`docs/`、小体积状态种子（`fields.tsv`、首版 `rotation.json`）
- **独立数据目录** `~/knowledge-loop/`（路径由**单一配置入口** `KNOWLEDGE_LOOP_HOME` 声明，**禁止硬编码 agent 私有路径**）：`digests/`、`archive/papers.jsonl`、`archive/pdfs/`、`knowledge/`
- **备份是硬性要求** —— 旧系统正是「无备份静默丢失」15 天而无人知（`output/20260925` 佐证）。候选 C 的代价就是「git 只追契约不追数据」，所以备份必须显式做、写进 spec。

**附带推荐（本票的额外产出）**：在数据层之上放一个轻量**状态机 + 状态文件** —— `fetch → select → write → archive → update_kb → push`，每阶段把 `Status` 写进 `runs/<date>.json`。好处：任何 agent 读同一份状态即可**幂等续跑 / 接力 / 中断恢复**，不依赖某个 agent 的会话内存。

→ **这条与票 02 的结论直接汇合**：票 02 发现卡片流的上下文桥不能再用 `attach_to_session`（卡片不进会话历史），而**这份 `runs/<date>.json` 正是那个桥** —— 一物两用，且天然 agent-agnostic。

**研究产物**：`.scratch/knowledge-loop/research/06-agent-agnostic-contract.md`（162 行，含 16 条逐条分层判定表 + 出处清单）。
