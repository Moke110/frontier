# frontier 原型 · Agent 任务契约

本项目的 editor 与 writer **不内置模型调用**。它们把「需要判断」的部分打包成任务文件，由宿主 agent 读取、推理、写回；脚本只负责取数、校验与落盘。这样换 agent 或换模型不需要改代码。

```
editor task  →  agent 排序  →  editor check  →  writer task  →  agent 写作  →  writer check
```

任务文件里已经包含 agent 需要的全部上下文（checkpoint 的 ontology / annotation / 知识卡 / 命题 / 历史篇数），agent 也可以随时用 `archive.cli` 自行读取更多细节。

## 1. editor task → selection

`python -m editor.cli task --candidates candidates.jsonl --out editor-task.json`

```json
{
  "schema_version": 1,
  "kind": "editor-task",
  "date": "2026-10-20",
  "instructions": "……排序标准、输出要求……",
  "limits": { "limit": 5, "per_checkpoint": 2 },
  "preferences": {
    "checkpoints": { "hmbs": { "n": 3, "mean": 0.72 } },
    "sources": { "europepmc": { "n": 2, "mean": 0.6 } }
  },
  "checkpoints": {
    "hmbs": {
      "label": "HMBS / 羟甲基胆素合酶",
      "annotation": "……判据……",
      "ontology": ["HMBS", "PBGD"],
      "weight": 6,
      "kg_node": { "node_id": "kg_hmbs", "summary": "……", "aliases": ["PBGD"] },
      "propositions": [ { "prop_id": "prop_…", "text": "……" } ],
      "archived_count": 12
    }
  },
  "candidates": [
    {
      "paper_id": "europepmc_42900001",
      "checkpoint_id": "hmbs",
      "source": "europepmc",
      "title": "……",
      "abstract": "……",
      "published": "2026-10-16",
      "is_preprint": false,
      "url": "https://…",
      "retrieval": { "query_id": "q_hmbs_europepmc", "rank_hint": 1 }
    }
  ]
}
```

Agent 写回 `selection.json`（形状见 `contracts/README.md` §4）：每条必须含 `checkpoint_id`、`paper.paper_id`、`score`（0–1）、`rationale`；`breakdown` 可选。不得编造候选之外的文章，不得超 `limits`。

校验：

```bash
python -m editor.cli check --task editor-task.json --selection selection.json
```

退出码 1 + `errors[]` 表示不合法；agent 应修正后重试，而不是绕过校验。

## 2. writer task → push

`python -m writer.cli task --selection selection.json --out writer-task.json`

```json
{
  "schema_version": 1,
  "kind": "writer-task",
  "format": "pdf",
  "date": "2026-10-20",
  "instructions": "……七段结构、HTML 片段、图片、引用、提议规则……",
  "archive_cli": "python -m archive.cli",
  "figure_command": "python -m writer.cli figures --selection <selection.json> --out <outbox>",
  "render_command": "python -m writer.cli render --push outbox/pushes/<push_id>.json --out <pdf>",
  "items": [
    {
      "checkpoint_id": "hmbs",
      "paper": { "paper_id": "…", "title": "…", "abstract": "…" },
      "context": {
        "node": { "node_id": "kg_hmbs", "summary": "…", "aliases": ["PBGD"] },
        "propositions": [ { "prop_id": "prop_hmbs_aip", "text": "…", "evidence": [] } ],
        "archived_count": 2,
        "recent_papers": [ { "paper_id": "…", "title": "…", "published": "…" } ]
      }
    }
  ],
  "proposal_kinds": {
    "add_evidence": "给命题补一条证据 …",
    "add_alias": "给知识卡补别名 …",
    "add_proposition": "新建命题 …",
    "update_summary": "改写摘要 …"
  },
  "output": {
    "dir": "outbox/pushes",
    "filename": "<push_id>.json",
    "schema": "contracts/README.md §5"
  }
}
```

Agent 先取图：

```bash
python -m writer.cli figures --selection selection.json --out outbox
# -> outbox/figures.json + outbox/pushes/assets/<push_id>/fig-*
```

然后为每个 item 写一个 push 文件，文件名 = `push_id`：

- `format: "pdf"`；
- `push_id = "<date>_<checkpoint_id>_<NN>"`，NN 从 01 递增（可用 task 里的 `suggested_push_id`）；
- `paper_ids` 必须包含该 item 的 `paper_id`，`paper` 里保留作者/期刊/日期/URL；
- `sections` 七个键 `takeaway / background / methods / results / why / limits / sources` 都非空；
- `body_html` 是正文 HTML 片段（不是整页），图片用 `<figure data-asset="fig-1"></figure>` 占位；
- `assets` 至少一项，来自 `figures.json`，`caption` 非空且 `source` 为 `paper | generated`；
- `why` 必须引用 `context`（知识卡摘要、命题、归档篇数至少其一）；
- `proposals` 只允许四种 kind，`status` 必须是 `draft`；
- `add_evidence` 的 `target_id` 必须是 context 里已有的命题；`add_alias` / `update_summary` 的目标必须存在；`add_proposition` 的 `node_ids` 必须都是已知节点。

校验：

```bash
python -m writer.cli check --task writer-task.json --outbox outbox
```

渲染：

```bash
python -m writer.cli render --push outbox/pushes/<push_id>.json --out outbox/<push_id>.pdf
```

渲染器负责固定模板、中文字体、页眉页脚、图注与「原文图 / 生成图」标记；agent 不写 CSS。

校验通过后再入库：

```bash
python -m archive.cli add-push --file outbox/pushes/<push_id>.json
```

## 3. 知识库读写边界

| 动作 | 谁做 | 怎么做 |
|---|---|---|
| 读知识卡 / 命题 / 上下文 | agent | 任务文件已附带；需要更多时调 `archive.cli context / kg-get / prop-list` |
| 写知识卡 / 命题 | **只有 archive** | `archive.cli apply-proposal` 或 `apply-decisions`（用户审批后） |
| 提出更新 | agent（writer） | 写进 push 的 `proposals`，状态 `draft` |
| 让用户同意 | publisher | 评分后发审批卡，落 `decisions.jsonl` |

agent **永远不直接编辑** `$KL_HOME/archive/**` 下的 JSON；所有知识库写入都必须经过 archive CLI，保证可追溯、可回滚。

## 4. 为什么任务文件里不放提示词以外的状态

任务文件是**一次性的输入快照**：agent 失败可重跑同一条 `task` 命令；agent 的输出必须通过 `check` 才能进入下一步。这样 editor/writer 可以被任何 agent 实现，脚本仍然可测、可复现。

确定性启发式实现（`editor rank` / `writer write`）保留作为离线 fallback 和测试基准，但正式流程以 agent 任务模式为准。
