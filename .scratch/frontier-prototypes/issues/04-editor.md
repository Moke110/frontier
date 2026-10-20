# 04 editor：排序与评分调权原型

Type: prototype ｜ Status: resolved ｜ Blocked by: —

## Question

editor 把 retriever 的候选排成一个可解释的序列，并按用户评分**调整排序方式**：

- 相关性（ontology 词命中 + 覆盖率）、时效性、checkpoint 权重、用户偏好四项加权。
- `fit` 从 ratings + pushes 学出「每个 checkpoint / 每个来源的历史偏好」（Beta 平滑均值），写入 `state/editor.yaml`。
- `rank` 输出 top N 与逐项 score breakdown，冷启动（无评分）时偏好项回落到 0.5。
- 排序必须确定性，便于测试与复现。

## Answer

已实现 `editor/model.py` + `editor/cli.py`：

- `fit`：把 ratings 通过 `push_id → push.checkpoint_id`、`paper_id → raw.source` 归因，用 Beta 平滑（prior n=2, mean=0.5）算出每个 checkpoint / 来源的偏好，写 `state/editor.yaml`。
- `rank`：四项加权 —— 相关性 0.40（ontology 命中数 + 覆盖率）、时效 0.15（14 天半衰）、偏好 0.30（checkpoint 0.6 + 来源 0.4）、checkpoint 权重 0.15；输出 `score` 与 `breakdown` + 一句 `rationale`。
- 支持 `--per-checkpoint` 控制单 checkpoint 上限；排序确定性（同分按 paper_id）。
- 测试验证了偏好可以把 HMBS 论文顶到第一（同一批候选，仅改变模型）。
