# 10 卡片流的多条发送机制

Type: research ｜ Status: resolved ｜ Blocked by: —
Claimed by: Hermes (session 2026-10-16)

## Question

卡片流要求一次推送发出 **N 张独立卡片**。这在 Hermes 上可行吗、怎么做？—— 这是票 01 选定 B 之后暴露的**最大可行性风险**。

需要查清：

- Hermes cron job 的一次 tick，**是否只能发最终回复那一条消息**？agent 有没有 `send_message` 之类可主动多次发送的工具？gateway 有没有对外发送接口？
- 若 agent 侧不能主动发多条，能否由**确定性脚本**直接调 gateway / 微信侧发送接口发多条？有无速率限制或风控？
- 多条消息的**顺序与延迟**能否控制？连发会不会被折叠 / 合并 / 限流？
- 每条卡片能否被用户**引用回复**、并被 agent 归因到具体那一条？（与票 02 第 2、3 问重叠 —— **若票 02 已答这两问，本票只补「怎么发」**）

**产出**：`.scratch/knowledge-loop/research/10-multi-message-send.md`，含可行方案（按推荐度排序）+ 每个方案「**换 agent 时是否还成立**」（与票 06 的 agent-agnostic 契约对齐）。

## Answer

**结论：卡片流可行 —— 但「让 agent 自己发多条」这条路是封死的，发送必须发生在 agent 循环之外。**

### 我独立复核过的事实（非仅采信子 agent 报告）

| 事实 | 证据（已实跑/实读） |
|---|---|
| `hermes send --to <target> [msg]`、`--file`、`--json` 存在，**不需 LLM、不需 agent 循环** | `hermes send --help`（实跑）· `hermes_cli/send_cmd.py` |
| agent **没有** `send_message` 工具 → cron 内 agent 无法主动发多条 | `hermes tools list` 无此项（实跑）· `tools/send_message_tool.py:1964` 注释「intentionally NOT registered」 |
| 用户**引用回复**只带来**文本**（标题 + 正文），**不含任何消息 id** | `gateway/platforms/weixin.py:961` → 拼成 `[引用: …]` 文本前缀（实读） |
| 单条消息上限 **4000 字符**，超出按 Markdown 边界**切块** | `website/docs/user-guide/messaging/weixin.md:254`（实读） |
| cron 内去重闸：打到与自动投递**同一目标**会被**静默 skip**（返回 `success:true, skipped:true`） | `tools/send_message_tool.py:464, 654`（实读） |
| cron 投递契约 =「agent **最终回复** = 一条消息」 | 旧实物 `~/.hermes/cron/output/5765d8701ebd_20261009_083442.txt` 开头的 `Cronjob Response:` 包裹 |

### 本票的答案：推荐落地形态（报告方案 A）

> **`no_agent` cron 脚本**（`~/.hermes/scripts/*.sh`）+ **串行 `hermes send --to weixin`** 逐条发送 + **每张卡片正文内嵌唯一 id/序号** + **脚本 stdout 置空**（否则会再投一条汇总）。

**为什么 A 最优**：`no_agent=True` 完全跳过 LLM（`cron/scheduler.py:2682-2690` 早返回，无 prompt、无 tool loop、无 token）→ 换成 Claude Code / Codex / opencode 驱动，行为**逐字一致**（根本没有 agent 可换）。这是本项目硬约束「agent-agnostic」的最强解。

其它候选（详见研究报告）：B = agent job + `deliver:local` + terminal 跑 `hermes send`（会 ×N token，且忘设 `deliver:local` 会**静默丢卡**）；C = 脚本直调 `gateway.platforms.weixin.send_weixin_direct`；D = 开 `hermes mcp serve` 用 `messages_send`。**判定不可行**：E = 本地微信 HTTP 口（不存在，网关是出站长轮询）；F = 把 N 张卡塞进一条回复（`_deliver_result` 只投一次）。

### 连带后果（本票真正的价值）

1. **票 08 的问题形状**再次修正 → 打分必须靠**卡片正文内嵌 id**：引用回来只有标题+文本；`reply_to` 参数被显式忽略（`weixin.py:2015`）；出站 message_id 是自造 `hermes-weixin-<uuid>` 且不回传 → **唯一归因路 = 内容级归因**。
2. **票 08 还必须吸收「追问」**：卡片走直发**不进会话历史**（`cron.mirror_delivery` 只镜像「最终回复那一条」）→ 旧系统靠 `attach_to_session` 支持的「回复『讲下第 2 篇』」在卡片流下**断了**。→ **打分与追问必须共用同一个「入站语法」，一起设计。**
3. **票 09 的「单卡长度上限」有了硬数字：< 4000 字符** —— 超出会被切块 → 一张卡变多条 → 归因崩坏。
4. **新票 11**：发送器实现路径（A/B/C/D 四选一的落地验证与定夺），依赖票 06。
5. **雾「失败与运维」**需补上：**静默丢卡**、**iLink 熔断与 -2 退避**（阈值 1 / 窗口 30s / 打开 30s；Hermes 侧**无**内置节流 → 脚本自加 1–2s 串行间隔）。
6. **DM-only**：weixin 是 DM 平台（无 thread），卡片推送只能进 DM。

**未验证项（继承给票 11 的真机试推）**：本报告全部为**静态判定**（源码 + 文档），**未实测发送**（硬约束禁发）。`hermes send` 脱离在线 gateway 发 weixin、token 并发安全性、微信客户端对连发气泡的折叠阈值 —— 均未验证。

**研究产物**：`.scratch/knowledge-loop/research/10-multi-message-send.md`（4 可行方案 + 2 不可行方案 + 速率/顺序/归因分析，全文带源码行号）。
