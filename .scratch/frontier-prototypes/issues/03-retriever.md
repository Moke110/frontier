# 03 retriever：取原文原型

Type: prototype ｜ Status: resolved ｜ Blocked by: —

## Question

retriever 读 frontier 的检索计划，按源取回候选论文，统一成一种 candidate 结构（元数据 + abstract 原文 + 查询归属），供 editor 排序：

- **fixture 模式**（默认）：从本地 `fixtures/papers/*.json` 按词命中过滤，离线可跑。
- **live 模式**：arXiv Atom API + Europe PMC REST，限定字段查询；预印本标 `is_preprint`。
- 输出去重（同 `source:source_id` 只留一条）、按 checkpoint 归组、保留检索时的 `query_id` 与时间窗口。
- 无候选时退出码 2（符合 spec 的分级退出码）。

## Answer

已实现 `retriever/adapters.py` + `retriever/cli.py`：

- 统一 candidate 结构（source / source_id / title / abstract / authors / journal / published / url / is_preprint + `paper_id` + `retrieval`）。
- `fixture`：从 `--fixtures` 目录按 ontology 词命中 title+abstract 过滤，离线可跑；`live`：arXiv Atom + Europe PMC REST，限定字段查询、标题黑名单、预印本标记。
- 去重 `source:source_id`；按计划窗口过滤出版日期；无候选退出码 2，取数失败 3。
- 测试见 `tests/test_pipeline.py`（噪音论文被排除、paper_id 生成、窗口过滤）。
