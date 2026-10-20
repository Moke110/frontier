# ADR 0001：知识卡片取代 checkpoint / kg node，命题连接卡片

- 日期：2026-10-20
- 状态：已接受
- 相关票：[知识卡片/命题数据契约与旧数据迁移](https://github.com/Moke110/frontier/issues/9)

## 背景

v1 里同一个知识单元有三种表示：

1. `frontier.yaml` 的 checkpoint（人写 ontology / annotation）；
2. `archive/kg/nodes/<node_id>.json` 的知识图节点（summary / aliases / 边）；
3. 命题里的 `node_ids`。

三者靠 `kg_node_id` 互相指，但没有单一权威；检索读 yaml，写作读 kg node，命题又用另一套字段。v2 要把检索、写作、更新都收敛到同一个知识单元。

## 决策

1. **知识卡片是唯一知识单元**，存 `archive/cards/<card_id>.json`，字段固定为
   `id / label / ontology / annotation`（另加 `schema_version` 与时间戳）。卡片不存任何边。
2. **命题是唯一连接处**：`id / title / content / history / related_knowledge`，
   `related_knowledge` 至少 2 张已存在卡片；证据与变更都进 `history`。
3. **`frontier.yaml`、`archive/kg/` 退役**。检索计划直接读卡片；评分状态
   `state/checkpoints.yaml` 保留文件名，但键改为卡片 id。
4. **id 用语义 slug**：`card_<slug>`、`prop_<slug>`，只允许 `[a-z0-9_]`；
   ASCII label/title 自动生成，冲突追加 `_2`、`_3`；非 ASCII 必须显式给 id。
5. **迁移一次性完成并备份**：`archive.cli migrate-v2` 可 `--dry-run`、可重复执行
   （第二次返回 `already-migrated`）、可用 `migrate-v2 --rollback <backup>` 回滚。
6. **旧提议只作历史**：v1 push 里的 proposals 标 `status: historical`，不补问、不自动应用。

## 迁移映射（v1 → v2）

| v1 | v2 |
|---|---|
| checkpoint `hmbs` / `virtual-cell` | `card_hmbs` / `card_virtual_cell`（保留手写 ontology/annotation） |
| 其余 kg node（aip / heme / perturbation） | `card_aip` / `card_heme_biosynthesis` / `card_perturbation_prediction`（aliases → ontology，summary → annotation） |
| kg edges | 丢弃（卡片无链接） |
| 命题 `node_ids` | `related_knowledge`（映射到卡片 id） |
| 命题 `text` / `evidence` | `content` / `history[].evidence` |
| paper / push 的 `checkpoint_id` | 值改为卡片 id；push 的 `kg_node_id` 删除 |
| `ratings.jsonl` | 增加 `card_id`（由 push 推导） |

`paper_id`、`push_id`、`rating_id` 是来源派生的稳定 id，不重写。

## 后果

- 检索只依赖 `archive/cards/`，`frontier validate` 检查四字段完整性。
- writer/editor 的任务包从 `kg_node` 改成 `card`；v2 的正式提议契约由后续票重写，
  本 ADR 只保证 archive 能按新存储应用旧形状的提议。
- 迁移备份在 `archive/legacy/v1-<ts>/`，含 `manifest.json` 与 `report.json`；
  回滚只恢复备份过的文件并删除 `archive/cards/`。
