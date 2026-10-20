# frontier 原型 · 文件契约

六个模块之间**不 import 彼此**，只通过下面这些文件交换数据。任何模块都可以被替换，只要仍读写同样的形状。
所有 JSON 顶层带 `schema_version: 1`，时间统一 ISO-8601（本地时区，秒级，如 `2026-10-20T09:30:00+08:00`）。

> editor / writer 的 agent 任务包（`editor-task.json`、`writer-task.json`）与校验规则见 [`agent-tasks.md`](agent-tasks.md)。

数据根由环境变量 `KL_HOME` 指定（默认 `./data`）：

```
$KL_HOME/
├── frontier.yaml                 # 人写：checkpoint 词汇表
├── state/
│   ├── checkpoints.yaml          # 机器写：权重 / 命中率 / 最后检索
│   └── editor.yaml               # 机器写：评分学出的偏好模型
├── archive/                      # 只有 archive 模块写
│   ├── raw/<paper_id>.json       # ① 原文（元数据）
│   ├── raw/text/<paper_id>.txt   # ① 原文（正文/摘要文本）
│   ├── pushes/<push_id>.json     # ② 推送
│   ├── kg/nodes/<node_id>.json   # ③ 知识图节点（= 知识卡片）
│   ├── kg/edges.jsonl            # ③ 知识图边
│   ├── propositions/<id>.json    # ④ 命题
│   ├── index/*.jsonl             # 各层索引（可 reindex 重建）
│   └── applied/<proposal_id>.json# 已应用的更新记录
├── ratings.jsonl                 # publisher 写，editor/frontier 读
└── publisher/
    ├── messages.jsonl            # message_id → push/proposal，用于回调路由
    ├── pending/<proposal_id>.json# 待审批提议副本（archive 读它来应用）
    ├── decisions.jsonl           # 用户同意/拒绝
    └── outbox/                   # 离线模式生成的卡片 JSON（调试用）
```

---

## 1. checkpoint 与状态

`frontier.yaml`（人写、低频；agent 只能提议，不能改）：

```yaml
schema_version: 1
checkpoints:
  - id: hmbs
    label: HMBS / 羟甲基胆素合酶
    kg_node_id: kg_hmbs          # ← 链接到 archive 的知识图节点（知识卡片）
    ontology: [HMBS, PBGD, hydroxymethylbilane synthase]
    annotation: |
      血红素合成第三步的胞质酶……
      ⛔ 不含：……
    related: [aip]               # 同属一个命题的其他 checkpoint
    enabled: true
```

`state/checkpoints.yaml`（机器写、高频）：

```yaml
schema_version: 1
checkpoints:
  hmbs:
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
  "checkpoint_id": "hmbs",
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

## 3. 候选 `candidates.jsonl`（retriever → editor）

每行是一篇原文记录，外加：

```json
{ "…paper 字段…": "…", "retrieval": { "query_id": "…", "checkpoint_id": "hmbs", "rank_hint": 1 } }
```

## 4. 选择 `selection.json`（editor → writer）

```json
{
  "schema_version": 1,
  "date": "2026-10-20",
  "selected": [
    {
      "checkpoint_id": "hmbs",
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
  "push_id": "2026-10-20_hmbs_01",
  "date": "2026-10-20",
  "checkpoint_id": "hmbs",
  "paper_ids": ["europepmc_42830441"],
  "title": "HMBS：…",
  "body_md": "…四段结构…",
  "sections": { "did": "…", "found": "…", "why": "…", "keep": "…" },
  "context": { "kg_node_id": "kg_hmbs", "propositions": ["prop_…"], "archived_count": 12 },
  "proposals": [ { "…proposal…": "…" } ],
  "status": "written",
  "created_at": "2026-10-20T09:10:00+08:00"
}
```

## 6. 知识图

节点（知识卡片）`archive/kg/nodes/<node_id>.json`：

```json
{
  "schema_version": 1,
  "node_id": "kg_hmbs",
  "label": "HMBS",
  "type": "concept",
  "summary": "血红素合成第三步的胞质酶；缺失导致急性间歇性卟啉症。",
  "aliases": ["PBGD", "hydroxymethylbilane synthase"],
  "checkpoint_ids": ["hmbs"],
  "updated_at": "2026-10-20T09:00:00+08:00"
}
```

边 `archive/kg/edges.jsonl`：

```json
{ "schema_version": 1, "from": "kg_hmbs", "to": "kg_aip", "type": "related_to", "note": "…", "created_at": "…" }
```

`type` ∈ `related_to | supports | contradicts`。

## 7. 命题 `archive/propositions/<prop_id>.json`

```json
{
  "schema_version": 1,
  "prop_id": "prop_hmbs_aip",
  "text": "HMBS 功能缺失导致急性间歇性卟啉症。",
  "node_ids": ["kg_hmbs", "kg_aip"],
  "status": "active",
  "evidence": [
    { "paper_id": "europepmc_42830441", "push_id": "2026-10-20_hmbs_01", "note": "…" }
  ],
  "updated_at": "2026-10-20T09:00:00+08:00"
}
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

嵌在 push 里，也单独复制到 `publisher/pending/` 等审批。

```json
{
  "schema_version": 1,
  "proposal_id": "p_2026-10-20_hmbs_01_1",
  "push_id": "2026-10-20_hmbs_01",
  "kind": "add_evidence | add_alias | add_proposition | update_summary",
  "target_type": "proposition | kg_node | none",
  "target_id": "prop_hmbs_aip",
  "diff": { "op": "add", "path": "evidence", "value": { "paper_id": "…", "note": "…" } },
  "before": "…",
  "after": "…",
  "rationale": "…",
  "confidence": 0.7,
  "status": "draft | pending_approval | approved | rejected"
}
```

## 10. publisher 内部

`messages.jsonl`：回调路由表。

```json
{ "message_id": "om_xxx", "kind": "rating | approval", "push_id": "…", "proposal_ids": ["…"], "sent_at": "…" }
```

`decisions.jsonl`：

```json
{ "proposal_id": "p_…", "decision": "approve | reject", "operator_id": "ou_…", "message_id": "om_…", "created_at": "…" }
```
