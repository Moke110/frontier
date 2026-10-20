# 02 frontier：检索式产出原型

Type: prototype ｜ Status: resolved ｜ Blocked by: —

## Question

frontier 维护 checkpoint 列表（`frontier.yaml`）与机器状态（`state/checkpoints.yaml`），负责把每个 enabled checkpoint 翻译成可执行的检索式：

- checkpoint = `id + label + kg_node_id + ontology + annotation + related`，其中 `kg_node_id` 链接到 archive 的知识图节点（即知识卡片）。
- 召回：`ontology` 同义词 OR；精度：`annotation` 随检索式一起下传，供 editor/writer 使用。
- 按源生成查询：arXiv（`submittedDate`，不带连字符）与 Europe PMC（`TITLE_ABS:` + `FIRST_PDATE:`）。
- 记录评分反馈：更新 `hit_rate` / `weight` / `last_checked`，权重参与 editor 排序。

需要：`validate`（checkpoint → 知识图节点存在性）、`plan`（输出 JSON 检索计划）、`record`（记录一条评分）。

## Answer

已实现 `frontier/model.py` + `frontier/cli.py`：

- `validate`：逐个 checkpoint 检查 `kg_node_id` 对应的 `archive/kg/nodes/<id>.json` 是否存在。
- `plan`：按 enabled checkpoint 生成两类检索式 —— arXiv `(abs:"…" OR …) AND submittedDate:[YYYYMMDD0000 TO YYYYMMDD2359]`（不带连字符）、Europe PMC `(TITLE_ABS:"…" OR …) AND (FIRST_PDATE:[start TO end])`；`annotation` 原样下传。
- `record`：更新 `hit_rate` 与 `ema`，`weight = clamp(1,10, round(1+9*ema))`，`last_checked` 写今天。
- `show`：汇总 checkpoint 状态。测试见 `tests/test_frontier.py`。
