# 06 publisher：飞书推送 / 评分 / 审批原型

Type: prototype ｜ Status: resolved ｜ Blocked by: —

## Question

publisher 负责与飞书对接（`lark-cli`），把 push 变成卡片、收集评分、在满足条件时征集知识更新同意：

- 评分卡：正文 + 可选评语 + 三按钮（不相关 / 一般 / 很好），一次提交同时拿回评分与评语（已验证的 3 按钮 + form 方案）。
- 评分落 `ratings.jsonl`；随后把该推送的卡片原地改成确认态。
- 若 writer 对该 push 提了知识更新，且用户评分不是「不相关」，则再发一张**审批卡**，逐条列出 diff，按钮「同意 / 拒绝」。
- 决策落 `decisions.jsonl`，待审批提议副本落 `publisher/pending/`，由 archive 应用 —— publisher 不直接改 archive。
- 支持 `--dry-run` 与离线 `ingest`，无飞书环境也能测。

## Answer

已实现 `publisher/{cards,feishu,store,service,cli}.py`：

- `send`：Card 2.0 评分卡 = 正文 + 可选多行评语 + 三按钮（`score_low/mid/high`，form submit）；`--dry-run` 写入 `publisher/outbox/` 并生成 `offline_rating_*` 路由 id。
- `listen` / `ingest`：解析 `card.action.trigger`；落 `ratings.jsonl`（按 message_id+action+operator 幂等）；原地把卡改成确认态（token）。
- 评分非「不相关」且有 `proposals` 时：复制到 `publisher/pending/`、发审批卡（同意 / 拒绝 + diff 摘要），决策落 `decisions.jsonl`。
- 只写 publisher 自己的状态，不改 archive；`archive apply-decisions` 负责应用。离线 `ingest --offline` 可完整演练。
- 测试见 `tests/test_publisher.py`（卡片结构、dry-run、评分→审批、拒绝路径）。
