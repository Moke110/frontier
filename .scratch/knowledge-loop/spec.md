# 个人知识循环 · 第一阶段 spec（草稿 v0.2）

> ⚠️ **2026-10-19 平台变更 —— 本文件 §4 §5 的载体约束已失效。**
> 微信 gateway 无法图文并茂/非文本交互，用户要求改前端。§4（单条 < 4000 字符、串行 `hermes send`）、§5（编号 + 回数字、一条打完、3 秒防抖）**都是微信的产物**，在新载体定案后必须重写。
> 平台调研见 `research/13-frontend-carrier.md`，待拍板选项见 `issues/13-frontend-carrier.md`；范围变更记录见 `map.md`。
> 其余章节（§2 数据契约、§3 检索、§6 反哺落点、§7 分层、§8 部分运维事实）**与载体无关，仍然有效**。

> **状态：草稿。** 已定项直接写；未定项在文中标 `⛔未定`，并集中列在 §9。
> 生成 2026-10-16，由 wayfinder 图 `.scratch/knowledge-loop/map.md` 的票 **01 / 02 / 03 / 04 / 05 / 06 / 10** 汇总。
> 票面细节与证据见 `issues/`，调研报告见 `research/`（590 行，带源码行号与 URL）。

---

## 0. 一句话

**checkpoint（我追的概念）→ 检索（arXiv + Europe PMC）→ 卡片（微信，一篇一条）→ 评分（编号 + token）→ 反哺（状态文件的 weight / hit_rate）**，一条闭环。

## 1. 范围

- **第一阶段 = checkpoint + 检索 + 卡片推送 + 评分反馈闭环**（用户 2026-10-16 指定）
- **不含知识库**：粒度方向已定（票 05：双层 —— 概念页 + 命题页，盲区附概念页），其余细节推迟到第二阶段
- 单人使用；宿主是 agent（本次 Hermes，但须 **agent-agnostic**）
- **判据**：推送命中率（我阅读后给的评分）

## 2. 数据契约

### 2.1 `frontier.yaml` —— 客观词汇表（**人写、低频**）

```yaml
schema_version: 1
checkpoints:
  - id: hmbs
    ontology: [HMBS, PBGD, hydroxymethylbilane synthase, 羟甲基胆素合酶]
    annotation: |
      血红素合成第三步的胞质酶（EC 4.3.1.8）。缺失 → 急性间歇性卟啉症(AIP)。
      ⛔ 不含：卟啉症的一般性综述（除非涉及 HMBS 分子本身）；ALAD / UROS 的论文
      ⚠️ 易混：PBG 单独出现时是底物、不是酶（PBGD 才是酶）
    related: [mito-import, aip-liver]
```

- **`ontology`** 只放术语与同义词 → 決定**召回**（同义词之间 **OR**）
- **`annotation`** 是**判据**（定义 + ⛔不含 + ⚠️易混），用于**检查检索结果、消歧** → 决定**精度**
- **`related`** 把同属一个命题的 checkpoint 连成**连通子图**；检索该命题 = **组间 AND**
- **命题与假说不进 ontology**（保住召回客观性，防确认偏误）
- 只有用户写这份文件；agent 只能**提议**（见 §5.3）

### 2.2 `state/checkpoints.yaml` —— 状态（**机器写、高频**）

```yaml
schema_version: 1
hmbs:
  weight: 9
  enabled: true
  last_checked: 2026-10-16
  hit_rate: { checked: 12, pushed: 4, scored_positive: 3 }
  proposals: []        # agent 的提议落这里，等用户确认
```

- **机器永不回写词汇表**，只写状态与提议（两份真相严格分开）

### 2.3 `archive/papers.jsonl` —— 去重归档（append）

- 每行：`{source, source_id, field_id→checkpoint_id, pushed_date, title, url, gist}`
- **去重键 = `source:source_id`**（`arxiv:2610.10482v1` / `pmid:42830441`）
- **额外用途（票 05 的廉价脉络）**：`title + 一句话 gist + checkpoint 归属` → 让卡片能说「本 checkpoint 最近 N 次命中里，这是第 2 次出现某形状」，**替代已推迟的知识库**

### 2.4 `runs/<date>.json` —— 当日 manifest（**卡片流的上下文桥**）

- 记录：日期、每个 checkpoint 的查询状态、候选池、**发出的卡片（序号 + 卡片内嵌 id + paper id + checkpoint_id）**
- **一物两用**：
  1. **状态机**（`fetch → select → write → archive → update_kb → push`，每阶段写 `Status`）→ 任何 agent 可幂等续跑/接力
  2. **上下文桥** —— 卡片走 `hermes send` 直发**不进会话历史**，`attach_to_session` 对卡片无效；用户回「2👎」时，agent 靠这份 manifest 还原「2」是哪篇

### 2.5 `digests/<date>_candidates.json` —— 候选全量（可追溯）

## 3. 检索

- **源**：arXiv Atom API（`export.arxiv.org/api/query`）+ **Europe PMC 全源**（`MED` + `PMC` + **`PPR` 预印本**）
- **⚠️ 查询必须限定字段**：`TITLE_ABS:`（Europe PMC）/ `[tiab]`（PubMed 语法）。实测：`"HMBS"` 不限字段 7 条、头两条完全跑偏（美罗培南给药、甲氨蝶呤药代）；`TITLE_ABS:"HMBS"` **1 条且正中靶心**
- **日期窗口**：Europe PMC 用 `FIRST_PDATE:[YYYY-MM-DD TO YYYY-MM-DD]`（注意 = **收录日期**，非出版日期）；arXiv 用 `submittedDate:[...]` 且**不能带连字符**（带则 HTTP 500）
- **覆盖策略：全域** —— 每 tick 查**全部 `enabled`** checkpoint（N=10 → 每天 20 次调用，成本可忽略）；**不做轮换调度器**
- **质量过滤**（沿用 `literature-apis` skill）：`pubTypeList` 需含 "Journal Article"、标题黑名单（poster/abstracts/proceedings/erratum/…）、必须有 pmid
- **预印本**：`PPR` 进池，卡片上须**标明是否为预印本**（未同行评审）
- **瓶颈不在查询在写作**：候选池可以大，**卡片数必须限量**（⛔ 限额待票 09）
- 已知 API 坑（arXiv 500 家族、Europe PMC 429 限流、`pdf=render` 退避）见 `literature-apis` skill

## 4. 卡片（推送形态）

- **一篇一条独立消息**（不是一条长日报）。原因：长日报的**致命伤是打分粒度** —— 整批一个分无法归因到单篇/单域 → 反哺链断掉
- **单条 < 4000 字符**（微信硬上限；超了会按 Markdown 边界**切块** → 一张卡变多条 → 归因崩坏）
- **正文必须内嵌唯一 id / 序号**（微信引用**不带消息 id**，`reply_to` 被忽略）——这是归因的**唯一**可行路径
- 四段结构（沿用旧日报的信息密度作为下界）：**做了什么 / 发现 / 为什么重要 / 保留**（+ 「为什么重要」需尽量接上 archive 里的轻量脉络）
- **发送机制**：`no_agent` cron 脚本 + **串行** `hermes send --to weixin`；**脚本 stdout 置空**（否则再投一条汇总）；**卡片间 1–2s 间隔**（Hermes 侧无节流，iLink 熔断阈值 1 次/30s 窗口）

## 5. 评分入站

### 5.1 语法（微信只有纯文本）

- **无按钮 / 无快捷回复 / 无 reaction**；唯一被官方认可的结构化输入 = **「编号列表 + 回数字」**（`clarify` 的文本回退）
- 主信号：**一条消息打完** —— `1👍 2👎 3👍 4👎`（**必须一条打完**：入站有 3 秒防抖，多条快发会被合并）
- **显式只做二元**（👍/👎 或 `+`/`-`）+ 可选一句话；**允许沉默**（沉默 = 默认保留）
- **不依赖「引用某条气泡」定位** —— 气泡 ≠ 条目（切分点在段落边界）

### 5.2 信号层级

| 信号 | 强弱 | 说明 |
|---|---|---|
| 显式二元评分 | 主信号 | 编号 + token，一条打完 |
| **是否追问某条目** | **最强正信号**（隐式） | 零额外动作、会话里天然可得；但**稀疏** |
| 沉默 | 弱负/中性 | **有偏**：「没看」与「不要」不可区分 |
| 打开率 / 停留 / 已读 | **不可行** | iLink 不投递这类事件 |

### 5.3 提议机制（agent 只能提议）

- agent 可提议**新增/停用 checkpoint**、**补充同义词**
- **同义词提议必须附「实测精确率」**：拿候选词去查，报出「前 10 条里 annotation 判为命中的有几条」；达标才提，**用户确认后才写入**
- 提议落在 `state/checkpoints.yaml` 的 `proposals`，一次最多 2–3 条（⛔ 呈现位置待票 08/09）

## 6. 反哺（评分 → 检索/排序）

**落点已定**：`state/checkpoints.yaml` 的 `hit_rate` / `weight` / `enabled`。

**政策 ⛔未定（票 08）**：权重怎么变、怎么参与排序、冷启动期怎么处理、怎么度量「系统在变好」。

**设计约束**：反哺只写**状态**，永不回写**词汇表**（保客观性与可归因）。

## 7. 分层与可移植（agent-agnostic）

| 层 | 契约 | 换 agent 要改什么 |
|---|---|---|
| ① 确定性脚本 | **CLI 契约**：子命令 / `--help` 自描述 / stdout = 机器句柄行 / stderr = 人类日志 / **退出码分级**（0 成功、2 无候选、3 取数失败…） | 几乎不用改 |
| ② agent 提示 | **`AGENTS.md`**（Linux Foundation 开放标准；Claude Code / Codex / opencode / Cursor 均读） | **只改「触发方式」** |
| ③ 数据 schema | **JSON Schema** + 全员 `schema_version` | 零改动 |

- **「任务提示」与「调度触发」物理分离** —— procedure 进 `AGENTS.md`；cron / timer / CI 是各 agent 的薄适配层，**不进契约**
- Hermes 专有的只有那层胶水：`~/.hermes/scripts/` 位置约束、runpy 真 wrapper、`attach_to_session`、`workdir`/`enabled_toolsets`、`hermes cron`

## 8. 运维与失败模式

| 事实 | 出处 |
|---|---|
| iLink 限频 `errcode -2` → 退避；熔断阈值 1 / 窗口 30s / 打开 30s | 票 10 报告 |
| `hermes send` 若打到与 cron 自动投递**同一目标** → **静默 skip**（返回 `success:true, skipped:true`） | `send_message_tool.py:464,654` |
| Hermes 侧**无**内置节流（每条 `hermes send` 是独立进程） | 票 10 |
| 微信是 **DM-only**（无 thread） | 票 02 |

⛔ **未定**：静默丢卡怎么检测与告警 · 重试策略 · 可观测面（票 11 / 12）

## 9. 未定项（= 剩余 frontier）

| 票 | 待定 |
|---|---|
| **08 评分交互** | 卡片内嵌 id 的形式 · 打分维度 · 追问与打分的语法区分 · 负信号表达 · 裸回复处理 · 改分 · 冷启动 · **反哺政策** · 度量 · 提议呈现位置 |
| **09 每日条数与节奏** | 每日卡片上限 · 连发/分批 · 未读堆积 · 候选不足或过多 · 单卡长度预算（<4000 内怎么分） |
| **11 发送器实现路径** | A/B/C/D 四选一 + **真机试推**（`hermes send` 脱离 gateway 发 weixin、连发是否被折叠 —— 均未实测） |
| **12 数据布局与备份** | 布局定案（票 06 推荐混合 C）· 数据根声明 · 小状态放哪 · **备份策略与「备份还活着」的监控** · 状态机 `Status` 枚举 |
| **04 残留** | checkpoint 初始规模（建议 8–12）· 每 checkpoint 每源查询上限（如 top 20）· `PPR` 是否默认入池 |

## 10. 已否决的方案（避免重走）

| 方案 | 否决理由 |
|---|---|
| 长日报（旧形态） | 打分粒度太粗（整批一个分）；且实测 4152–5763 字符被切成 2 条气泡 |
| C 分级摘要（30 秒版 + 深读 1 篇） | 每天只喂 1 篇纵深，用户不取 |
| 用「引用某条气泡」做定位 | 气泡 ≠ 条目；引用不带 id；`reply_to` 被忽略 |
| 用 `attach_to_session` 当上下文桥 | 卡片直发不进会话历史 → 该机制对卡片流失效 |
| 轮换检索（每天只查几个 checkpoint） | 评分只能学「域内」，学不到「域间注意力分配」 |
| 让 agent 自动往 ontology 加词 | 让搜索结果反过来定义检索边界 → 召回漂移且无法归因 |
| 盲区跨概念单独成册（票 05 的 A 方案） | 用户选 B（盲区附概念页）；**反对意见已记录**，第二阶段复核 |
| 把假说/命题写进 ontology | 会污染召回客观性（用户原则） |
