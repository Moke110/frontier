# 01 archive：四层存储原型

Type: prototype ｜ Status: resolved ｜ Blocked by: —

## Question

把 archive 做成一个**只依赖文件系统**的存储模块，分四层独立可查：

1. **原文**（`raw/`）：检索回来的论文元数据 + 正文/摘要文本，去重键 `source:source_id`。
2. **推送**（`pushes/`）：已生成的卡片内容与归属（checkpoint、paper ids、正文、提议）。
3. **知识图**（`kg/`）：节点（知识卡片）+ 边，节点是 checkpoint 的链接目标。
4. **命题列表**（`propositions/`）：命题文本、关联节点、证据论文。

需要支持：写入/查询/上下文聚合（给 writer 用）、应用知识图/命题更新（审批通过后）、重建索引、导出统计。所有层带 `schema_version`，写入走 CLI，其他模块只读文件。

## Answer

已实现 `archive/store.py` + `archive/cli.py`：

- 四层目录与索引（`index/*.jsonl`）由 `init` / `reindex` 管理，`reindex` 可从文件重建索引。
- `add-paper` 按 `source:source_id` 去重并写 `raw/text/<id>.txt`；`add-push` 存卡片；`kg-put-node` / `kg-link` / `kg-subgraph` 管知识图；`prop-put` / `prop-list` / `prop-for-node` 管命题。
- `context --node --checkpoint` 聚合知识卡、命题、相关边、该 checkpoint 的归档数与最近论文，供 writer 使用。
- `apply-proposal` 支持 `add_evidence` / `add_alias` / `add_proposition` / `update_summary`；`apply-decisions` 按 `publisher/pending/` + `decisions.jsonl` 应用审批，幂等（重复应用 skip），拒绝也留痕。
- `stats` 输出各层计数。测试见 `tests/test_archive.py`（去重、上下文、三种更新、幂等/拒绝）。
