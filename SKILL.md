---
name: frontier
description: "Run the personal knowledge loop: turn knowledge cards into retrieval queries, rank papers, write long-form pushes, send them to Lark, collect ratings, and update cards / proposition evidence / proposition reviews through one serial question queue. Use when the user wants to run or advance their frontier/knowledge-loop daily workflow."
metadata:
  requires:
    bins: ["python3", "lark-cli"]
---

# frontier

完整流程、领域模型、更新契约与飞书卡片格式都在 **[`skills/frontier-loop/SKILL.md`](skills/frontier-loop/SKILL.md)**。本文件只做入口转发，不再维护第二份流程。

- 前置条件：已安装 agent；`lark-cli` 已登录并订阅 `card.action.trigger`；仓库已软链到 agent 的 skills 目录。
- 数据根：`export KL_HOME="${KL_HOME:-$HOME/knowledge-loop}"`。
- 自检：`command -v lark-cli && lark-cli auth status --json && python3 -m pytest -q`。
- 契约：`contracts/README.md`、`contracts/agent-tasks.md`；队列：`docs/specs/unified-question-queue.md`。
