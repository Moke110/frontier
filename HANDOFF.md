# 交接文档（2026-10-27）

给下一个接手 frontier 仓库的 agent 看。本文只写**当前状态、卡在哪、下一步怎么做**；已落在别处的内容用路径引用，不复制。

- 仓库：`E:\Desktop\frontier`（GitHub `Moke110/frontier`），原生 Windows（非 WSL），Python 3.13 venv 在 `.venv/`
- 当前提交：`362d005` `feat(hostrun): host-owned install, queue durability and bounded runs (#30-#36)`
- 工作树：干净；测试 `188 passed, 3 skipped`
- 数据根：默认 `~/knowledge-loop`，**优先用 `--home` 显式传**，`KL_HOME` 仅在未给时生效

## 1. 本轮做完的事

按 ADR [`0005-agent-owned-execution`](docs/adr/0005-agent-owned-execution.md)（安装、调度、恢复归宿主 agent）新增 `hostrun/` 包，共 2845 行：

| 文件 | 职责 |
|---|---|
| [`hostrun/install.py`](hostrun/install.py) | 七步探测（host / dependencies / lark_cli / identity / knowledge_base / schedules / first_run）、可续接 `state.json`、`working / blocked / untested` 三段报告、evidence 凭据脱敏；`ok` 是终态，复检不降级 |
| [`hostrun/kb.py`](hostrun/kb.py) | 飞书链接解析、attach（只写配置不建表）、14 张表幂等建齐、`--expect-empty` 列出样本标题、初始主题需 `--yes` 确认 |
| [`hostrun/feedback.py`](hostrun/feedback.py) | 飞书侧「问题 / 反馈 / 更正」三张持久表；`submit` 是唯一提交边界；只处理活动题；更正只入队；`rebuild` 从飞书重建且不重放已处理决定 |
| [`hostrun/executor.py`](hostrun/executor.py) | 单执行端**时间**租约（free / held / stale）、过期接管留痕、换机必须 `handover`（旧端活跃需 `--force`） |
| [`hostrun/intents.py`](hostrun/intents.py) | `daily / feedback / maintenance` 三意图，固定顺序：反馈 → 恢复未完成 → 维护（到期才做）→ 检索闸门；维护每自然日至多一次，失败不记完成 |
| [`hostrun/schedules.py`](hostrun/schedules.py) | 生成三个任务的**确切命令**，需用户确认；只有 `--host-created` 才把 `schedules` 记为 ok |
| [`hostrun/audit.py`](hostrun/audit.py) | 174 篇基线比对、分片**按序**校验、悬空推送引用、15 条旧测试推送单列、配额 <1%、连续零差异 streak |
| [`hostrun/cli.py`](hostrun/cli.py) | 命令面；内含 `_normalize()` 让 `--home / --offline` 也能写在子命令之后 |

测试 935 行：`tests/test_hostrun_install.py`、`test_hostrun_kb.py`、`test_hostrun_feedback.py`、`test_hostrun_runtime.py`。离线夹具在 [`tests/conftest.py`](tests/conftest.py)（`offline_home` / `configured_home` / `offline_base`）。

文档与入口：

- [`INSTALL.md`](INSTALL.md) 重写为**唯一**安装入口，含可直接粘贴的 prompt
- 旧 systemd 说明 `git mv` 到 [`docs/legacy/2026-10-systemd-install.md`](docs/legacy/2026-10-systemd-install.md)，[`deploy/README.md`](deploy/README.md) 标 legacy
- [`README.md`](README.md)、[`SKILL.md`](SKILL.md)、[`skills/frontier-loop/SKILL.md`](skills/frontier-loop/SKILL.md)、[`WINDOWS-TRANSFER.md`](WINDOWS-TRANSFER.md) 全部改指现行入口，不再要求软链 / 常驻 listener / `export KL_HOME`
- [`contracts/README.md`](contracts/README.md) 新增 §12：hostrun 命令面、数据根布局、状态语义、租约规则

## 2. 顺手修掉的真缺陷（都是会让功能静默失效的那种）

1. `install.summary()` 里 `**buckets` 覆盖了布尔 `ok`——报告永远读不到布尔值；
2. `first_ok_at` 首次成功时从不写入，续接时间线缺失；
3. `schedules plan` 生成 `run --home …`，argparse 直接拒绝——**所有排程命令都跑不起来**；
4. `audit` 分片校验比较排序后的集合，`part02→part01` 也能通过；
5. `scripts/demo.py` 自七段推送格式落地后就一直失败（模板推送没有 `sections` + 走的是已退役的审批卡链路），已改为跳过 `writer render`、演示统一队列 + 逐题同意。

Windows 侧两个既有失败不再报错：`tests/test_trigger.py` 的 POSIX 进程组测试改为条件跳过；`tests/test_pdf_writer.py` 的 WeasyPrint 依赖改为守卫。`trigger/service.py::_kill_tree` 补了 `taskkill /T` 分支。

## 3. 开放项与解除阻塞的确切条件

Ticket 实现类 #30–#36 已关闭。#37 / #38 / #39 / #40 与 spec #29 **保持开启**，因为缺真实环境证据——不要把它们改成通过。

本机 `install check` 的真实结论（原始输出见 [`docs/acceptance/2026-10-27-host-matrix.md`](docs/acceptance/2026-10-27-host-matrix.md)）：

- `dependencies: ok`
- `lark_cli: blocked`、`identity: blocked`（本机没有可用的 `lark-cli`）
- `host: untested`（未声明宿主版本与内置调度）
- 空库对 174 篇基线：`missing: 174`、`streak: 0`

缺的三类证据，解除顺序建议如下：

1. **装 lark-cli 并授权**：装到私有目录（`<home>/bin`），完成 user/bot 授权，然后
   `python -m hostrun.cli --home <home> install check --repo . --host-product <产品> --host-version <版本>`
   把 `lark_cli` / `identity` 变 `ok`。这一步解锁 #31 的真实建库、`feedback sync`、`audit` 真数据。
2. **宿主真实调度**：在宿主里按 `schedules plan` 输出的命令建三个任务并等到**至少一次真实触发**，留下触发记录，再加 `--host-schedules` 重跑 `install check`，把 `host` 变 `ok`（解锁 #35 / #38 / #37 的调度项）。
3. **连续三天零差异**：真实库上连跑三天 `hostrun audit run --baseline <manifest>`，`streak` 到 3（解锁 #39）。
4. 以上都拿到后，按 `INSTALL.md` 走一次**新装 + 已有库恢复**，再关 #40。

注意 #37 是 ChatGPT 宿主：本机无法实测，只能在有 ChatGPT 本地执行能力的环境复现，**不要拿 WorkBuddy 的结果顶替**。

## 4. 已知坑

- `--home` 的**位置**：argparse 只认全局位置；`hostrun/cli.py` 的 `_normalize()` 已兜住子命令后的写法，但自己拼命令时仍建议 `python -m hostrun.cli --home X <cmd>`。
- `hostrun kb create-tables` 在离线模式下必须显式传 `client=`，否则会去构造真实 LarkDrive；见 `tests/test_hostrun_kb.py` 的用法。
- `library/offline.py` 的 `JsonBase` 建表后自带一行配置数据，断言「库为空」时要逐表检查 `list(table) == []`，不要断言 `list_tables() == []`。
- `.workbuddy/` 已加入 `.gitignore`（工作记忆与临时文件，不进版本库）。
- 不要用 `git add -A` 前忘了 `.workbuddy/` 已被忽略——上一轮正是靠 `git add -A ':!.workbuddy'`。
- `docs/legacy/2026-10-systemd-install.md` 里的 `WINDOWS-TRANSFER.md` 相对链接指向同目录，实际文件在仓库根；属历史文档，未修。

## 5. 常用命令

```bash
cd /e/Desktop/frontier
.venv/Scripts/python.exe -m pytest -q                              # 188 passed, 3 skipped
.venv/Scripts/python.exe scripts/demo.py                           # 离线端到端，写可丢弃数据根
.venv/Scripts/python.exe -m hostrun.cli --home <home> install report
.venv/Scripts/python.exe -m hostrun.cli --home <home> status
```

## 6. 建议技能

下一位接手时按需用 Skill 工具调用（这些都不会自动触发，需要显式调）：

- `implement` — 继续做开放 ticket / spec（本轮就是用它推进的）
- `code-review` — 提交前按标准与规范两轴审一遍改动
- `grilling` / `grill-with-docs` — 在动 #37/#38 的验收口径前，先把「什么算通过」问清楚
- `diagnosing-bugs` — 真实环境接入后若 `install check` 某步反复失败
- `handoff` — 下一次会话结束时再次压缩交接

## 7. 一句话状态

实现该做的都做完了且离线可验证；**剩下的全部是「真实环境证据」**——lark-cli 授权、宿主真实调度触发、真实库连续三天零差异。在这三样拿到之前，不要关闭 #37/#38/#39/#40，也不要在任何文档里写成已通过。
