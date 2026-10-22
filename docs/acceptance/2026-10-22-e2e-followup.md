# 端到端复验（#19 / #20 / #21）

- 日期：2026-10-22
- 修复提交：`d941fd2`（`fix: make the auto-push chain observable and lease-safe`）
- 环境：`~/knowledge-loop`，`frontier-listener` / `frontier-rating-listener` / `frontier-daily.timer` / `frontier-retry.timer` 全部 active
- 结论：**昨日失败的两项均通过**。队列清空后自动拉起成功，整条链路无人工改数据。

## 复验矩阵

| # | 要求 | 结果 | 证据 |
|---|---|---|---|
| 5 | 全部答完自动启动下一次检索推送 | 通过 | 09:46:36 最后一题 `reject_all` → 09:46:37 `spawn` + `start` → 10:05:43 推送 `2026-10-22_card_systematic_variation_01` |
| 6 | 差评场景丢弃更新题 | 通过 | 10:06:15 评分 `irrelevant` → 命题更新题 `dropped`（`rating_irrelevant`） |
| 7 | 全程无需手工改数据 | 通过 | 本轮无 `finish-start` / `request-push` 手工介入；知识写入只经 archive |

昨日已通过项（1–4）见 `2026-10-21-e2e.md`。

## 本轮时间线

- 09:46:26 / 09:46:32 昨日遗留的两道更新题被 `reject_all`
- 09:46:36 队列清空 → `request.start`（08:00 定时请求，因队列未清空一直待推）
- 09:46:37 `publisher/service.py::_spawn_pending` 拉起 `trigger.cli run-request`，`trigger-spawn.log` 写入 spawn 头
- 09:47–10:03 检索 → 排序 → 写作；`editor task` 已排除 `archive/pushes` 里出现过的 `paper_id`
- 10:05:43 PDF + 评分题发送成功（`om_x100b62a2b9b0a484cef07fa9ad21ee8` / `om_x100b62a2b94718accef4bc5ecee0aba`）
- 10:06:03 兜底 timer 触发，此时 job lock 仍被占用 → 返回 `busy`，未动 request/lease（新行为）
- 10:06:05 本轮 job `finish ok`，清 request
- 10:06:15 评分 `irrelevant`，命题更新题整组 dropped，队列清空

## 修复验证

| 修复 | 验证方式 |
|---|---|
| spawn 子进程日志、失败告警 | `trigger-spawn.log` 有 09:46 与 17:44 两次 spawn 头；Popen 异常/立即非零退出会写 `spawn_failed`/`spawn_exited` 并发 Lark（单元测试） |
| 兜底 timer（2 分钟，`--quiet`） | 10:06:03 实际触发并正确让行；无待推请求时不写 `trigger.log` |
| 租约覆盖整趟 job | `lease = max(10min, timeout+5min)`；旧代码 09:56/09:58 的两次「抢租约后被 job lock 拒绝」不再出现（单元测试 + 现场） |
| job lock 竞争不释放别人租约 | `test_job_lock_contention_leaves_request_alone` |
| 已推送论文过滤 | `test_editor_task_skips_already_pushed_papers` |
| `publisher send` 拒绝时非零退出 | `test_send_cli_exits_non_zero_on_duplicate` |
| 超时杀进程组 + 记录 agent 尾部 | `test_run_agent_kills_process_group_on_timeout`、`test_timeout_logs_the_agent_tail` |
| 完成校验（无新 push / 未发出） | `test_run_without_any_push_is_a_failure`、`test_run_without_a_sent_push_is_a_failure` |

全部 94 个测试通过。

## 部署动作

- `~/.config/systemd/user/frontier-retry.service` 更新为 `run-request --quiet`，`daemon-reload` 后重启 timer；
- `frontier-rating-listener` 于 10:06:48 重启，加载新的 `_spawn_pending`（存活检查 + Lark 告警）。

## 剩余观察

- 2026-10-23 08:00 是第一次完全无人值守的「定时 → 推送 → 队列」日，作为回归观察点；无异常即视为 #19 稳定。
