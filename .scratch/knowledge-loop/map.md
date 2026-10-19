# 个人知识循环（Personal Knowledge Loop）

Label: `wayfinder:map` ｜ Slug: `knowledge-loop` ｜ Started: 2026-10-16
**Destination 于 2026-10-16 重画过一次（用户调整第一阶段范围）—— 见「范围变更记录」。**

> 📄 **先读这个**：[`spec.md`](spec.md) —— 第一阶段 spec 草稿 v0.2，已把结票内容汇总成可交接文档（已定项 vs `⛔未定` 分开标）。
> 🔁 **新会话如何接续**：读 `spec.md` → 读本 map 的 Destination / Notes / 雾 → 从 frontier 取**最小票号**的 open + unblocked 票 → **claim（改 `Status: claimed`）后**再动手 → 结票时写 `## Answer` + 在 Decisions 挂一行 + 把毕业的雾清掉。

## Destination

一份可交接的 spec（`.scratch/knowledge-loop/spec.md`），覆盖**第一阶段**：把「**checkpoint → 检索 → 卡片推送 → 评分反馈 → 反哺**」这条**闭环**锁到实现者不需要再做产品决策的程度。

- **第一阶段范围**（用户 2026-10-16 指定）：**checkpoint（前沿）+ 检索 + 评分反馈闭环**。
- **知识库不在第一阶段**：粒度方向已定（票 05：双层 —— 概念页 + 命题页，盲区附概念页），其余细节推迟到第二阶段。
- **约束**：单人使用；宿主是 agent（本次落地 Hermes cron + 微信推送，但数据格式与流程说明须 **agent-agnostic**）。
- **首要判据**：**推送命中率**（我阅读后给的评分）。
- **不做**：本图**不实现**（只做决策与调查）；不重建旧 `~/paper_digest`；不做知识库。

### 范围变更记录

**2026-10-16（用户）**：原 destination 是「四部分全在的 spec」。用户改为：「关于知识库不要再深入计划了，我们第一阶段任务是把 checkpoint + 检索 + 评分反馈闭环做出来。」→ destination 缩到三阶段闭环；知识库留方向、细节出图（见 Out of scope）。

## Notes

- **领域**：AI × 生物医学方法学与可信度（单细胞 / perturbation / 虚拟细胞 / 评测协议）。手上资产：`~/arc`、`~/_research`（HMBS 系列、AICM/AIP）、`~/library`（LINCS2020、GSE92742、virtual-cell-challenge）、`~/vcc`、`~/dargus`。
- **每个 session 应 consult 的 skill**：`grilling` + `domain-modeling`（HITL 票）、`research`（research 票）、`prototype`（prototype 票）、`cron-digest-pipelines` + 其 `references/paper-digest-instance.md`（旧系统架构，**勿重新发明**）、`literature-apis`（检索 API 的坑）。
- **沟通偏好**：中文；HITL 票**一次只问一个问题**并附推荐答案；用户常用单字母（A/B/C）回答；消息别太长（太长可能投递失败，失败了改用纯文本短消息重问）。
- **旧系统遗产**：设计在 `cron-digest-pipelines` skill；数据种子是 `~/.hermes/cron/output/` 的 8 份日报（09-25 ~ 10-09）。旧 `~/paper_digest/` 与「论文晨报」cron job 已不存在（本机与 Windows 侧均无备份）。**知识库正文未幸存**，日报里只有「今天补了几条」的报告痕迹。
- **研究产物**：`research/`（3 份报告，590 行，带源码行号与 URL）。**原型产物**：`prototypes/`（三种推送形态样张）。
- **📐 已确立的模型：前沿（票 03）** —— frontier = **checkpoint 列表**；`checkpoint = id + ontology + annotation + related`。**召回**＝同义词 OR；**精度**＝annotation 判据式消歧（定义 + ⛔不含 + ⚠️易混）；**命题** ＝ `related` 连通子图（组间 AND），**假说不进 ontology**；**状态**（`hit_rate`/`weight`/`enabled`/`last_checked`/`proposals`）另存机器写的文件。
- **🔍 检索技术要点（票 04 实测）**：
  - **查询必须限定字段** `TITLE_ABS:` / `[tiab]` —— 实测 `"HMBS"` 不限字段 7 条（头两条是美罗培南给药、甲氨蝶呤药代，完全跑偏），`TITLE_ABS:"HMBS"` **1 条正中靶心**
  - **预印本无需新 API**：Europe PMC 支持 `SRC:PPR`（16 天窗口 11,870 条）
  - Europe PMC `FIRST_PDATE` = **收录日期**；arXiv `submittedDate` **不能带连字符**（500）
  - **全域检索 + 发送侧限额**：查便宜（N=10 → 20 次/天），写贵（每篇四要点的 LLM 成本）
- **🔒 已确立的平台硬约束**（票 02 + 票 10）：单条微信 **< 4000 字符**（超长按段落切块，气泡 ≠ 条目）· **无按钮/无快捷回复/无 reaction**，唯一结构化输入 = 「编号 + 回数字」· 引用**只带文本不带 id** · 入站 **3 秒防抖**合并 · 卡片直发**不进会话历史** · **DM-only**。
- **🔒 已确立的架构原则**（票 06）：分层＝确定性脚本（CLI 契约）/ agent 提示（`AGENTS.md`）/ 数据（JSON Schema）；**「任务提示」与「调度触发」物理分离** —— 换 agent 只重写薄薄的调度胶水层。
- **⚠️ 第一阶段的结构性缺口（票 05）**：没有知识库，卡片会**「断史」**（讲不了「同一形状第 7 次」）→ spec 里用 `archive/papers.jsonl` 的 `title + gist + checkpoint` 当**轻量脉络**。
- **⚠️ 环境限制**：`web_search` / `web_extract` **未配置**（Firecrawl 无密钥）→ 用 `curl` 或 biomni MCP 的 `extract_url_content`。**Hermes 源码在 `/home/chang/.hermes/hermes-agent`（v0.19.0）** —— 查平台能力读源码，别猜文档。
- 本图的产物是**决策**，不是实现。

## Decisions so far

<!-- 索引：每行一条已结票 —— 足够判断相关性，点链接进去看细节 -->

- [01 推送形态（三种样张对比）](issues/01-push-format-prototype.md) — 采用 **B 卡片流**（一条消息一篇）。关键理由：长日报的**致命伤是打分粒度**（整批一个分 → 无法归因到单篇/单域 → 反哺断链）。连带解锁票 09、票 10。
- [02 评分采集机制](research/02-scoring-mechanism.md) — 微信只有**纯文本**；唯一结构化输入是「**编号 + 回数字**」。显式只做**二元 + 可选一句话**、允许沉默；「**是否追问**」= 最强隐式正信号；打开率/停留/已读**不可行**。
- [03 前沿画像的表示](issues/03-frontier-model.md) — 前沿 = **独立 YAML 词汇表**：`id + ontology + annotation(判据式) + related`。召回＝同义词 OR，精度＝annotation 消歧，命题＝related 连通子图（组间 AND），**假说不进 ontology**。**状态拆两份**（人写词汇表 / 机器写状态）。**只有用户写词汇表**，agent 只能提议。
- [04 信息源边界与覆盖策略](issues/04-source-boundary-and-coverage.md) — 源 = **arXiv + Europe PMC 全源（MED/PMC/PPR）**，查询**限定 `TITLE_ABS`**（实测 7 条噪音 → 1 条命中）；**全域检索 + 发送侧限额**（查便宜写贵；轮换会让评分学不到「域间注意力分配」）；同义词扩展**须附实测精确率**且用户确认才写入。
- [05 知识库载体与粒度](issues/05-knowledge-base.md) — 粒度取 **B 双层**（概念页 + 命题页，盲区附概念页）；其余细节**不深入**（推迟第二阶段）。附风险记录：盲区价值来自跨域复用，按概念拆散可能失效。
- [06 agent-agnostic 数据契约与数据布局](research/06-agent-agnostic-contract.md) — Hermes 专有的只有**「调度胶水」一层**；三层契约 = CLI 契约 / `AGENTS.md` / JSON Schema；**布局推荐混合 C**（契约在 repo、数据在 `~/knowledge-loop/`、单一配置入口 `KNOWLEDGE_LOOP_HOME`）+ **异地定时备份为硬性要求**。
- [10 卡片流的多条发送机制](issues/10-multi-message-send.md) — **可行，但发送必须在 agent 循环之外**：`no_agent` 脚本 + 串行 `hermes send --to weixin`（stdout 置空）。硬约束：卡片内嵌唯一 id、单卡 **< 4000 字符**、卡片不进会话历史。

**⚡ 跨票综合（本图最重要的结论）**：票 02 的「上下文桥 = `attach_to_session` 镜像」在卡片流下**不可用**（票 10），换成**当日 manifest 文件**（`runs/<date>.json`）后 —— 它同时是票 06 推荐的**状态机状态文件**、且是 agent-agnostic 的。**一物两用，桥的问题与状态机的问题一起解决。**

## Not yet specified

<!-- 在范围内、但还说不成一句精确问题的雾；frontier 推进后逐条毕业成票 -->

- **评分如何反哺检索与画像**（权重怎么变、怎么参与排序与选题）—— **落点已定**（状态文件的 `hit_rate` / `weight` / `enabled`），**政策待「08 评分交互」结票**。⚠️ 这是第一阶段闭环的**收口处**
- **冷启动期（无评分历史）的排序与选题权重** —— 待「08 评分交互」结票
- **怎么知道系统在变好**（命中率的度量与趋势；沉默的有偏性怎么纠）—— 度量落点已有（`hit_rate`），政策待「08」
- **提议机制的具体形态** —— agent 的提议写在哪（`proposals` vs 推送末尾）、多久汇总一次、怎么一键确认 —— 待「08」与「09」
- **第一阶段的规模参数** —— checkpoint 初始数量（建议 8–12）· 每 checkpoint 每源的单次查询上限（如 top 20）· `PPR` 预印本是否默认入池 —— 待用户给数字（票 04 残留）
- **失败与运维细节** —— 事实已有（iLink 熔断 1/30s/30s、`errcode -2` 退避、`hermes send` 同目标**静默 skip**、无内置节流）；**决策**（静默丢卡怎么检测与告警、重试策略、可观测面）待「11」与「12」

## Out of scope

<!-- 超出 destination 的工作：关闭、永不毕业 -->

- **知识库的其余细节**（载体格式 / 写入权与回退 / token 消费方式 / annotation 与知识库的权威边界）—— 第一阶段不做。粒度方向已定（票 05 = B 双层），细节作为**第二阶段的新 effort** 重新开图。
- [07 冷启动种子（8 份旧日报 → 知识库）](issues/07-cold-seed.md) — 已关闭。它是「给知识库做冷启动」，知识库既推迟，本票一并推迟到第二阶段。侦察结论保留在票面。
