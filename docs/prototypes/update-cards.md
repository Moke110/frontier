# 更新题飞书卡片样张

- 票：[更新题飞书卡片样张 #14](https://github.com/Moke110/frontier/issues/14)
- 实现：`publisher/update_cards.py` 的 `build_update_card(push, item, index, total)`
- 样张输入：`fixtures/update-cards/*.item.json`
- 样张输出：`fixtures/update-cards/*.card.json`
- 预览：`fixtures/update-cards/preview.md`（文字版）/ `preview.html`（近似视觉版，非飞书真实渲染）
- 重新生成：`python scripts/build_update_card_samples.py`
- 用户确认：2026-10-21 首版通过；2026-10-22 按「顶栏只写类型 + 进度、实体 id/title 进正文」改版。

## 1. 三张样张

| 样张 | 实体 | 展示内容 |
|---|---|---|
| `card-update` | 知识卡片 `card_hmbs` | `add_card_ontology` + `update_card_annotation`；只展示新增行；附来源、页码、引文 |
| `proposition-update` | 命题 `prop_hmbs_aip` | 标题改写、内容改写、补证据；内容用行级 diff；证据只出现一次 |
| `create-proposition` | 新建命题 | 标题、内容、`related_knowledge`（3 张卡）、来源证据 |
| `proposal-review` | 命题综述 | 证据计数、diff 行数、Base 链接；按钮「采纳此版 / 保持上一版」 |

卡片/证据卡标「第 N / M 题」，按钮固定为「同意全部 / 拒绝全部」；综述卡按钮为「采纳此版 / 保持上一版」。每张只处理一个实体。

## 2. 版式决定

- **顶栏标题**：`知识卡片更新 · 第 2 / 4 题` / `命题证据更新 · 第 2 / 4 题`；**没有副标题**。
- **正文第一行**：实体 id + label/title，例如 ``**`card_hmbs`** · HMBS``；新建实体写 `**新建知识卡片** · label`。
- **来源**：论文标题 + 期刊/日期，放在实体行之后。
- **变更区**：最多 3 条变更，超出显示「还有 N 条变更」。长文本只显示行级新增/删除，不整段重复。
- **证据区**：最多 2 条，格式为「引文 + 《论文》· 第 N 页」；`add_proposition_evidence` 的引文已在变更区，不再重复。
- **理由**：只显示置信度最高的那一条理由 + 置信度，控制信息密度。
- **按钮**：同意左（蓝）/ 拒绝右（红），callback value 带 `queue_item_id`、`proposal_ids`、`decision`。
- **页脚**：说明同意立即写入、拒绝保持原样、答完才发下一题。

## 3. 综述卡（Phase 2b）

- 顶栏：`命题综述更新 · 第 N / M 题`，无副标题。
- 正文第一行：`prop_xxx · 标题`。
- 随后是「基于 N 条证据（支持 X / 反证 Y）」、diff 行数、Base 记录链接。
- 按钮：「采纳此版」/「保持上一版」。
- 完整综述与证据附录在 HTML 文件里，不在卡片里展开。
