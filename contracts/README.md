# frontier 原型 · 文件契约

六个模块之间**不 import 彼此**，只通过下面这些文件交换数据。任何模块都可以被替换，只要仍读写同样的形状。
所有 JSON 顶层带 `schema_version: 1`，时间统一 ISO-8601（本地时区，秒级，如 `2026-10-20T09:30:00+08:00`）。

> editor / writer 的 agent 任务包（`editor-task.json`、`writer-task.json`）与校验规则见 [`agent-tasks.md`](agent-tasks.md)。

数据根由环境变量 `KL_HOME` 指定（默认 `~/knowledge-loop`）：

```
$KL_HOME/
├── state/
│   ├── checkpoints.yaml          # 机器写：按知识卡片 id 存权重 / 命中率 / 最后检索
│   └── editor.yaml               # 机器写：评分学出的偏好模型
├── archive/                      # 只有 archive 模块写
│   ├── raw/<paper_id>.json       # ① 原文（元数据）
│   ├── raw/text/<paper_id>.txt   # ① 原文（正文/摘要文本）
│   ├── raw/pages/<paper_id>.json # ① PDF 页码锚点（正文页码 → 字符区间）
│   ├── reports/pdf-ingest-*.json # PDF 入库运行报告
│   ├── pushes/<push_id>.json     # ② 推送
│   ├── pushes/assets/<push_id>/  # ② 推送图片（原文图 / 生成图）
│   ├── cards/<card_id>.json      # ③ 知识卡片（取代 checkpoint + kg node）
│   ├── propositions/<id>.json    # ④ 命题
│   ├── index/*.jsonl             # 各层索引（可 reindex 重建）
│   ├── applied/<proposal_id>.json# 已应用的更新记录
│   └── legacy/v1-<ts>/           # v1 迁移备份（可 rollback）
├── ratings.jsonl                 # publisher 写，editor/frontier 读
├── queue/                        # 统一问题队列（docs/specs/unified-question-queue.md）
│   ├── state.json                # 队列表 + 单 active
│   ├── events.jsonl              # 只追加的审计/重建日志
│   ├── request.json              # 合并后的待推请求
│   ├── lock                      # 队列状态排他锁
│   └── start.lock                # 检索启动租约（预留）
└── publisher/
    ├── messages.jsonl            # message_id → push/queue item，用于回调路由
    ├── pending/<proposal_id>.json# 旧审批链路的待审批副本（v2 不再新增）
    ├── decisions.jsonl           # 用户同意/拒绝
    ├── trigger.lock              # 手动补推串行锁
    ├── trigger.log               # 手动补推事件日志
    └── outbox/                   # 离线模式生成的卡片 JSON（调试用）
```

---

## 1. 知识卡片与状态

知识卡片是 frontier 的唯一知识单元，取代 v1 的 checkpoint 与 kg node。**卡片不存任何链接**（知识—知识、知识—命题都不存）；连接只存在于命题的 `related_knowledge`。

`archive/cards/<card_id>.json`（`archive` 写）：

```json
{
  "schema_version": 2,
  "id": "card_hmbs",
  "label": "HMBS",
  "ontology": ["HMBS", "PBGD", "hydroxymethylbilane synthase"],
  "annotation": "血红素合成第三步的胞质酶……\n⛔ 不含：……\n⚠️ 易混：……",
  "created_at": "2026-10-20T09:00:00+08:00",
  "updated_at": "2026-10-20T09:00:00+08:00"
}
```

- `id`：语义 slug，`^card_[a-z0-9][a-z0-9_]*$`，如 `card_hmbs`、`card_virtual_cell`。
- `label` 非空；`ontology` 是非空字符串列表（检索召回用）；`annotation` 非空（精确性判断与排除项）。
- 自动生成 id 时用 label 的 ASCII slug；冲突追加 `_2`、`_3`；非 ASCII label 必须显式给 id。
- `frontier.yaml` 已退役；检索计划直接读卡片。旧 checkpoint 词汇（`checkpoint_id`）在新数据里就是卡片 id。

`state/checkpoints.yaml`（机器写、高频；文件名保留，键是卡片 id）：

```yaml
schema_version: 1
checkpoints:
  card_hmbs:
    weight: 5                    # 1..10，editor 排序用
    ema: 0.5                     # 评分的指数滑动平均
    enabled: true
    last_checked: "2026-10-20"
    hit_rate: { checked: 12, pushed: 4, scored_total: 3, scored_positive: 2 }
    proposals: []
```

## 2. 原文 `archive/raw/<paper_id>.json`

```json
{
  "schema_version": 1,
  "paper_id": "europepmc_42830441",
  "source": "europepmc | arxiv | fixture",
  "source_id": "42830441",
  "checkpoint_id": "card_hmbs",
  "title": "…",
  "abstract": "…",
  "text_path": "raw/text/europepmc_42830441.txt",
  "authors": ["…"],
  "journal": "…",
  "published": "2026-10-02",
  "url": "https://…",
  "is_preprint": false,
  "fetched_at": "2026-10-20T09:00:00+08:00",
  "query_id": "q_hmbs_europepmc"
}
```

去重键 `source:source_id`；`paper_id = <source>_<sanitized source_id>`。
`checkpoint_id` 是历史字段名，值是知识卡片 id（如 `card_hmbs`）；新代码也接受 `card_id`。

### 2.1 PDF 入库（`pdf_ingest`）

`python -m pdf_ingest.cli run --manifest fixtures/pdf-manifest.jsonl [--limit N] [--dry-run]`

- `source = "pdf"`；`paper_id` 由 PDF 文件主名生成并与初始主题清单一致：
  `2025_Anders_Bench-LinBaseline.pdf` → `pdf_2025_anders_bench_linbaseline`。
- `source_id` 回退顺序：manifest 的 `doi`（小写）→ `pmid:<pmid>` → `arxiv:<id>`（去 `arXiv:` 前缀、小写）→ `md5:<md5>`。
- manifest 是书目与身份的唯一来源（PDF ` /Title`、印刷 DOI 不可信）；raw 记录额外保留
  `doi / pmid / pmcid / arxiv / md5 / category / pdf_path / pdf_pages / pages / year / notes`。
- 正文：PyMuPDF `page.get_text("text")`，各页文本按 `"\n\n"` 连接写入 `raw/text/<paper_id>.txt`。
- 页码锚点 `archive/raw/pages/<paper_id>.json`：

```json
{
  "schema_version": 1,
  "kind": "page-anchors",
  "paper_id": "pdf_2025_anders_bench_linbaseline",
  "text_path": "raw/text/pdf_2025_anders_bench_linbaseline.txt",
  "md5": "…",
  "page_sep": "\n\n",
  "pdf_pages": 21,
  "text_chars": 61000,
  "extracted_at": "2026-10-21T15:00:00+08:00",
  "page_anchors": [
    {"page": 1, "start": 0, "end": 2980, "chars": 2980, "text_empty": false}
  ]
}
```

`page` 是 **PDF 页序（1 起）**，不是印刷页码；`[start, end)` 是全文 `.txt` 的字符区间。
`text_empty: true` 表示整页是图（应标为 `figure_page`，不参与检索）。
引文定位用 `pdf_ingest.anchors.locate_quote(text, page_anchors, page, quote)`：
匹配忽略 PDF 换行造成的空白差异，不忽略用词。

入库幂等：完整论文重跑记 `skipped`；缺 text 或 pages 的已存在论文就地补写并记 `repaired`；
单篇失败只记入 `archive/reports/pdf-ingest-<ts>.json` 的 `failures`，不中断整批。


## 3. 候选 `candidates.jsonl`（retriever → editor）

每行是一篇原文记录，外加：

```json
{ "…paper 字段…": "…", "retrieval": { "query_id": "q_card_hmbs_europepmc", "checkpoint_id": "card_hmbs", "rank_hint": 1 } }
```

## 4. 选择 `selection.json`（editor → writer）

```json
{
  "schema_version": 1,
  "date": "2026-10-20",
  "selected": [
    {
      "checkpoint_id": "card_hmbs",
      "paper": { "…paper 字段…": "…" },
      "score": 0.82,
      "breakdown": { "relevance": 0.9, "recency": 1.0, "preference": 0.5, "weight": 0.5 },
      "rationale": "ontology 命中 3 个词；2 天前发表；checkpoint 偏好 0.5"
    }
  ]
}
```

## 5. 推送 `archive/pushes/<push_id>.json`（writer → archive / publisher）

```json
{
  "schema_version": 1,
  "push_id": "2026-10-20_card_hmbs_01",
  "date": "2026-10-20",
  "checkpoint_id": "card_hmbs",
  "paper_ids": ["europepmc_42830441"],
  "title": "HMBS：…",
  "body_md": "…四段结构…",
  "sections": { "did": "…", "found": "…", "why": "…", "keep": "…" },
  "context": { "card_id": "card_hmbs", "propositions": ["prop_…"], "archived_count": 12 },
  "proposals": [ { "…proposal…": "…" } ],
  "status": "written",
  "created_at": "2026-10-20T09:10:00+08:00"
}
```

## 5.1 长文推送 `format: pdf`

正式流程使用长文 PDF；`format` 缺省或为 `card` 时仍按 §5 的四段卡片处理（离线 fallback）。

```json
{
  "schema_version": 1,
  "format": "pdf",
  "push_id": "2026-10-20_card_hmbs_01",
  "date": "2026-10-20",
  "checkpoint_id": "card_hmbs",
  "checkpoint_label": "HMBS",
  "paper_ids": ["europepmc_42830441"],
  "paper": {
    "paper_id": "europepmc_42830441",
    "source": "europepmc",
    "title": "…",
    "authors": ["…"],
    "journal": "…",
    "published": "2026-10-02",
    "url": "https://…",
    "is_preprint": false
  },
  "title": "HMBS：……",
  "sections": {
    "takeaway": "一句话结论",
    "background": "研究背景与问题",
    "methods": "方法",
    "results": "关键结果",
    "why": "与知识卡/命题的关系",
    "limits": "局限与存疑",
    "sources": "原文与数据（至少一个 URL）"
  },
  "body_html": "<h2>背景</h2><p>…</p><figure data-asset=\"fig-1\"></figure>",
  "assets": [
    {
      "id": "fig-1",
      "path": "assets/2026-10-20_hmbs_01/fig-1.png",
      "caption": "图 1. …",
      "source": "paper | generated",
      "origin_url": "https://…"
    }
  ],
  "proposals": [],
  "status": "written",
  "created_at": "2026-10-20T09:10:00+08:00"
}
```

约束：

- `body_html` 是正文**片段**，不是整页；不得含 `<script>` / `<style>` / `<link>` / 内联事件；
- 每个 `<figure data-asset="…"></figure>` 必须对应 `assets` 里的一项，至少一张图；
- `assets[].path` 是相对 push 文件的路径，不得越出 outbox；
- `assets[].caption` 非空，`source` 只能是 `paper` 或 `generated`，渲染时会自动加「原文图 / 生成图」标记；
- `writer render` 用固定模板把片段渲染成 PDF；`archive add-push` 会把 `assets/<push_id>/` 一并复制进 `archive/pushes/assets/`。

## 6. 知识卡片

卡片即 `archive/cards/<card_id>.json`，形状见 §1。没有 `kg/nodes`、没有 `kg/edges.jsonl`：
v2 不存知识—知识链接，也不存知识—命题链接。需要“关联”时读命题的
`related_knowledge`（反向查：`archive.cli prop-list --card <card_id>`）。

写入命令：

```bash
python -m archive.cli card-put --file card.json      # 新建或更新（id 省略则按 label 生成）
python -m archive.cli card-get card_hmbs
python -m archive.cli card-list
python -m archive.cli context --card card_hmbs       # 卡片 + 命题 + 历史篇数
```

## 7. 命题 `archive/propositions/<id>.json`

```json
{
  "schema_version": 2,
  "id": "prop_hmbs_aip",
  "title": "HMBS 功能缺失导致 AIP",
  "content": "HMBS 功能缺失导致急性间歇性卟啉症（AIP）。",
  "related_knowledge": ["card_hmbs", "card_aip"],
  "history": [
    {
      "at": "2026-10-20T09:00:00+08:00",
      "action": "created",
      "source": { "kind": "paper | push | user | migration | cli", "id": "…" },
      "before": null,
      "after": { "title": "…", "content": "…", "related_knowledge": ["…"] },
      "rationale": "为什么改",
      "evidence": [
        { "paper_id": "europepmc_42830441", "push_id": "…", "page": 7, "quote": "原文引文" }
      ]
    }
  ],
  "created_at": "2026-10-20T09:00:00+08:00",
  "updated_at": "2026-10-20T09:00:00+08:00"
}
```

约束：

- `related_knowledge` 至少 2 个**已存在**的卡片 id，不得重复；
- `history` 非空，`action ∈ created | content_changed | title_changed | related_knowledge_changed | evidence_added`；
- 改 title / content / related_knowledge 必须追加 history（`archive.store.update_prop` 会做）；
- 证据只存在 history 里，不再有顶层 `evidence` 字段。

写入命令：

```bash
python -m archive.cli prop-put --file prop.json
python -m archive.cli prop-get prop_hmbs_aip
python -m archive.cli prop-list --card card_hmbs
```

## 8. 评分 `ratings.jsonl`（publisher → editor / frontier）

```json
{
  "schema_version": 1,
  "rating_id": "r_20261020T091500_ab12",
  "push_id": "2026-10-20_hmbs_01",
  "message_id": "om_xxx",
  "operator_id": "ou_xxx",
  "verdict": "irrelevant | ok | great",
  "comment": "…",
  "created_at": "2026-10-20T09:15:00+08:00"
}
```

## 9. 更新提议 `proposal`

嵌在 push 里；v2 每篇推送最多 **2 个卡片目标 + 2 个命题目标**，同一目标的多个操作在入队时合并成一个更新题（见 `docs/specs/unified-question-queue.md`）。

```json
{
  "schema_version": 2,
  "proposal_id": "p_2026-10-21_card_hmbs_01_01",
  "push_id": "2026-10-21_card_hmbs_01",
  "op": "add_proposition_evidence",
  "target_type": "proposition",
  "target_id": "prop_hmbs_aip",
  "diff": {
    "op": "add",
    "path": "evidence",
    "value": { "paper_id": "europepmc_42830441", "page": 3, "quote": "…", "section": "results" }
  },
  "before": 0,
  "after": 1,
  "rationale": "为什么这条更新成立",
  "confidence": 0.7,
  "evidence": { "paper_id": "europepmc_42830441", "page": 3, "quote": "…", "section": "results" },
  "status": "draft"
}
```

### 9.1 操作表

| `op` | `target_type` | `target_id` | `diff.path` | `diff.value` | `before` / `after` |
|---|---|---|---|---|---|
| `add_card_ontology` | `card` | 已有卡片 id | `ontology` | 新词（string）或词列表 | 当前 ontology / 追加后的 ontology |
| `update_card_annotation` | `card` | 已有卡片 id | `annotation` | 新 annotation | 当前 annotation / 新 annotation |
| `create_card` | `none` | `null` | `card` | `{id?, label, ontology, annotation}` | `null` / 新卡片对象 |
| `create_proposition` | `none` | `null` | `proposition` | `{id?, title, content, related_knowledge}` | `null` / 新命题对象 |
| `update_proposition_title` | `proposition` | 已有命题 id | `title` | 新标题 | 当前标题 / 新标题 |
| `update_proposition_content` | `proposition` | 已有命题 id | `content` | 新内容 | 当前内容 / 新内容 |
| `add_proposition_evidence` | `proposition` | 已有命题 id | `evidence` | 与顶层 `evidence` 相同 | 当前证据条数 / +1 |
| `update_proposition_related_knowledge` | `proposition` | 已有命题 id | `related_knowledge` | ≥2 张已有卡片 id | 当前列表 / 新列表 |

### 9.2 约束

- `evidence` 每条必填：`paper_id` 必须是本次 `push.paper_ids` 之一；`page` 是 ≥1 的整数，摘要引文可为 `null`；`quote` 是 8–500 字的原文片段。证据必须可追溯到该论文，不得编造。
- `before` 必须与 writer task 快照一致（防陈旧 diff）；`after` 必须等于 `diff.value`（或按操作表推导），且不得与 `before` 相同。
- `create_proposition.related_knowledge` 至少 2 张**已存在**卡片；同一次推送新建的卡片不能立刻被新命题引用。
- `proposal_id` 形如 `p_<push_id>_<NN>`；同一 push 内唯一；`status` 只能是 `draft`。
- writer **不写 archive**；同意后由 archive 按操作表落盘（`archive.cli apply-proposal` / 队列的 `apply-group`）。
- v1 迁移来的旧提议标 `status: historical`，不补问；archive 仍能识别旧 `kind`，但新 writer 只产出上表操作。

## 10. publisher 内部

`messages.jsonl`：回调路由表。

```json
{ "message_id": "om_xxx", "kind": "push_file | rating | update", "push_id": "…", "proposal_ids": ["…"], "queue_item_id": "q_…", "target": "ou_xxx" }
```

`decisions.jsonl`：

```json
{ "item_id": "q_…", "push_id": "…", "proposal_ids": ["…"], "decision": "agree_all | reject_all", "operator_id": "ou_…", "created_at": "…" }
```

## 11. 统一问题队列

状态机、边界用例与恢复策略见 [`docs/specs/unified-question-queue.md`](../docs/specs/unified-question-queue.md)；实现在 `question_queue/`。

```bash
python -m question_queue.cli status
python -m question_queue.cli enqueue --push archive/pushes/<push_id>.json
python -m question_queue.cli next
python -m question_queue.cli answer --item <item_id> --verdict great
python -m question_queue.cli answer --item <item_id> --decision agree_all
python -m question_queue.cli retry --item <item_id>
python -m question_queue.cli request-push --source manual
python -m question_queue.cli try-start
```

`publisher send` 会把 push 入队并只发送当前 active 题；回调经 `messages.jsonl` 的 `queue_item_id` 路由回队列。同意更新时 archive 以 `group_id=<item_id>` 原子应用并幂等；拒绝只写 `decisions.jsonl`。
