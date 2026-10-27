---
name: frontier
description: "Run the personal knowledge loop: turn knowledge cards into retrieval queries, rank papers, write long-form pushes, send them to Lark, collect ratings, and update cards / proposition evidence / proposition reviews through one serial question queue. Use when the user wants to run or advance their frontier/knowledge-loop daily workflow."
metadata:
  requires:
    bins: ["python3", "lark-cli"]
---

# frontier

完整流程、领域模型、更新契约与飞书卡片格式都在 **[`skills/frontier-loop/SKILL.md`](skills/frontier-loop/SKILL.md)**。本文件只做入口转发，不再维护第二份流程。

- 运行方式：**由宿主 agent 在本机按需执行**，一次一个意图，做完退出。不装 systemd、不装常驻监听、不写持久环境变量。
- 安装：把 [`INSTALL.md`](INSTALL.md) 第 3 节的 prompt 交给宿主；安装状态由 `python -m hostrun.cli install report` 给出（`working` / `blocked` / `untested`）。
- 数据根：默认 `~/knowledge-loop`；用 `--home <路径>` 显式指定（支持中文与空格）。`KL_HOME` 仅在未给 `--home` 时生效。
- 自检：`python -m hostrun.cli install status`、`python -m hostrun.cli status`、`python -m pytest -q`。
- 三个意图：`run --intent daily|feedback|maintenance`；反馈入口是 `hostrun feedback submit|process`。
- 契约：`contracts/README.md`、`contracts/agent-tasks.md`；队列：`docs/specs/unified-question-queue.md`。
- 验收：以 [`docs/acceptance/`](docs/acceptance/) 的实测记录为准；未实测的宿主写「未实测」，缺能力的写「阻塞」，不写成通过。
