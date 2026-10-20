# 07 端到端离线 demo

Type: prototype ｜ Status: resolved ｜ Blocked by: 01, 02, 03, 04, 05, 06

## Question

用 fixtures 在临时 `KL_HOME` 里把整条链路跑通，证明六个模块**只靠文件契约**就能串起来：

checkpoint → frontier.plan → retriever(fixture).fetch → editor.fit/rank → writer.write → archive.add-push → publisher.send(dry-run) → 模拟评分事件 → 生成审批卡 → 模拟同意 → archive 应用提议。

要求：一条命令可重复执行、不联网、不污染仓库数据、结尾打印每步产物路径与关键字段。

## Answer

已实现 `scripts/demo.py`：一条命令在 `/tmp/kl-demo-*` 建临时 `KL_HOME`，离线跑完 12 步，结尾验证：

- 命题 `prop_hmbs_aip` 多了一条证据（`europepmc_42900001`）；
- 知识卡 `kg_hmbs` 多了一个别名 `hydroxymethylbilane synthase`；
- 命题数 2 → 3（新建 `kg_hmbs ↔ kg_heme` 命题）；
- `frontier.record` 后 HMBS 权重 6 → 7，`editor.fit` 学到偏好，重排后 HMBS 论文分数上升（0.64 → 0.69 量级）；
- 全流程无网络、无飞书调用。`python -m pytest -q` 全部通过（当前 18 个）。
