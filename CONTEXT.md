# frontier — domain glossary

This file is vocabulary, not a spec. Implementation lives in `contracts/` and the code.

## Knowledge card（知识卡片）

The canonical frontier item. A knowledge card **replaces** the old checkpoint.

Fields: `id`, `label`, `ontology`, `annotation`.

- `ontology` drives recall (synonyms / surface forms).
- `annotation` drives precision (definition, exclusions, confusions).
- A card stores **no** knowledge-to-knowledge links and **no** knowledge-to-proposition links.

## checkpoint

Retired as an independent entity. Where the old vocabulary says "checkpoint", read "knowledge card id". Retrieval plans over knowledge cards.

## Proposition（命题）

A cross-paper synthesized claim, not a per-paper summary.

Fields: `id`, `title`, `review`, `related_knowledge`, `evidence`, `changelog`,
`evidence_updates_since_review`.

- `related_knowledge` is a list of knowledge card ids and **must contain at least two cards**.
- A new proposition must carry **at least two evidence entries**.
- `review` is the current synthesis (≤2000 characters, four fixed sections).
- `changelog` records non-evidence changes (title / review / related_knowledge): timestamp, source, before → after, rationale.

## Evidence（证据）

One entry in a proposition's `evidence` list: `id`, `stance` (`supports` /
`contradicts`), `conclusion` (≤200 characters), `papers[]` (paper_id, push_id,
page, quote, added_at), `created_at`, `updated_at`.

- An entry contains only reports whose conclusions point in the same direction.
- Different entries under the same proposition may contradict each other.
- A new report merges into an existing entry when the stance and direction agree; otherwise it becomes a new entry.

## Review（综述）

A proposition's `review` is synthesized from its evidence, never from outside
facts. It is rewritten automatically after every ten accepted evidence updates.
Rejecting a new review keeps the counter; the next accepted evidence update
retries.

## Evidence update（证据更新）

One accepted `add_proposition_evidence` or `merge_proposition_evidence` proposal.
Each accepted proposal counts as one update, regardless of how many reports it
adds.

## Review update（综述更新）

The queued question that asks the user to adopt a newly written review. It is
independent of the per-push update budget and gates the next retrieval push
until answered.

## Theme（主题）

Not a stored entity. A theme is only a grouping used to batch-confirm the initial knowledge-base build. Confirmed themes become knowledge cards and propositions; the theme name itself is not persisted as a graph node.

## Push（推送）

One paper's long-form push (HTML from Phase 3) plus its rating question and any knowledge-update questions. One push, one paper.

「推送」是一次事件；它渲染出的文件是「推送件」，不要用「推送」指文件。
_Avoid_: 文章、PDF

## Unified question queue（统一问题队列）

A single serial queue of questions produced by a push or by the initial build confirmation flow.

- Item kinds: push rating, knowledge-card update, proposition evidence update, proposition review update.
- One active question at a time; the next is sent only after the current one is submitted.
- Updates to the same card or the same proposition are grouped into one question.
- One push has at most **two entity targets** in total (cards + propositions, creates included).
- A rating is answered first; update questions follow.
- An `irrelevant` rating discards that push's update questions.
- Every question must be answered before the next retrieval push may start.

## Pending retrieval request（待推请求）

A retrieval trigger (manual "再推一篇" or the daily 08:00 run) that arrives while the question queue is non-empty. It is recorded, coalesced with other pending requests, and executed automatically once the queue is empty.

## Rating（评分）

`irrelevant` / `ok` / `great`. This phase uses ratings only to gate knowledge updates; ratings do **not** feed back into retrieval weights or ranking.

## Writer

The agent role that reads a paper and proposes knowledge-card / proposition updates. The writer never writes `$KL_HOME/archive/**` directly; approved changes go through the archive CLI.

## 存储与档案

**原文（source document）**:
一篇论文的 PDF 原件，主键 `paper_id`。一条原文记录对应云盘里至多一个文件 —— 同一篇论文永远只有一份原件。
_Avoid_: 文献、资料、PDF 文件、附件

**报道（report）**:
某条证据对某篇原文的一次具体引用（论文 + 推送 + 页码 + 引文）。一行不是一篇论文；同一篇原文可以有多条报道。
_Avoid_: paper、papers 表、引文记录

**推送件（push artifact）**:
一次推送渲染出的自包含 HTML（图片内联、无外部依赖），主键 `push_id`。它是"当时看到的东西"，不是可以重新生成的视图。
_Avoid_: 推送、PDF、文章

**分片（part）**:
一个超过云盘单文件上限的原文被切成的有序片段（`<paper_id>.pdf.partNN`），顺序记在「原文」的 `分片` 列。读的时候拼回整份、按整份 md5 校验。
_Avoid_: 分段、chunk、附件

**库（library）**:
同类文件在云盘的一个根目录，外加 Base 里对应的登记表。原文库、推送库各一个；两者共用一个配额。
_Avoid_: 文件夹、存储桶、bucket

**原文库**:
原文的库。收录"推送过的论文"与存量迁移进来的原件；取不到 PDF 时仍登记一行，标为无原件。
_Avoid_: 论文库、文献库

**推送库**:
推送件的库。只收已送达的推送 —— 发送失败的不入库。

**在库（in library）**:
文件已在云盘且 Base 有登记。只有这个状态计入配额。
_Avoid_: 已上传、已同步

**无原件（no source file）**:
原文记录存在、云盘无文件（多为付费墙）。证据引文退化为按摘要锚定。

**已离线归档（archived offline）**:
文件已下载到本机备份位置、md5 校验通过并从云盘删除。Base 行永久保留。
_Avoid_: 已删除、已清理

**待上传（pending upload）**:
Base 有行、云盘无文件，等待补传。断链对账后的默认状态。

**配额（quota）**:
原文库与推送库合计允许占用的云盘字节数，默认 5GB，用户直接在 Base 修改。只统计在库记录。
_Avoid_: 限额、容量上限（作为术语时用配额）

**缓存（cache）**:
本地按需下载与派生的副本（PDF、正文文本、页码锚点、索引），随时可删，命中以 md5 为准。
_Avoid_: 镜像、备份、本地库

**离线备份（offline backup）**:
把在库文件下载到本机目录并校验 md5 的动作，是删除云盘文件的前置条件。
_Avoid_: 归档、导出

**对账（reconcile）**:
把云盘目录的实际文件与 Base 登记逐项比对，产出四类差异：孤儿文件、断链、重复文件、状态与实物不符。

**孤儿文件**:
云盘有文件、Base 没有对应行。无害，补登记即可。

**断链**:
Base 有行、云盘无文件。有害：通常改回待上传并提醒；若该行已有备份位置，则置为已离线归档。

**决定（decision）**:
用户对一条更新提议的终态（采纳 / 拒绝），按提议粒度记录，用问题 ID 聚合同一次问答。它解释"为什么这条证据没被采纳"。
_Avoid_: 审批、答复、投票
