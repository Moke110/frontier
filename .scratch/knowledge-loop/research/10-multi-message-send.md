# 10 · cron 一次 tick 如何发出多条独立微信消息（卡片流推送可行性）

> 调研方式：**只读**（源码 + 官方文档 + 本地配置）。**未发送任何测试消息、未创建/修改任何 cron job**。
> 环境：WSL，home=/home/chang，Hermes v0.19.0 (2026.7.20)，源码 `/home/chang/.hermes/hermes-agent`（git install）。
> 微信（weixin）网关在线：`gateway_state.json` → `platforms.weixin.state = "connected"`（PID 263186，`gateway.pid`）。
> 调研时间：2026-10-16。

---

## ① 结论摘要

**能。但「cron agent 自己发挥多条」这条路是封死的**：Hermes 对 cron 的投递契约是「agent 的**最终回复** = **一条**消息」，且本版本**没有**给 agent 注册 `send_message` 工具。**要发 N 张独立卡片，只能让「消息投递发生在 agent 循环之外」** —— 即 **脚本**（`no_agent` cron 脚本，或 agent job 的 terminal 里）**循环调用 `hermes send`**，或脚本直接调用 Python 发送引擎 / 走 opt-in 的 `hermes mcp serve`。这几条都天然 **agent-agnostic**（换 Claude Code / Codex / opencode 驱动同样成立），其中 `no_agent` 脚本方案最纯净（根本不跑 LLM）。

---

## ② 可行方案（按推荐度排序）

### 背景事实（先看清「为什么 agent 侧不行」）

| 事实 | 出处 |
|---|---|
| cron 只投递 agent 的**最终回复**，且「agent 不自己发消息，prompt 里没有任何东西可调用」 | `website/docs/user-guide/features/cron.md`：「The agent's final response is automatically delivered to the configured `deliver:` target — the agent does not send messages itself, so there is nothing to call in the cron prompt.」 |
| 投递正文被包一层 `Cronjob Response: <name>\n(job_id: ...)\n-------------\n` | `cron/scheduler.py:1492-1501`（`_deliver_result`）；旧证据 `/home/chang/.hermes/cron/output/5765d8701ebd_20261009_083442.txt` 第 1–3 行 |
| `send_message` **故意不注册为 agent 可调工具** | `tools/send_message_tool.py:1964-1974`：「NOTE: `send_message` is intentionally NOT registered as an agent-callable model tool.」；`toolsets.py:373-377` 同义注释；`hermes tools list` 输出中无 `send_message` |
| cron 内即便能触发 send，也有**去重闸**：目标与本次自动投递目标相同时直接「跳过不发」 | `tools/send_message_tool.py:654-682`（`_maybe_skip_cron_duplicate_send`），读 `HERMES_CRON_AUTO_DELIVER_PLATFORM/CHAT_ID/THREAD_ID` |
| 自动投递变量是 **ContextVar**，由 `cron/scheduler.py:2966-2972 / 3041-3048` 设置（**仅 LLM agent 路径**，在 `no_agent` 早返回**之后**） | `cron/scheduler.py:2699`（no_agent 早返回）、`2920+`（agent 路径）、`gateway/session_context.py:119-124` |
| 子进程环境桥接：ContextVar 为 `_UNSET` 且进程已 engaged 时，把该系列变量**从子进程 env 里剥掉** | `tools/environments/local.py:404-449`（`_inject_session_context_env`） |

> **推论（关键）**：`no_agent` 脚本的子进程**拿不到** `HERMES_CRON_AUTO_DELIVER_*` → 脚本里调 `hermes send` **不会被去重闸拦**。
> 反之，**LLM agent 路径**里 agent 用 terminal 起的子进程**会**带上这三个变量 → 同一 chat 的 `hermes send` 会被**静默跳过**（返回 `{"success":true,"skipped":true,...}`）。

---

### 方案 A ★ 首选：`no_agent` cron 脚本 + 脚本内循环 `hermes send`

**能发多条？能，N 条 = N 次调用，每条是独立微信消息。**

- **调用方式**（脚本内，逐条）：
  ```bash
  /home/chang/.local/bin/hermes send --to weixin "卡片 #1 …"
  /home/chang/.local/bin/hermes send --to weixin --file /tmp/card-2.md
  /home/chang/.local/bin/hermes send --to weixin --json   # 取 message_id/success 结构化结果
  ```
  - `--to weixin`（裸平台名）→ 走 `WEIXIN_HOME_CHANNEL`（`/home/chang/.hermes/.env` 中该键**已存在**）。
  - `--to weixin:<chat_id>` → 显式目标。本机 DM 目标见 `channel_directory.json`：`o9cq8034VxuCJpJREv3KKpVdZyrU@im.wechat`。
    ⚠ 该 id 不匹配 `_WEIXIN_TARGET_RE`（`tools/send_message_tool.py:33`），所以会走 `resolve_channel_name` 的**频道名解析**（`channel_directory.json` 里 id==name，可解析成功）。
  - CLI 实现：`hermes_cli/send_cmd.py`（thin wrapper → `tools.send_message_tool.send_message_tool`）；帮助文本自述「Reuses the gateway's platform credentials (~/.hermes/.env + ~/.hermes/config.yaml) — no LLM, no agent loop, **no running gateway required**」。
- **脚本落位**：cron `script` 参数只允许 `~/.hermes/scripts/` 下的文件（`.sh`/`.bash` → bash，其它 → Python）。`website/docs/user-guide/features/cron.md:444-450`、`cron/jobs.py:1107-1113`。
- **创建方式**（**本次未执行**，仅记录）：
  ```
  hermes cron create --schedule "0 8 * * *" --no-agent \
      --script push-cards.sh --deliver local
  ```
  或由 `cronjob` 工具以 `no_agent=True, script="...", deliver="local"` 创建（`website/docs/user-guide/features/cron.md:454-468`）。
- **必须注意**：脚本 stdout 也会被**投递成一条消息**（`cron/scheduler.py:2774-2782`）。想只发卡片 → 让脚本 **stdout 为空**（静默 tick，`scheduler.py:2763-2772`）或只输出一行汇总；或把 `deliver` 设 `local` 让自动投递落到本地文件。
- **是否 agent-agnostic**：**是，最强**。`no_agent=True` 完全跳过 LLM（`cron/scheduler.py:2682-2690`：「no AIAgent, no prompt, no tool loop, no token spend」）。换成 Claude Code / Codex / opencode 驱动该 cron，行为**逐字一致**，因为根本没有 agent。
- **状态**：✅ 推荐，`WEIXIN_HOME_CHANNEL` 已就绪。⚠ 未实测（硬约束禁发）。

---

### 方案 B：cron **agent** job + `deliver: local` + agent 用 terminal 跑 `hermes send`

- **调用方式**：cron job 设 `deliver="local"`（→ `_resolve_delivery_targets` 返回空，`cron/scheduler.py:1278-1279`，因此**不设** `HERMES_CRON_AUTO_DELIVER_*`），agent 在 prompt 指示下用 `terminal` 工具循环执行方案 A 的 `hermes send` 命令。
- **为什么必须 `deliver: local`**：若保持默认 `origin`/平台投递，agent 的 terminal 子进程会带上 `HERMES_CRON_AUTO_DELIVER_*`（`cron/scheduler.py:3043-3048` + `tools/environments/local.py:440-448`），`hermes send` 打到同一 chat 会被**静默 skip**（`send_message_tool.py:672-682`）。设 `local` 后闸门失效。
- **是否 agent-agnostic**：**是**。任何能跑 shell 的 agent（含 Claude Code / Codex / opencode 的 terminal）都能执行 `hermes send`。属"agent 只是驱动者，发送走独立 CLI"的结构。
- **代价/风险**：agent 需要为每张卡做一次工具调用（token 成本 × N），且若忘设 `deliver:local` 会**静默丢卡**（返回 success/skipped）；同时最终回复还会被投递一次（除非 `[SILENT]` 抑制，`cron/scheduler.py:286-295`）。**不推荐**给"稳定卡片流"，但可用。

---

### 方案 C：脚本内**直接调用 Python 发送引擎**（绕过一切门控）

- **调用方式**（Python 脚本 / `no_agent` 脚本内）：
  ```python
  # 最底层、一次性、无需 live adapter、无需 gateway：
  from gateway.platforms.weixin import send_weixin_direct
  r = await send_weixin_direct(extra={}, token=None, chat_id="<chat_id>", message="卡片 #1 …")
  # 或走通用分发（注意：去重闸在 _handle_send，不在 _send_to_platform → 此路不被拦）
  from tools.send_message_tool import _send_to_platform
  ```
  - `send_weixin_direct(...)` 定义于 `gateway/platforms/weixin.py:2283-2381`，docstring：「One-shot send helper for `send_message` and cron delivery. This bypasses the long-poll adapter lifecycle and uses the raw API directly.」自建 aiohttp 会话，token/account 取自 `get_secret("WEIXIN_TOKEN"/"WEIXIN_ACCOUNT_ID")`（即 `.env`）。
  - 也可直接用 `tools/send_message_tool.py::_send_to_platform`（去重逻辑只存在于 `_handle_send`，`send_message_tool.py:464-466`）。
- **是否 agent-agnostic**：**是**（纯脚本，零 agent 依赖）。
- **注意**：`send_weixin_direct` 返回的 `message_id` 是 Hermes 自造 id（见 ④）；**不要**把 token 打进日志/报告。

---

### 方案 D（opt-in，需配置）：`hermes mcp serve` 暴露的 MCP 工具 `messages_send`

- **调用方式**：本机跑 `hermes mcp serve`（MCP stdio server），其暴露工具 `messages_send(target, message)`；任何 MCP 客户端（Claude Code / Cursor / **Codex** / opencode）挂上它即可循环调用。
  - 实现 `mcp_serve.py:826-858`：`messages_send` → `send_message_tool({"action":"send","target":...,"message":...})`（**注意：走 `_handle_send`，因此带去重闸**；但 MCP server 是**独立进程**，其环境**无** `HERMES_CRON_AUTO_DELIVER_*` → 不会被 skip）。
  - 另附 `channels_list`（`mcp_serve.py:862-912`）用于列出可发目标。
  - 文档：`website/docs/user-guide/features/mcp.md:802`「For sending messages, it uses the same internal send engine (tools/send_message_tool.py) that powers cron delivery and the `hermes send` CLI.」
- **是否 agent-agnostic**：**是**（MCP 是跨 agent 的通用面）。
- **现状**：**未配置**。本机 `config.yaml` 的 `mcp_servers` 只有 `biomni`（`/home/chang/.hermes/config.yaml:182-191`）。

---

### 方案 E（**判定不可行**）：直连「微信网关本地 HTTP 接口」

- **不存在**本地微信发送 HTTP 端口。weixin 网关是**出站长轮询客户端**，不是本地 HTTP 服务：
  - iLink 端点常量：`EP_SEND_MESSAGE = "ilink/bot/sendmessage"`，base `https://ilinkai.weixin.qq.com`（`gateway/platforms/weixin.py:70-89`）。
  - Hermes 自己的 `api_server`（`gateway/platforms/api_server.py:1482-1516`）路由里**没有任何「发消息到平台」的接口**：只有 `/api/platforms/{platform}/events`（**入站**回调）、`/api/jobs*`（cron 管理）、`/v1/chat/completions` 等。
- 直连 iLink 需要：`context_token`（磁盘 `~/.hermes/weixin/accounts/8f1f5ff5ab27@im.bot.context-tokens.json`）+ AES-128-ECB CDN 协议复刻 → 判定**不可行/不划算**。
- 依据查询范围：`gateway/platforms/api_server.py`、`gateway/platforms/weixin.py`、`website/docs/user-guide/messaging/weixin.md`。

### 方案 F（**判定不可行**）：把 N 张卡塞进**一条**最终回复

- `_deliver_result` 只投一次（`cron/scheduler.py:1445-1503`）。微信侧单条上限 **4000 字符**，超出才切块（`website/docs/user-guide/messaging/weixin.md:250-259`），切块点按 Markdown 边界而非"卡片边界"→ 不等价于独立卡片。**不可行**。

---

## ③ 速率限制与顺序控制

### 速率限制（weixin / iLink 侧）

| 机制 | 参数 | 出处 |
|---|---|---|
| iLink 频控 errcode/ret = **-2** | 退避重试，等待 `_send_chunk_retry_delay_seconds × 3` | `gateway/platforms/weixin.py:96, 105-109, 1792-1811` |
| 熔断器（circuit breaker） | `rate_limit_circuit_threshold` 默认 **1**，窗口 **30s**，打开 **30s** | `weixin.py:1180-1196, 1699-1720` |
| 熔断器 env 覆盖 | `WEIXIN_RATE_LIMIT_CIRCUIT_THRESHOLD / _WINDOW_SECONDS / _OPEN_SECONDS` | 同上 |
| 单条内多 chunk 间隔 | `WEIXIN_SEND_CHUNK_DELAY_SECONDS` 默认 **1.5s**；重试 `WEIXIN_SEND_CHUNK_RETRIES` 默认 **4** | `weixin.py:1169-1176, 1901-1902` |
| 单条上限 | **4000 字符**，超出按段落/代码围栏切块 | `docs/user-guide/messaging/weixin.md:250-259` |
| 会话过期降级 | errcode **-14** 或 stale **-2**（errmsg="unknown error"）→ **无 context_token 重发一次**（保证无用户新消息时的 cron 首推仍可送达） | `weixin.py:100-109, 732-745, 1770-1790` |

**「一次 tick 连发 N 条」的实际含义**：每条卡片 = **一次独立发送调用**。
- **`hermes send` 路线**：每次调用是**独立进程**，各自新建 aiohttp 会话 → 各自的熔断器状态**互不共享** → Hermes 侧**没有**为"N 条卡片"内置节流。**建议脚本自己 `sleep 1~2s`** 逐条发，避免触发 iLink 侧限频/折叠。
- 会不会被**折叠**：卡片只在**单条 >4000 字符**时被切块；N 条各自 <4000 的独立消息**不会被 Hermes 折叠**。微信客户端侧是否把连续气泡折叠属 iLink/客户端行为，**未验证**（无实测）——保守做法是控制节奏（间隔 1–2s）。

### 顺序控制

- **串行发送 → 顺序有保证**：每次发送都是 `await` 完成/CLI 同步返回后再发下一条。方案 A/C/D 都天然串行可控。
- **并发发送 → 顺序不保证**（且会更快触发熔断）。
- 方案 A/B 中若脚本用 `&` 并行 → 顺序不可控，**不要这样写**。
- 每条卡片内如有多个 chunk：按 `chunk` 顺序发送，chunk 间 1.5s 间隔（`weixin.py:1899-1902`）。

---

## ④ 引用归因（用户能否「引用回复某一条卡」并被 agent 归因）

### 入站（用户 → agent）：能拿到"被引用的内容"，但**没有 id**

- iLink 把被引用消息放在 `ref_msg`；Hermes 将其**拼成文本前缀**：
  `[引用: <title> | <ref_text>]` 或 `[引用媒体: <title>]`
  出处：`gateway/platforms/weixin.py:942-962`（`_extract_text`）。
- 同时在 `_process_message` 里把 `ref_msg.message_item` 的**媒体**也采集下来（`weixin.py:1446-1449`）。
- **关键缺口**：前缀里**不含任何 message id**。《weixin.md:200》也确认「Media from quoted (replied-to) messages is also extracted, so the agent has context about what the user is replying to.」——只有**内容**。

### 出站（agent → 用户）：没有可被回传的原生 id，且不支持程序化 reply

- Hermes 的 outbound `message_id` = **本地自造** `hermes-weixin-<uuid4hex>`，**不是**微信/iLink 的原生 msg id（`weixin.py:1900, 2172`；`SendResult.message_id=last_message_id`）。→ 用户回复时**不会**把它带回来 → **无法用 id 做精确归因**。
- `send()` 的 `reply_to` 参数被**显式忽略**：`del reply_to, kwargs`（`weixin.py:2015, 2033`）→ **不支持**"程序化引用回复某条"。
- 5 分钟入站去重窗（`weixin.py:98, 1412-1414`）与 `message_id` 有关，但与引用归因无关。

### 结论（**Hermes 微信端的能力边界**）

> **精确的 id 级归因：判不可行**（未找到任何把出站卡片 id 暴露给用户回复链路的代码）。
> **内容级归因：可行** —— **每张卡片必须自带唯一、可读的标识**（例如首行 `[卡片 #3 · arxiv:2610.10482]`，或卡片尾部带上原始 id），用户引用回复后，agent 从 `[引用: …]` 前缀里读到该标识即可归因到具体卡片。
> 这对"评分反馈"采集（并行票在做）是**直接接口要求**：卡片正文里的 id 必须**稳定且唯一**，否则引用归因会撞车。

### 会话连续性（补充，简述）

- cron 默认**不**把投递写入会话历史（`website/docs/developer-guide/cron-internals.md:272`：「Cron deliveries are NOT mirrored into gateway session conversation history.」）。
- 可 opt-in `cron.mirror_delivery` / 每 job `attach_to_session` 让投递变成**可续接会话**（`website/docs/user-guide/features/cron.md`「Continuable jobs」；代码 `cron/scheduler.py:_maybe_mirror_cron_delivery`，默认 **off**）。
- ⚠ **但对「多卡」无解**：镜像的只是"本次投递的那**一条**"（最终回复）。方案 A/C 的 N 条卡片是走发送引擎直发的，**不进会话历史**，所以**只有引用内容（④）这一条归因路**。
- 另：weixin 是 **DM 平台**（`channel_directory.json` 里 `type: "dm"`），无 thread；`weixin.md:15-24` 警告 iLink bot 身份通常收不到普通微信群事件 → 卡片推送**只能走 DM**。

---

## ⑤ 未验证 / 存疑项

1. **全部结论均为静态（源码+文档）判定，未经实测发送**（硬约束禁止发微信）。"能发多条"是从代码路径推出的，非实验观察。
2. **文档 vs 代码冲突（分块延迟）**：`docs/.../weixin.md:259` 写「0.3 s inter-chunk delay」，代码 `weixin.py:1169-1171` 是 `WEIXIN_SEND_CHUNK_DELAY_SECONDS` 默认 **1.5**。**以代码为准**。
3. **文档互相冲突（cron 镜像）**：`cron-internals.md:272` 说"不镜像"，`cron.md` 的 Continuable jobs 说可镜像。代码中两套并存 → 以 `mirror_delivery` 默认 **false** 理解。
4. **`hermes send` 对 weixin 是否真能"不依赖 gateway"**：代码层 `send_weixin_direct` 可脱离 adapter 自建会话（`weixin.py:2338-2381`），但本机只在 gateway 运行态被证明 connected；脱离 gateway 的一次性发送**未实测**。同理 `WEIXIN_TOKEN` 是否仍是有效会话**未验证**。
5. **token 锁**：`weixin.md:296-298` 说同一 token 只能一个 gateway 实例（long-poll 锁）。`send_weixin_direct` 代码里**未见**取该锁 → 与在线 gateway **并发发送**是否安全**未验证**。
6. **raw_message 里是否带被引用消息的原生 id**：`weixin.py:1464` 把原始 payload 存进 `MessageEvent.raw_message`，但文本提取只取 `message_item`/`title`。**未找到任何消费 ref 原生 id 的代码** → 目前**判不可用**。若未来要 id 级归因，此处是唯一可能的突破口。
7. **agent-agnostic 判定口径**：本报告的"是"基于「发送动作发生在 agent 循环之外（独立 CLI/脚本/MCP）」这一结构。若把 cron 换成**非 Hermes** 的外部 runner（如 Claude Code 自带 scheduler），仍需该 runner 能调用本机 `hermes` CLI 或挂 MCP —— 本机可行，但属**外部依赖**，需确认。
8. **微信客户端侧折叠/风控**：连发 N 条是否被客户端折叠、iLink 具体限频阈值（官方未公开数值，只有 -2 错误码）——**未找到文档支持**，判定"存在但阈值未知"。

---

## 附：一句话给下游的接口要求

卡片流推送的**推荐落地形态** = `no_agent` cron 脚本（`~/.hermes/scripts/*.sh`）+ 串行 `hermes send --to weixin` 逐条发送 + **每张卡片正文内嵌唯一 id/序号**（用于引用归因）+ 脚本 stdout 置空（避免多投一条）。
