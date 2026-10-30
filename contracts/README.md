# frontier 原型 · 文件契约

各模块之间**不 import 彼此**，只通过下面这些文件交换数据。任何模块都可以被替换，只要仍读写同样的形状。
所有 JSON 顶层带 `schema_version: 1`，时间统一 ISO-8601（本地时区，秒级，如 `2026-10-20T09:30:00+08:00`）。

> editor / writer 的 agent 任务包（`editor-task.json`、`writer-task.json`）与校验规则见 [`agent-tasks.md`](agent-tasks.md)。

两个顶层位置由统一解析（`hostrun.layout`）决定：**代码目录** `--code`（默认仓库根，运行时区为 `<code>/.frontier/`）与**资料目录** `--archive`（默认 `<code>/../frontier-archive`）。资料目录只放 `originals/`（原文）与 `pushes/`（推送件）；运行状态一律在运行时区。子进程通过 `FRONTIER_CODE` / `FRONTIER_ARCHIVE` / `FRONTIER_RUNTIME` 继承同一次解析；旧 `--home` 已退役，传入即报错并提示 `install migrate`：

```
<code>/.frontier/                 # 运行时区（不放进资料目录）
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
├── cache/                        # library 按需下载，可随时删（ADR 0003）
│   └── raw/<paper_id>.pdf        # 以 Base md5 判命中；分片原文在这里拼回整份
├── ratings.jsonl                 # publisher 写，editor/frontier 读
├── knowledge/                    # Bitable 镜像（Phase 3a）
│   ├── base.json                 # base_token / base_url / 知识五表 id；library.setup 追加原文/推送日志/决定/配置四表 id
│   └── state.json                # 文本列基线，用于识别手工编辑
├── queue/                        # 统一问题队列（contracts/question-queue.md）
│   ├── state.json                # 队列表 + 单 active
│   ├── events.jsonl              # 只追加的审计/重建日志
│   ├── request.json              # 合并后的待推请求
│   ├── lock                      # 队列状态排他锁
│   └── start.lock                # 检索启动租约（预留）
├── library/                      # 云盘库的本地状态（全部可删）
│   ├── cache/config.json         # 「配置」表缓存（10 分钟）
│   ├── alerts/<ts>.json          # 待发送的配额提醒（publisher alerts 发送后移入 sent/）
│   ├── reports/*.json            # 对账 / 回填报告
│   └── state.json                # 同类提醒 24h 冷却
└── publisher/
    ├── messages.jsonl            # message_id → push/queue item，用于回调路由
    ├── send-attempts.jsonl       # 每次真实发送的尝试（sending/sent/unknown/not_sent）；
    │                             #   unknown 时拒绝盲目重发，用 publisher.cli resolve-send 对账
    ├── pending/<proposal_id>.json# 旧审批链路的待审批副本（v2 不再新增）
    ├── decisions.jsonl           # 用户同意/拒绝（旧审批链路）
    ├── decision_rows.jsonl       # 提议级决定暂存（采纳/拒绝 + 评语），library decisions sync 写入「决定」表
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

### 2.2 初始构建导入（`initial_build`）

`python -m initial_build.cli apply --draft drafts/initial-build/<theme> [--dry-run]`

- draft 目录含 `cards.jsonl`、`propositions.jsonl`、`sources.jsonl`（与 #12 样张一致）。
- 写库前先做完整校验：卡片四字段 / `ontology` ≥3 / `annotation` 含 ⛔ 与 ⚠️；
  命题 `related_knowledge` ≥2 张已知卡、`history[0].action=created` 且有 rationale、
  每条证据 `paper_id/page/quote` 可在 `archive/raw/pages/` 锚点中定位。
- 单篇证据命题（证据不足 2 篇独立论文）不阻断整批：记入报告的 `held`，不写 archive，留作后续批次。
- 硬校验失败则整批不写；写库失败会回滚 `cards/` 与 `propositions/`。
- 幂等：内容相同的卡片/命题记 `skipped`；报告在 `archive/reports/initial-build-<theme>-<ts>.json`。



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

## 5.1 长文推送 `format: html`

正式流程使用长文 PDF；`format` 缺省或为 `card` 时仍按 §5 的四段卡片处理（离线 fallback）。

```json
{
  "schema_version": 1,
  "format": "html",
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
  "schema_version": 3,
  "id": "prop_hmbs_aip",
  "title": "HMBS 功能缺失导致 AIP",
  "review": "## 结论\n…\n## 支持证据\n…\n## 反证与边界\n…\n## 待验证\n…",
  "related_knowledge": ["card_hmbs", "card_aip"],
  "evidence": [
    {
      "id": "ev_hmbs_aip_01",
      "stance": "supports",
      "conclusion": "多项病例与酶学研究一致显示 HMBS 活性下降导致 AIP。",
      "papers": [
        {
          "paper_id": "europepmc_42888036",
          "push_id": "2026-10-16_card_hmbs_01",
          "page": 3,
          "quote": "原文引文",
          "added_at": "2026-10-16T09:00:00+08:00"
        }
      ],
      "created_at": "2026-10-16T09:00:00+08:00",
      "updated_at": "2026-10-16T09:00:00+08:00"
    }
  ],
  "changelog": [
    {
      "at": "2026-10-20T09:00:00+08:00",
      "action": "created",
      "field": "review",
      "before": null,
      "after": "…",
      "rationale": "初始构建",
      "source": { "kind": "initial-build | push | user | migration | cli", "id": "…" }
    }
  ],
  "evidence_updates_since_review": 0,
  "created_at": "2026-10-20T09:00:00+08:00",
  "updated_at": "2026-10-20T09:00:00+08:00"
}
```

约束：

- `related_knowledge` 至少 2 个**已存在**的卡片 id，不得重复。
- `review` 非空、≤2000 字；固定四节（结论 / 支持证据 / 反证与边界 / 待验证）。
- `evidence[]` 每条：`stance ∈ supports|contradicts`、`conclusion` 1–200 字、`papers[]` 至少一篇；
  每篇带 `paper_id / page / quote`，`quote` 8–500 字，`page` 为 ≥1 整数或 `null`（摘要）。
- 同一条 evidence 内只放方向一致的报道；不同 evidence 可以互相矛盾。
- `changelog` 非空，只记 title / review / related_knowledge 的变更；证据更新不进 changelog。
- 新建命题必须带 ≥2 条 evidence。
- 迁移：旧 `history[].evidence` 每个条目拆成一条 evidence，标 `migrated_from_v2`。

写入命令：

```bash
python -m archive.cli prop-put --file prop.json
python -m archive.cli prop-get prop_hmbs_aip
python -m archive.cli prop-list --card card_hmbs
python -m archive.cli migrate-v3 [--dry-run] [--rollback <backup>]
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

嵌在 push 里；v2 每篇推送最多 **2 个实体目标**（知识卡片 + 命题合计，新建也占名额），同一目标的多个操作在入队时合并成一个更新题（见 `contracts/question-queue.md`）。

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
| `create_proposition` | `none` | `null` | `proposition` | `{id?, title, review, related_knowledge, evidence[≥2]}` | `null` / 新命题对象 |
| `update_proposition_title` | `proposition` | 已有命题 id | `title` | 新标题 | 当前标题 / 新标题 |
| `update_proposition_review` | `proposition` | 已有命题 id | `review` | 新综述（20–2000 字） | 当前综述 / 新综述 |
| `add_proposition_evidence` | `proposition` | 已有命题 id | `evidence` | `{conclusion≤200, stance, papers[]}` | 当前证据条数 / +1 |
| `merge_proposition_evidence` | `proposition` | 已有命题 id | `evidence` | `{target_evidence_id, papers[], conclusion?}` | 目标条目当前报道数 / +新增报道数 |
| `update_proposition_related_knowledge` | `proposition` | 已有命题 id | `related_knowledge` | ≥2 张已有卡片 id | 当前列表 / 新列表 |

### 9.2 约束

- `evidence` 每条必填：`paper_id` 必须是本次 `push.paper_ids` 之一；`page` 是 ≥1 的整数，摘要引文可为 `null`；`quote` 是 8–500 字的原文片段。证据必须可追溯到该论文，不得编造。
- `before` 必须与 writer task 快照一致（防陈旧 diff）；`after` 必须等于 `diff.value`（或按操作表推导），且不得与 `before` 相同。
- 证据提议的 `papers[]` 每篇都要带 `paper_id / page / quote`；`paper_id` 必须是本次 push 的论文。
- `create_proposition.related_knowledge` 至少 2 张**已存在**卡片；同一次推送新建的卡片不能立刻被新命题引用。
- `create_proposition.evidence` 至少 2 条；每条 `conclusion ≤200` 字。
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

`send-attempts.jsonl`：真实发送先写 `sending`，成功后写 `sent`（带 `message_id`），异常/超时写 `unknown`；未决尝试存在时同一推送拒绝再次发送（`send_status_unknown`），必须先 `publisher.cli resolve-send --push <id> --message <message_id>`（已送达）或 `--not-sent`（确认未发出）对账。清理的 `sent` 证据要求 `messages.jsonl` 中该消息是本次推送的 `push_file` 且 `target` 为已核实收件人。

## 10.5 Bitable 镜像（Phase 3a）

```bash
python -m knowledge.cli sync        # 本地知识层 → Bitable（幂等 upsert + 关联）
python -m knowledge.cli pull        # Bitable 文本列 → 本地（补 changelog / 待修正）
python -m knowledge.cli compare     # 报告漂移；ok=false 时退出码 1
python -m knowledge.cli ledger      # 重建文本基线
```

- 双读期本地 `archive/` 仍是权威；Bitable 是镜像。
- `sync` 按业务 id 匹配，不做删除；Bitable 多出的记录由 `compare` 暴露。
- `pull` 只接受 title / review / annotation / conclusion；结构列（id、关联、日期、计数）不回拉。
- `sync` 成功后刷新 `knowledge/state.json`；`pull` 结束后同样刷新。

## 10.6 原文/推送库（Phase 4，见 `contracts/lark-storage.md`）

自 ADR 0003 起，云盘 + Base 是原文与推送的唯一真相；`archive/raw/**`、`archive/pushes/**` 降级为本地缓存与物化视图：

```bash
python -m library.cli put-source --file <pdf> --paper <paper_id>
python -m library.cli put-push --push <push_id> --html <path>   # publisher 发送成功后调用
python -m library.cli resolve --paper <paper_id>                # 缓存路径，按 md5 校验
python -m library.cli quota --check
python -m library.cli reconcile
python -m library.cli evict --candidates
python -m library.cli evict --execute          # 先备份+校验 md5，再删
python -m library.cli restore --paper <id>
python -m library.cli decisions sync           # 提议级决定写入「决定」表
```

全局 `--offline` 用 `<运行时区>/library/offline-*.json` 的夹具跑完整流程，不碰真实租户。

- 「原文」「推送日志」「决定」「配置」四张表的字段与状态机见 spec §3；`papers` 表语义是「报道」，不是论文。
- 配额默认 5GB（Base「配置」表可改）；100% 时只拦新原文，不拦推送；永不自动删除。
- 删除顺序固定：备份并校验 md5 → 状态改 `已离线归档` → 删云盘文件。

## 11. 统一问题队列

状态机、边界用例与恢复策略见 [`contracts/question-queue.md`](question-queue.md)；实现在 `question_queue/`。

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

## 12. 宿主运行（hostrun）

由宿主 agent 驱动的安装、租约与有界运行。**不写持久环境变量、不创建服务或系统定时任务**；唯一允许的常驻组件是用户手动启停的监听进程（[ADR 0008](../docs/adr/0008-listener-process.md)），它不是一个 Windows 服务、不登录自启、也不替代执行端租约。位置只由统一解析给出：`--code`（默认仓库根）+ `--archive`（默认 `<code>/../frontier-archive`），运行时区固定为 `<code>/.frontier/`。工作区默认含 `frontier/`（代码目录）与 `frontier-archive/`（资料目录）。uv 管理的私有环境与解释器记录在安装记录里（迁移后在 `<code>/.frontier/.venv`）；代码目录只保留代码，uv 优先从工作区外解析。

```bash
# 工作区、私有 uv/解释器、frontier-run 入口指针
python -m hostrun.cli install workspace --root <workspace>
python -m hostrun.cli --code <code> --archive <archive> install toolchain --root <workspace>
python -m hostrun.cli --code <code> --archive <archive> install skill --root <workspace> --target <host-skill-dir>/frontier-run
python -m hostrun.cli install check|report|status|record|locate

# 飞书 CLI：可执行 / 身份 / 授权范围 / 资源读取分项
python -m hostrun.cli lark discover|install|login|status --root <workspace>

# 设施：Base 本身、全部表、原文库与推送库目录（稳定 ID）
python -m hostrun.cli facilities plan|create|attach|status|rename

# 关键词临时闭环 → 精确清理 → 正式知识
# smoke record 的证据闸门：retrieved --plan（可选 --candidates 须一致）、
# written --paper（可重复）、rendered --push + --html（校验渲染契约）、
# sent --push --message --question；verify --field name=value（可重复）
python -m hostrun.cli smoke start|plan|brief|status|record|verify|fail
python -m hostrun.cli cleanup plan|run|status
python -m hostrun.cli init intake|propose|review|confirm|apply|adopt-existing|retrieve|status

# 两个瞬时宿主任务与真实触发
python -m hostrun.cli schedules plan|confirm|status|pause|resume|trigger

# 监听进程：用户手动启停；巡检与在线状态
python -m hostrun.cli listener start|stop|status|serve|install|health
python -m hostrun.cli run --intent listener-check

# 运行、反馈与恢复
python -m hostrun.cli feedback setup|sync|status|process|rebuild|submit|correct
python -m hostrun.cli run --intent daily|feedback|maintenance [--finish ok|error]
python -m hostrun.cli audit run --baseline <manifest>|streak
python -m hostrun.cli executor status|handover
python -m hostrun.cli status
```

```
<workspace>/
├── .frontier/install.json        # 代码 / 资料目录 / uv / 私有环境 / 解释器 / 技能绝对路径（技能移动后仍可定位）
├── frontier/                     # 代码目录；运行时区在 frontier/.frontier/（下列条目）
└── frontier-archive/             # 资料目录：只有 originals/ 与 pushes/
    ├── originals/                # 原文
    └── pushes/                   # 推送件
```

运行时区（`<code>/.frontier/`）内的安装与运行状态：

```
<code>/.frontier/
    ├── bin/                      # 缺失时的私有 uv（优先从工作区外解析；不改 PATH）；
    │                             #   frontier-listener.cmd / frontier-listener-stop.cmd（用户手动启停）
    ├── .venv/                    # uv 管理的私有环境与解释器（绝对路径同时写入指针记录与安装配置）
    ├── install/
    │   ├── config.json           # 宿主、私有路径、时区、权限与任务（凭据字段一律 ***）
    │   ├── state.json            # 分步状态：host/workspace/dependencies/skill/lark_cli/identity/
    │   │                         #   permissions/facilities/knowledge/schedules/scheduled_run/
    │   │                         #   listener/listener_health（巡检证据单独记为 listener_health）；
    │   │                         #   test_loop/cleanup 已退役，旧记录仍可读但不参与门禁
    │   ├── facilities.json       # Base/表/目录的稳定 ID 与已确认展示名
    │   ├── recipient.json        # /frontier-init 传输测试核实后的收件人（schema_version/owner/verified_at/source）；
    │   │                         #   用户标识原文只在这里与测试记录中，不进入安装报告
    │   ├── smoke.json            # 测试 ID、owner 与 owner_verified、步骤、副作用归属
    │   │                         #   （artifacts.candidates/plan/paper_ids/push_html）、
    │   │                         #   verify 的 steps.verified.checks；清理后只留最小验收状态
    │   └── initial/              # 文献元数据、候选卡片、确认哈希、写入报告、标准检索计划
    ├── listener/                 # listener.lock（单实例）/ heartbeat.json（每 60s 重写）/
    │                             #   listener.log（满 1 MB 滚动到 listener.log.1）/ stop（停止哨兵）/
    │                             #   derived.lock（派生运行单飞行）
    ├── executor/                 # lease.json + events.jsonl（时间租约，不是 pid）
    ├── hostrun/runs.jsonl        # 意图、动作、是否安静；scheduled/task 仅由宿主任务写入，
    │                             #   derived 标记监听进程派生的有界运行
    └── library/                  # maintenance/<date>.json、audit/<date>.json
```

约定：

- `install report` 的 `working` / `blocked` / `untested` / `pending` 分项是验收依据；缺能力标 `blocked`，没测过标 `untested`，不得写成通过。
- 工作区与私有环境：已有副本有未提交改动、origin 不符或不是 git 仓库时阻塞，不拉取、不覆盖；重跑复用已验证组件。依赖步骤只认**记录的解释器**：未记录、不是绝对路径、文件不存在或位于代码目录内时标 `blocked`，并给出可照做的 `install toolchain ... --clear` 修复命令（含先切换到代码目录）；不回退到当前运行进程的解释器。`--clear` 才重建运行时区环境，重复运行复用现有环境。
- 飞书 CLI 与权限：可执行、登录、授权范围、真实资源读取分别验证；记到文件系统的绝对路径失效时 `blocked`，不静默回退到 PATH。`permissions=ok` 要求授权范围与**真实 Base + Drive 读取**均成功；`messages` 作为独立的 `untested` 子证据保留，不因登录成功或消息未测而伪造；配置中 `permissions.scope` 保存飞书 scope，宿主能力另记 `host_scope`，两者不互相覆盖。
- 设施：按用户确认的展示名创建；使用稳定 ID，改名不影响读写。`facilities create` 总是新建独立 Base，不按名称复用同名库；`facilities plan` / `create` 把同名 Base 作为 `existing_same_name`（`count`/`names`/`note`）提示报告，查找失败时只留该字段并保持 `count: null`，不冒充已执行的动作；接入已有库必须显式 `facilities attach`（只检查/补缺，不清空）。部分失败如实报告并可从已创建项续接。
- 临时闭环：临时卡片 ID 与推送/消息/文件/问题/论文 ID 全部归属测试。`frontier.cli validate --include-temporary` 用于在清理前校验临时卡片；普通 `validate`/`plan` 仍排除 `card_smoke_*`。`retrieved` 必须指向真实的 `--plan` 计划/候选文件并由文件得出候选数（可选 `--candidates` 必须一致）；`written` 至少一个 `--paper`；`rendered` 必须带 `--push` 与 `--html`，并按 `writer/render.py` 契约校验七段与 `原文图`/`生成图` 图注；`sent` 带推送、消息、问题 ID，且该消息必须在 `publisher/messages.jsonl` 中登记为本次推送的 `push_file`、`target` 等于测试记录中已核实的收件人（缺失为 `message_recipient_unverified`，不匹配为 `message_mismatch`，均不推进步骤）；`applied` 用 `--target`（被采纳目标 ID）与 `--applied-field`（每个被采纳字段）登记写入意图，省略时按临时卡片、只要求至少一个读回检查。`verify` 的逐字段读回累计在 `steps.verified.checks`，且必须覆盖每个已登记目标与字段才完整；覆盖不足返回 `verification_incomplete` 并保持 `test_loop` 未通过，字段不一致照常失败。成功必须包含完整读回核对，失败不开放正式初始化。
- 清理：只按测试 ID 与记录中的卡片/推送/问题/文件/消息/选中论文 ID 删除并逐范围读回确认；消息撤回后必须按记录的消息 ID 重新读取，仍可读或读取结果无法判定都算残留/失败，保持 `cleanup=blocked`，正式初始化闸门关闭。撤回/读回与云盘删除/核对只使用记录或显式给出的**绝对且存在的** `lark-cli`；没有可用绝对路径时该项记 `failed`，绝不回退到 PATH 的 `lark-cli`。结果在 `removed`（逐表明细）之外给出 `counts`：Base 记录、消息、云盘文件、本地文件、队列条目，并写入 `install` 的清理证据。
- 正式知识：**新建路径**仅在“测试通过 + 清理读回通过”后开放；`init propose` 需要可读 intake（可读输入、可读全文与用户要求），并快照既有卡片 ID（快照读取失败即拒绝，不写草案）；卡片须用户确认且确认绑定草稿哈希；`init apply` 拒绝更新草案前已存在的卡片 ID（没有覆盖开关），同步后归一化比较字段读回，不一致即 `base_readback_mismatch`。**已有库**由用户显式确认后走 `init adopt-existing` 导入现有卡片，不经过新建测试闸门、不重建也不清空；两条路径完成后都做一次标准检索，测试关键词不复用。
- `run` 的固定顺序：反馈 → 恢复未完成 → 维护（到期才做）→ 检索闸门。`feedback` 意图**从不**创建检索请求；维护在同一天第一次反馈轮询（或第一次运行）时执行，未答问题不阻止维护；错过的每日请求合并为一次。
- 只创建两个宿主任务：`frontier-daily`（用户时区 08:00，推送）与 `frontier-listener-check`（每日 09:00，监听巡检）。正式知识未就绪时 `confirm` 拒绝创建（包括暂停），不写 `schedules` 任务；就绪后 `confirm` 为每个任务生成 proof 并写入命令。运行日志中的 `scheduled=true`、`task=<id>`、`proof` 匹配、运行时间的 UTC 偏移与计划时区记录的 `utc_offset_seconds` 一致，且落在计划时间内（±5 分钟启动容差）的记录才能写 `scheduled_run`，手动运行、非到点运行、异时区时间与伪造时间不计。**监听巡检不写 `scheduled_run`**，它的证据是 `listener_health`（见下）。
- 监听进程：单一前台进程、用户手动启停，不装服务、不登录自启、不写注册表。事件面用 bot 身份消费 `im.message.receive_v1`，只接受已核实 owner 的单聊消息；命令白名单为 `推一篇` / `处理反馈` / `状态`，未知文本只回用法提示，群聊与他人消息忽略并记日志。
- 反馈轮询：监听进程每 5 分钟执行一次 `run --intent feedback`（机械、无模型）；**自动轮询与显式 `处理反馈` 都在后台 daemon 工作线程执行**（复用派生运行的 worker 机制），事件循环继续消费事件、写心跳、调度轮询并回复 `状态`；同一时刻只允许一个反馈轮询在飞行（在飞行时自动轮询跳过本轮，显式命令立即回复"正在处理反馈，稍后再试"）。显式命令两段回执：立即回执"已开始处理反馈"，工作线程结束后仅在有变化/失败/跳过时发送结果回执，无变化保持安静；自动轮询从不发消息。每次轮询取得的执行端租约覆盖**整个运行**（`listener.feedback_lease_minutes`，默认 45 分钟），不是轮询间隔，避免超过一个轮询间隔的运行被下一轮并发启动；执行端租约被占用时跳过本轮，不抢、不重试；worker 异常被捕获并记日志/回执，不向 `serve` 抛出；日志与心跳写入对主循环与工作线程安全（单写/加锁）。
- 派生运行：监听进程用记录的 `dsh` 绝对路径执行 `dsh --profile headless "<brief>"`（任务为**位置参数**，headless profile 没有 `--prompt`）拉起一次有界宿主运行；记录的可选 `listener.dsh_args`（例如 `--patch <overlay.yml>`，用于本机 headless profile 缺少模型凭据时启用账号授权路由）插在 profile 与任务之间，任务始终是最后一个参数。派生在后台 daemon 工作线程执行，事件消费、心跳与 `状态` 回复不被阻塞；同一时刻的第二个派生命令立即回复"正在运行"。护栏：单飞行锁、**先取执行端租约再准备（request_push/try_start）与派生，准备+派生在同一段连续租约内**（acquire 失败不产生任何队列/卡片副作用）、单次上限 20 分钟、失败不自动重试、写入 `runs.jsonl` 并标记 `derived`、在飞书回执（开始时立即回执"已开始"，结束时回执完成/失败）；派生等待子进程期间**持续续租**（`executor.heartbeat`，20 分钟窗口），准备+子进程等待超过初始窗口也不会让另一宿主中途接管；`install report` 有 `blocked` 项时拒绝派生并如实回复。派生 spawn 使用记录的仓库作为 cwd、环境含 `FRONTIER_CODE` / `FRONTIER_ARCHIVE` / `FRONTIER_RUNTIME`（保留其余环境），brief 前置仓库/运行时区/记录解释器与"必须加载 `frontier-run` 技能"的要求；argv 形状已由 2026-10-30 的真实命令验证。
- 监听巡检：读取心跳新鲜度（≤10 分钟）、进程存活与最近一次成功事件时间；事件时间以 `last_event_age_seconds` 出现在 `listener_health` 证据与 `listener status` 输出中，心跳新鲜但超过 `listener.event_stale_seconds`（默认 3600）无成功事件时只在 `problems` 给出诊断提示，**在线判定仍为"心跳新鲜 + 进程存活"**；判定不在线时用记录的启动命令拉起一次并在 30 秒后复查，恢复成功报告一次，仍失败报告具体缺项并停手。证据写入独立的 `listener_health` 步骤；到点容差（±5 分钟）只用于证明"调度器真实触发"，不用于巡检。
- 同一时刻只有一个执行端：另一宿主持有有效租约时返回 `executor_busy`；过期租约可被接管并在 `events.jsonl` 记 `taken_over`；换机必须 `handover`（旧端仍活跃时需 `--force` 并说明）。
- `feedback rebuild` 从「问题」表重建本地队列，已处理的决定不会被再次应用。
