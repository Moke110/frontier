# 02 · 个人简报推送后的评分反馈怎么采集

> 研究日期：2026-10-16 ｜ 环境：WSL, home=/home/chang, Hermes Agent（profile: default）
> 目标：为「个人知识循环」系统第 4 部分（推送 → 评分反馈）确定**可落地的反馈信号形态**。
> 本文所有事实均标注出处（本机文件路径 + 行号，或文档 URL / 抓取到的页面）。查不到的一律写明「未找到支持，判定为不可行」。

---

## 0. 一句话结论（先看这个）

**微信（iLink）通道上，用户回复简报后 agent 拿到的是「纯文本」**——没有可点按钮、没有快捷回复、没有消息表情（reaction）信号。唯一的结构化能力是**「引用（quote-reply）」会把被引用气泡的文本内联进用户消息**，以及 **`clarify` 工具支持的「编号选项 + 回复数字」文本回退**。因此**评分交互必须设计成「在一条普通文本消息里就能表达清楚」**，并把「最省力的信号」放在最前面。

---

## ① Hermes 微信端能力边界（逐条事实 + 证据）

### A1. 用户在微信回复一条消息，agent 到底能看到什么？

**结论：agent 看到的是一条纯文本消息（外加可选的媒体附件）。引用内容会被内联进文本。**

证据 —— 入站文本抽取函数 `_extract_text()`，文件 `gateway/platforms/weixin.py` L942–968：

- 只取 `text_item.text` 作为正文（L944–945）。
- 若带 `ref_msg`（被引用/回复的消息）：
  - 被引用的是媒体 → 前缀 `[引用媒体: <title>]`（L949–952）；
  - 否则 → 前缀 **`[引用: <title> | <被引用正文>]`**，即**把被引用消息的文字直接拼进当前这条文本**（L953–961）。
- 语音消息：若 iLink 带转写文本（`voice_item.text`），直接当文本返回（L963–967）；否则下载 SILK 音频缓存（见 A3）。

**判定：**
- ✅ 纯文本：**是**。
- ✅ 能否拿到「引用的是哪条消息」：**能——但只以文字形式拿到被引用的内容，拿不到可编程定位的消息 id**。结构化字段 `ref_msg` 只存在于 `raw_message`（`MessageEvent.raw_message`，`gateway/platforms/base.py` L1773），而进入模型上下文的是被内联进 `event.text` 的那行 `[引用: …]`。**未找到**把「被引用消息的 message_id」作为独立字段喂给 agent 的路径。
- ❌ 可点按钮：**未找到支持，判定为不可行**。
- ❌ 快捷回复：**未找到支持，判定为不可行**。
- ❌ 消息表情/reaction（点赞、拍一拍、表情回应）：**未找到支持**。`grep -i "reaction|thumb|emoji|sticker" gateway/platforms/weixin.py` 只命中一个出站标志 `no_need_thumb`（L544），无任何入站 reaction 类型。

### A2. 有没有「按钮 UI / clarify 选项」？（最接近「快捷回复」的东西）

**结论：Hermes 有一个 `clarify` 工具，可以让 agent 问「多选问题」；但微信适配器没有实现按钮渲染，只能走「编号列表 + 回复数字」的文本回退。**

证据 —— `tools/clarify_gateway.py` L20–30 明写两条投递路径：
1. **Button UI** — 适配器「override `send_clarify`」渲染内联按钮（例如 Telegram 的 `InlineKeyboardMarkup`）；
2. **Text fallback** — 没有富 UI 的适配器「渲染编号列表」，用户**回复数字（`"2"`）或自由文本**，gateway 在 `_handle_message` 里拦截并解析。

`grep -rln "def send_clarify" gateway/platforms/` 只返回 **`base.py`（默认空实现）** 和 **`whatsapp_cloud.py`**；**`weixin.py` 里没有任何 `clarify` / `send_clarify` 命中 → 微信走文本回退路径**。

解析逻辑在 `gateway/run.py` L10198–10245：`_clarify_mod.resolve_text_response_for_session(...)`，注释（L10200–10203）明确：**「直接回复多选提示也被接受（`"2"` 映射到第 2 个选项），任意文本变成自定义答案」**。

**判定：微信上「结构化选择」的唯一可用形态 = 让用户回复一个短 token（数字/字母）。这不是原生按钮，会随文本一起进入普通会话。**

实测佐证（本机 session DB）：用户在微信里确实用过这套机制——`state.db` messages 里有一条 agent 发出的 clarify 问题带 `choices_offered: ["A. …","B. …", …]`，用户以字母回复（session `20261016_081810_769c890b`）。

### A3. 消息长度 / 格式 / 媒体限制

证据 —— 文档 `/home/chang/.hermes/hermes-agent/website/docs/user-guide/messaging/weixin.md`（官方站 https://hermes-agent.nousresearch.com/docs 对应 `user-guide/messaging/weixin.md`）：

- **出站最大长度 4000 字符**（L254）；超长按「段落 / 空行 / 代码围栏」等逻辑边界切分，块间 0.3 s 延迟（L252–259）。
- **Markdown 原生保留**：标题、表格、代码块照发（L241–248）。
- **入站媒体**：图片/视频/文件都会被下载 + AES 解密 + 本地缓存；语音优先取转写文本，否则缓存 SILK（L189–211）。
- **引用消息的媒体也会被抽取**（L200）。
- **入站文本防抖批处理**：`platforms.weixin.extra.text_batch_delay_seconds` 默认 **3.0 s**；多条快速文本会被 **用 `\n` 拼成一条**再派发（L126；实现见 `weixin.py` L1510–1549，`_enqueue_text_event`）。iLink 侧长文本会在 ~2048 字符处切块（`weixin.py` L1510 `_SPLIT_THRESHOLD = 1800`），防抖会把碎片再合并。
- **去重**：按消息 id 5 分钟滑窗（L294）。

**对评分回传的影响：**
- 用 emoji 打分（👍/👎）：**会被当作普通文本**，可靠（只是需要你自己解析）；但**不能用 WeChat 的「消息表情回应」**——那类事件不投递。
- 用数字/字母打分：可靠，且与 clarify 回退路径天然一致。
- ⚠️ **多字段快速连发会被合并成一条**：若你连发 `1👍` 回车 `2👎`，默认 3 s 内会被拼成一行 `"1👍\n2👎"` —— 解析时须按行处理，或让用户一条消息里写全。

### A4. cron 的 `attach_to_session` 如何把回复带回会话？

证据 —— 文档 `website/docs/user-guide/features/cron.md` §「Continuable jobs (reply to a cron delivery)」L315–346；实现 `cron/scheduler.py` L624–756 + `gateway/mirror.py` L25–93。

**机制：**
1. 开关与优先级（`cron/scheduler.py` L624–653）：**per-job `attach_to_session` (bool) > 全局 `cron.mirror_delivery` > False**。**默认 OFF**（历史行为是「fire-and-forget：推送不进聊天历史，用户回复时 agent 完全没记录」）。
2. 生效范围（L656–686）：**只对 job 的 origin 会话生效**。fan-out / broadcast（`all`、显式发给别的 chat）**永不** mirror。
3. 写回方式（L689–756）：投递成功后，把简报正文以 **`role="user"`** 的一条 turn 追加进**目标会话的 transcript（SQLite `messages` 表）**，正文前缀 `[Cron delivery: <任务名>]\n<简报全文>`。**注意：这是写进会话历史，不是再往微信发一遍。**
4. 为什么是 user role（`mirror.py` L40–49 注释）：assistant-role mirror 会与真实 assistant 轮次相邻、破坏严格交替，故用 user role，并靠 `repair_message_sequence` 的「连续 user 合并」兜底。
5. **平台差异（`cron.md` L332–346）**：thread 能力平台（Telegram topic / Slack / Discord thread）会**每次投递新开一个独立 thread**并种入该 thread 的会话；**DM-only 平台（WhatsApp / Signal / SMS 等）无 thread，就把简报 mirror 进 origin DM 会话**。
   - ⚠️ **微信适配器未实现 thread 原语**：`grep -n "create_handoff_thread|thread" gateway/platforms/weixin.py` 只命中注释，无线程创建；且本机微信 session 全部是 `chat_type='dm'`（`state.db`）。**故微信走「DM mirror」路径：简报进 DM 会话，DM 即续接面。**

**判定：**
- ✅ 开了 `attach_to_session` 后，用户在微信回复时，**agent 会话里已经有简报全文**（含编号 1–4）——所以「讲下第 2 篇」「1👍 2👎」这类**靠编号指代**的回复完全可行，且**这是最可靠的路径**。
- ⚠️ **一次推送如果发了多条消息，用户能否逐条引用打分？** 分两层看：
  - **客户端气泡层**：简报正文 ~4200–5760 字符（实测本机 8 个日报输出文件，`char` 4152–5763），超过 4000 上限 → **一次投递通常被切成 2 条气泡**。若用户 quote-reply 某条气泡，`_extract_text` 会把**那条气泡的文字**内联进消息。**但切分点在段落边界，气泡 ≠ 条目**，所以「引用气泡 N = 第 N 篇」**不可靠**。
  - **会话层**：mirror 进会话的永远是**整篇简报的一个 user turn**（不分条）。所以**按编号（1–4）指代 > 按气泡引用**。

### A5. 简报正文的形状（实测）

证据 —— `/home/chang/.hermes/cron/output/5765d8701ebd_20261009_083442.txt`（及同目录 8 个文件）。

- 顶部自动包裹：`Cronjob Response: 论文晨报\n(job_id: …)\n-------------\n`（`cron/scheduler.py` L1482–1500，`cron.wrap_response` 默认 true）。
- 正文：Markdown，含 `**1.` … `**4.` 编号条目 + 「本次略过的候选」+ 归档核对脚注。
- 末尾**自动追加**：`To stop or manage this job, send me a new message (e.g. "stop reminder 论文晨报").`（L1500）。
- 正文里**主动邀请**：「可回复 **序号（1–4）** 追问某篇的细节、局限，或与既往脉络的关系。」——即**旧系统的反馈入口本就是「回复序号」**，而**不是打分**。

### A6. 一句话总表

| 能力 | 微信（iLink）通道 | 证据 |
|---|---|---|
| agent 收到纯文本 | ✅ | `weixin.py` L942–968 |
| 引用内容可见 | ✅（内联为 `[引用: …]`，无独立 id） | `weixin.py` L946–961 |
| 原生按钮 | ❌ 无 | 无 `send_clarify`；`tools/clarify_gateway.py` L28 |
| 快捷回复 | ❌ 无（仅「回复数字」文本回退） | `tools/clarify_gateway.py` L28–30；`run.py` L10200–10203 |
| 消息表情/reaction | ❌ 不投递 | `weixin.py` grep 无 reaction 类型 |
| 语音→文本 | ✅（有转写时） | `weixin.py` L963–967；docs L198 |
| 单条出站上限 | 4000 字符，超长切 2+ 气泡 | docs L252–259；实测 4152–5763 字符 |
| cron 简报进会话 | ✅ 需开 `attach_to_session` | `cron/scheduler.py` L624–756；`cron.md` L315–346 |

---

## ② 可行反馈信号形态清单（按实现成本从低到高）

> 「省力程度」= 用户每次要付出多少动作；「可靠性」= 信号是否精确、是否易解析、是否易被忽略。

### 形态 1：**零动作 / 隐式信号**（成本最低，可靠性中）
用户**什么都不用做**，系统从「用户后续行为」里推断。

| 信号 | 怎么拿到（本机可行） | 省力 | 可靠性 |
|---|---|---|---|
| **是否追问**（"讲下第 2 篇"）| 会话里分析用户回复 | 极高 | 高（强正例，但**稀疏**：大多数条目没人提） |
| **是否点开链接/读了 PDF** | 需外部埋点（微信点链接/本地 PDF 打开）——**本机微信通道拿不到**，只有自己维护的知识库/归档能间接反映 | 极高 | 低 |
| **条目在知识库是否被二次引用** | 你自己的 archive/知识库出现该 id | 极高 | 中高（但滞后） |

- ⚠️ 微信通道**拿不到打开率/停留时长/已读**：iLink 不投递这类事件（`weixin.py` 无相关字段）。**「打开率 / 停留 / 已读」在微信上判定为不可行**，除非把链接改成你自己的短链/落地页去埋点。
- **优点**：不增加用户负担。**缺点**：信号稀疏，而且「没反应」既可能是「不感兴趣」也可能是「没看」，**有偏**。

### 形态 2：**单 token 回复**（成本低，可靠性高）——**推荐主力**
用户回一条普通消息，内容是一个短 token。

- 例：`1👍 2👎 3👍 4👎`（一条消息打完 4 条）、或对单篇 `2👎`、或 `2+` / `2-`。
- **省力**：几秒、一条消息。**可靠性**：高（正则/按行解析即可）。
- 依据：
  - 这是微信上**唯一被官方机制认可的结构化输入**（clarify 文本回退，`run.py` L10200–10203 明说「`"2"` 映射到第 2 个选项」）。
  - 旧系统已经用「回复序号」做追问（A5），用户**已养成习惯**，迁移成本≈0。
- ⚠️ 注意 A3 的**防抖合并**：多 token 最好写在**一条**消息里，或按行解析。

### 形态 3：**编号选择题（clarify 式）**（成本中低，可靠性高）
系统主动问：「今日 4 篇，哪几篇值得留？（回数字，多选，如 `1 3`）」。本质是形态 2 的「带提示版本」。
- **省力**：中（多一轮对话，但选项现成）。**可靠性**：高。
- 依据：clarify 工具的编号列表 + 数字回退（`tools/clarify_gateway.py` L28–30）。
- **代价**：**多一次往返**，且需要用户在场；对「每天 4 篇」尚可，对「每天 20 条」会变负担 → 见 ④。

### 形态 4：**自然语言批量评分**（成本低，可靠性中）
用户随便说：「1、3 有意思，2 太水，4 看不懂」。
- **省力**：低（自然表达，最符合微信直觉）。**可靠性**：中（需 LLM 抽取，易歧义；但**语义比 token 丰富**——能区分「太水」vs「看不懂」）。
- **依据**：本机已有把回复交给 agent 处理的整套链路（cron 简报在会话里 + 用户回复即普通消息）。

### 形态 5：**引用某条气泡 + 一句话**（成本中，可靠性中）
用户 quote-reply 某条气泡后评论。
- **可靠性**：中（能拿到被引用文字，但气泡≠条目，见 A4；且依赖微信客户端是否允许引用 bot 消息——**本机未做端到端验证**）。
- **判定**：可用作**补充**，**不宜作为主路径**。

### 形态 6：**星标 / 打分面板**（成本高，可靠性高）
自建落地页，用户点链接进去打分。
- **省力**：低（要跳出微信）。**可靠性**：高。
- **代价**：需要额外开发 + 部署 + 用户改习惯。**在 Hermes 微信通道上属于过度设计**。

**排序小结（成本低→高，省力由高→低）：** ①隐式 → ②单 token → ③clarify 编号 → ④自然语言 → ⑤引用 → ⑥自建面板。

---

## ③ 业界做法与教训（显式 vs 隐式 + 防「嫌麻烦不打分」）

> 抓取受限说明：本机仅部分域名可达。**已实际抓取**的页面在每条下注明；**未能抓取**的明确标注「未能验证，属通用知识」。

### 3.1 AlphaSignal —— **一键 upvote，把反馈做成社区排名**（已抓取）
- 抓取自 https://alphasignal.ai/ ：首页在「LATEST UPVOTES」筛选下逐条列出 AI 新闻，**每条带显著的数字票数**（实测样本：9,040 / 7,817 / 5,515 …）。
- **教训**：反馈形态是**「一键点赞」这个最省力的显式动作**，并**把票数直接显示出来**当作社会证明 → 用户知道自己的点击有意义。**没有多档打分**。

### 3.2 Readwise / Readwise Reader —— **用「高亮/保存」当隐式强信号，不逼用户打分**（已抓取）
- 抓取自 https://readwise.io/reader 与 https://docs.readwise.io/reader/docs/ ：产品核心是「读 → **高亮/批注** → 自动同步到 Readwise 库 → 复习」；Reader 支持 RSS/Newsletter 订阅、Filtered Views、**Action Tags**、**Daily Digest** 邮件。
- **教训**：
  - **最省力且最真实的反馈不是打分，而是「高亮 / 保存 / 打标签」**——用户本来就会为「值得回头看的」动手，这个动作**顺便**就是评级。
  - **Daily Digest + 复习（spaced repetition）**把「消费」和「反馈」合并：你复习谁，就是你在给谁投票。
  - **不存在「请给这篇文章 1–5 分」的强制环节**——避免打断阅读。

### 3.3 学术推荐系统 —— **隐式反馈是主流，显式评分昂贵且稀疏**（已抓取 2 篇 + 通用知识）
- **BPR**（Rendle et al., arXiv:1205.2618，**已抓取摘要**）：直指「most common scenario with **implicit feedback (e.g. clicks, purchases)**」，并把目标改为**排序（pairwise preference）**而非预测绝对分。
- **Review-based RS 综述**（arXiv:2405.05562，**已抓取摘要**）：原文——「users have the opportunity to share feedback in various modes, **including numerical ratings, textual reviews, and likes/dislikes**. Traditional recommendation systems rely on **users' explicit ratings or implicit interactions (e.g. likes, clicks, shares, saves)**」。
- **FM4RecSys 综述**（arXiv:2504.16420，**已抓取摘要**）：综述「用户–物品交互 + 内容特征」的建模范式。
- **通用知识（未能本机抓取，仅作背景）**：
  - **Hu, Koren & Volinsky 2008**《Collaborative Filtering for Implicit Feedback Datasets》是「用隐式反馈（观看/购买）替代显式评分」的奠基论文——核心洞见：**隐式信号多但含义模糊（"没点"≠"不喜欢"），显式信号少但干净**。
  - **冷启动（Schein et al. 2002）**：无反馈时无法个性化 → 需要「先少量必答 + 快速迭代」。
  - **评分疲劳 / survey fatigue**：要求多档打分（1–5 星）会显著降低回收率；业界普遍退到**二元（👍/👎）或相对比较（pairwise）**。

### 3.4 Inoreader —— **未能在本机验证**
- `curl https://www.inoreader.com/` 返回 `000`（域名不可达）。**其「文章级 👍/👎 + more like this」机制未能取得第一手证据，不写入事实结论。**

### 3.5 Papr —— **未能验证「AI 新闻」形态（产品已转向）**
- 抓取 https://papr.ai/ ：当前落地页是 **「Papr Work」**（面向 GTM 的 AI 应用平台），**未出现任何「AI 新闻 / 反馈打分」入口**。原「AI 新闻」形态的反馈机制**无法从当前官网验证**，不写入结论。

### 3.6 Newsletter / 邮件类 —— **隐式为主（通用知识，未能本机抓取一手证据）**
- 行业标准隐式指标：**打开率、点击率、退订、回复**；显式几乎只有「回复」和偶尔的「这篇怎么样？」。
- **教训**：**退订是极强的负信号**；**「什么都别做」也是一种反馈（沉默 = 默认不讨厌）**。设计时应假设**多数条目不会得到显式反馈**。

### 3.7 三条业界共识（综合）
1. **显式反馈昂贵且稀疏 → 主指标应建在隐式信号上，显式只做「少量、一键」的补充。**
2. **降低单次动作的代价**：一键二元（👍/👎 / upvote）> 相对比较（A 还是 B）> 绝对多档打分（1–5 星）。**越少档越多人做**。
3. **防「嫌麻烦不打分」的关键不是催促，而是**：(a) **让可用动作 = 用户本来就会做的动作**（Readwise 的高亮/保存）；(b) **把反馈塞进已有流程**（回复一条消息，而不是去开新页面）；(c) **允许沉默**（沉默当默认，用隐式信号补）。

---

## ④ 对「评分交互设计」的 3 条最关键结论

### 结论 1 — 主信号用「回复一条文本消息」，最省力形态是**编号 + 单 token**，不要指望按钮
微信通道**没有按钮、没有快捷回复、没有 reaction**（①A1/A2，证据：无 `send_clarify`、无 reaction 类型）。唯一被官方机制认可的结构化输入是 **「编号列表 + 回复数字」**（`run.py` L10200–10203）。因此评分应交由**一条普通消息**承载，例如：
> 系统推完简报后附一行：`评分：回复如「1👍 2👎 3👍 4👎」（一条消息打完）`
理由：旧系统已用「回复序号」做追问（①A5），用户**已有肌肉记忆**；且 token 解析 100% 可靠，不像自然语言需要猜测。

### 结论 2 — **不要逐条引用气泡打分**；用**简报内的条目编号**做定位，并保证编号稳定
简报一次投递会被切成 **2 条气泡**（4000 字符上限，实测正文 4152–5763 字符），且切点在段落边界、**气泡 ≠ 条目**（①A4/A5）。所以「引用第 N 条气泡 = 评第 N 篇」**不可靠**。
做法：**在简报正文里给每条一个稳定编号**（旧系统的 `**1.` … `**4.` 已经做到），用户**只回编号**；`attach_to_session=true` 会把**整篇简报**作为一个 user turn 写回会话（`cron/scheduler.py` L689–756），agent 因此**始终能看到编号与全文的对应关系**。
→ **必须开 `attach_to_session=true`**，否则 agent 回复时对简报「失忆」，编号无从对应。

### 结论 3 — 显式评分要「少、可沉默、能被隐式信号补」，绝不做多档强制打分
业界一致：显式评分昂贵稀疏，**一键二元（👍/👎）或 upvote 才是回收率最高**的形态（②③：AlphaSignal 只做 upvote；Readwise 干脆用「高亮/保存」代替打分；BPR/Hu 等以隐式反馈为主）。结合微信通道限制：
- **显式**：只提供**二元 + 可选一句话**（emoji 或 `+/-`），且**允许整条不回**（沉默 = 默认保留）。
- **隐式**：把「**是否追问该条目**」（"讲下第 2 篇"）当作**最强正信号**记录——它在会话里天然可得、零额外动作。**「打开率 / 停留 / 已读」在微信通道拿不到**（iLink 不投递），**判定为不可行**，除非自建带埋点的落地页（此时退回③形态 6，成本高）。
- **防疲劳**：把「评分」做成**回复简报的顺手动作**而不是**独立的评分环节**；多条目一次性回 `1👍 2👎 3👍 4👎`，不要一条一条问。

---

## 附录 · 证据清单

**本机源码/文档（绝对路径）**
- `/home/chang/.hermes/hermes-agent/gateway/platforms/weixin.py` —— `_extract_text` L942–968（文本/引用/语音）；防抖批处理 L1510–1549；无按钮/无 reaction（grep 证据）。
- `/home/chang/.hermes/hermes-agent/tools/clarify_gateway.py` —— L20–30（Button UI vs Text fallback）。
- `/home/chang/.hermes/hermes-agent/gateway/run.py` —— L10198–10245（clarify 文本回退解析）。
- `/home/chang/.hermes/hermes-agent/cron/scheduler.py` —— `_cron_mirror_delivery_enabled`/`_target_matches_origin`/`_maybe_mirror_cron_delivery` L624–756；投递包裹 L1482–1500。
- `/home/chang/.hermes/hermes-agent/gateway/mirror.py` —— L25–93（`mirror_to_session`，user-role mirror 原因 L40–49）。
- `/home/chang/.hermes/hermes-agent/website/docs/user-guide/messaging/weixin.md` —— L189–211（媒体）、L241–259（Markdown/切分/4000）、L96–127（特性/配置）。
- `/home/chang/.hermes/hermes-agent/website/docs/user-guide/features/cron.md` —— L315–346（continuable jobs / attach_to_session / 平台差异）。
- `/home/chang/.hermes/cron/output/5765d8701ebd_20261009_083442.txt`（及同目录 8 份）—— 简报正文形状；实测 4152–5763 字符。
- `/home/chang/.hermes/cron/jobs.json` —— `{"jobs": []}`（旧 job 已不存在）。
- `/home/chang/.hermes/state.db` —— `sessions` 表：微信 3 个会话，`source='weixin'`、`chat_type='dm'`；`messages` 表含 clarify `choices_offered` 实例。

**外部抓取（2026-10-16 实测可达）**
- https://alphasignal.ai/ —— 「LATEST UPVOTES」+ 每条数字票数。
- https://readwise.io/reader 、https://docs.readwise.io/reader/docs/ —— 高亮/批注/同步/Daily Digest/RSS/Action Tags。
- https://arxiv.org/abs/1205.2618 —— BPR，「implicit feedback (e.g. clicks, purchases)」。
- https://arxiv.org/abs/2405.05562 —— Review-based RS 综述，「numerical ratings, textual reviews, and likes/dislikes」「explicit ratings or implicit interactions (e.g. likes, clicks, shares, saves)」。
- https://arxiv.org/abs/2504.16420 —— FM4RecSys 综述摘要。

**未能取得一手证据（明确排除）**
- Inoreader（`https://www.inoreader.com/` 返回 000）；Papr 的「AI 新闻」形态（当前 papr.ai 已转向 Papr Work）；Newsletter 打开率/点击率的公开一手数据（通用知识）；Hu et al. 2008 与 Schein et al. 2002 原文（通用知识，未抓取）。
