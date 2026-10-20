# 05 writer：推送撰写 + 知识更新提议原型

Type: prototype ｜ Status: resolved ｜ Blocked by: —

## Question

writer 消费 editor 选出的原文，产出可直接推送的卡片内容，同时在原文信息足够时**提议**更新知识图 / 命题：

- 四段结构：做了什么 / 发现 / 为什么重要 / 保留。
- 「为什么重要」必须引用 archive 的上下文：checkpoint 的知识卡、相关命题、该 checkpoint 已归档篇数（替代知识库的轻量脉络）。
- 提议（proposal）三种：给命题补证据、给知识卡补别名、新建命题；带 `rationale` 与 `confidence`。
- writer **不直接写 archive**：push 带 `proposals` 字段进入 outbox，由 archive 在审批通过后应用。
- 当前为确定性抽取式原型（无 LLM），接口预留 LLM 替换点。

## Answer

已实现 `writer/model.py` + `writer/cli.py`：

- `write` 输出 `outbox/pushes/<push_id>.json`，含 `sections`（did / found / why / keep）、`body_md`、`context`（知识卡、命题 id、已归档数）、`proposals`。
- 「为什么重要」直接拼接 archive 知识卡 summary + 相关命题 + 该 checkpoint 归档篇数，实现轻量脉络。
- 提议启发式：命题补证据（节点术语共现）、知识卡补别名（ontology 有、节点没有）、新建命题（同一句出现两个未连接节点）；全部 `status: draft`，带 `rationale` / `confidence`。
- writer **只读** archive，不写；push 由调用方交给 `archive add-push`。测试见 `tests/test_pipeline.py`。
