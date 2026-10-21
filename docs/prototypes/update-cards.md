# 更新题飞书卡片样张

- 票：[更新题飞书卡片样张 #14](https://github.com/Moke110/frontier/issues/14)
- 实现：`publisher/update_cards.py` 的 `build_update_card(push, item, index, total)`
- 样张输入：`fixtures/update-cards/*.item.json`
- 样张输出：`fixtures/update-cards/*.card.json`
- 预览：`fixtures/update-cards/preview.md`（文字版）/ `preview.html`（近似视觉版，非飞书真实渲染）
- 重新生成：`python scripts/build_update_card_samples.py`

## 1. 三张样张

| 样张 | 实体 | 展示内容 |
|---|---|---|
| `card-update` | 知识卡片 `card_hmbs` | `add_card_ontology` + `update_card_annotation`；只展示新增行；附来源、页码、引文 |
| `proposition-update` | 命题 `prop_hmbs_aip` | 标题改写、内容改写、补证据；内容用行级 diff；证据只出现一次 |
| `create-proposition` | 新建命题 | 标题、内容、`related_knowledge`（3 张卡）、来源证据 |

三张卡都标「第 N / M 题」，按钮固定为「同意全部 / 拒绝全部」，每张只处理一个实体。

## 2. 版式决定

- **标题**：`知识更新 · 第 2 / 4 题`；**副标题**：实体类型 + id + 可选 label。
- **来源**：论文标题 + 期刊/日期，避免用户不知道这条更新来自哪篇。
- **变更区**：最多 3 条变更，超出显示「还有 N 条变更」。长文本只显示行级新增/删除，不整段重复。
- **证据区**：最多 2 条，格式为「引文 + 《论文》· 第 N 页」；`add_proposition_evidence` 的引文已在变更区，不再重复。
- **理由**：只显示置信度最高的那一条理由 + 置信度，控制信息密度。
- **按钮**：同意左（蓝）/ 拒绝右（红），callback value 带 `queue_item_id`、`proposal_ids`、`decision`。
- **页脚**：说明同意立即写入、拒绝保持原样、答完才发下一题。

## 3. 需要你确认的点

1. **密度**：annotation / content 只显示新增/删除行，是否足够？还是需要完整 before/after？
2. **证据**：每条证据保留引文 + 页码 + 论文标题；是否还要 URL 或「打开 PDF」按钮？
3. **理由**：只显示最高置信度的一条理由，是否需要每一条变更都带理由？
4. **按钮**：同意在左、拒绝在右；是否需要把「拒绝」改成更中性的「都不采纳」？
5. **标题**：`知识更新 · 第 N / M 题` 是否清楚，还是应带上推送日期/论文简称？

确认后，这份版式会作为 #16 队列逐题卡片的默认样式。
