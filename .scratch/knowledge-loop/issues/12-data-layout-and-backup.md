# 12 数据布局定案与备份容灾

Type: grilling ｜ Status: open ｜ Blocked by: —

> 本票由票 06 结票后从「Not yet specified」**毕业**而来。票 06 给出的是**建议**（推荐混合 C），**决定权在你**。

## Question

把票 06 的三层契约落到具体的**布局与运维**上。

要定：

- **布局选型** —— A 全放 repo（随 git、天然异地备份，但 PDF/JSONL 撑大仓库、且 `.scratch/` 在本 repo 的语义是 issue 暂存区，承载长期数据与本意冲突）／B 全放独立目录（agent-agnostic 但不在 git、旧系统就是这样静默丢失）／**C 混合**（票 06 推荐：契约在 repo、数据在 `~/knowledge-loop/`、单一配置入口 `KNOWLEDGE_LOOP_HOME`）
- **数据根怎么声明** —— 环境变量 vs repo 内 config 段 vs 两者（谁是唯一权威）
- **小状态放哪** —— `rotation.json`、`runs/<date>.json` 这类小状态：只在数据目录，还是 repo 内也留冷备/种子（多一份会不会产生「两份真相」）
- **备份策略（票 06 定为硬性要求）** —— 备什么（只备 `knowledge/` + `papers.jsonl`，还是含 PDF）／多久一次／**备到哪**（另一台机？网盘？私有 git 远端？）／**怎么知道备份还活着**（旧系统是「无备份且无人知」——这条比备份本身更容易失败）
- **状态机落地** —— 票 06 建议 `fetch → select → write → archive → update_kb → push` 每阶段写 `Status` 进 `runs/<date>.json`：是否采纳、`Status` 枚举取值、以及它同时担当「卡片流上下文桥」（票 02）时需不需要额外的卡片级粒度

## Answer

（pending）
