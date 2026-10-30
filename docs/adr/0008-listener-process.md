# ADR 0008：监听进程承担 24 小时在线操作，宿主定时任务只做有界运行

- 日期：2026-10-29
- 状态：已接受（设计与文档）；代码已由实施票据 #62–#68 实现（合入 `spec61-integration`）；真实验收待办
- 修订：[ADR 0005](0005-agent-owned-execution.md) 中"不创建独立常驻程序"的约束，以及"每小时检查反馈"的默认调度；[ADR 0005](0005-agent-owned-execution.md) 其余约束继续有效
- 相关：[ADR 0006](0006-deepseek-harness-as-a-host.md)（DeepSeek Harness 作为运行宿主）、[ADR 0007](0007-reuse-configured-lark-cli.md)（用已配置的 lark-cli）

## 背景

[ADR 0005](0005-agent-owned-execution.md) 之后，frontier 的所有运行都由宿主 agent 的一次唤醒承担：每日 08:00 推送，每小时 `*:05` 检查反馈。用户的两个新要求改变了这个前提：

1. 希望 24 小时都能通过飞书操作 frontier，而不是只有宿主被唤醒的那几分钟；
2. 宿主定时任务只允许**瞬时运行**，不再为了保持在线而长期挂着会话。

"24 小时在线"和"不挂会话"无法同时由宿主会话调度满足，因此需要一个独立于会话的常驻进程：它消费飞书事件，代替原先每小时会话检查承担反馈处理，并在需要判断的工作上按需拉起一次有界宿主运行。

## 决策

### 1. 宿主定时任务改为两个瞬时任务

- `frontier-daily`：每日 08:00（用户时区）请求并开始一篇推送；仍由每次唤醒的会话亲自完成排序与写作，完成后**立即结束**，不派生后台作业、不保持会话。
- `frontier-listener-check`：每日 09:00 巡检监听进程；纯机械检查，几十秒内结束。
- **取消**每小时反馈检查任务；反馈处理改由监听进程承担（见第 4 条）。合并逻辑不变：错过多天最多合并成一次待推请求。

### 2. 监听进程的形态与生命周期

- 宿主机器上的**单一前台控制台进程**，窗口标题固定为 `frontier-listener`，便于用户识别与手动停止。
- 由用户启动和停止：`<home>/bin/frontier-listener.cmd` 启动，`<home>/bin/frontier-listener-stop.cmd` 停止，也可 `Ctrl+C` 或关闭该窗口。
- 单实例锁 `<home>/listener/listener.lock`；心跳 `<home>/listener/heartbeat.json` 每 60 秒重写；日志 `<home>/listener/listener.log`。
- **不**注册 Windows 服务、系统计划任务、登录自启或注册表项；机器重启后监听进程不在线，直到用户启动或巡检报告。

### 3. 事件面与命令集

- 用 **bot 身份**消费 `im.message.receive_v1`，并在同一私聊回复；与日常推送同一身份。
- 只接受已核实收件人（`install/recipient.json` 的 owner）的**单聊**消息；群聊、他人消息一律忽略并记日志。
- 命令集 v1：`推一篇`、`处理反馈`、`状态`。未知文本只回复用法提示，不对自由文本做解释执行。
- `暂停`/`恢复` 命令、登录自启、Windows 服务均**不在 v1 范围**；暂停仍由用户停止监听进程与在宿主中停用定时任务完成。

### 4. 反馈处理

- 监听进程内置 **5 分钟**轮询：`hostrun run --intent feedback`。这是纯机械运行（处理已提交答案、恢复未完成工作、当天首次维护），不需要模型。
- 执行端租约被占用时跳过本轮，下一轮再试；不抢、不强制、不重试。
- 无变化时保持安静，不发消息。

### 5. 需要判断的工作：派生一次有界宿主运行

- 监听进程用**记录的 `dsh` 绝对路径**执行 `dsh --profile headless` 派生一次宿主运行（本机为 `D:\dsh\resources\runtime\cli\bin\dsh.cmd`；`dsh` 不在 PATH，必须记录绝对路径）。
- 护栏：单飞行锁（同一时刻最多一个派生运行）；派生前必须取得执行端租约；单次上限 20 分钟；失败**不自动重试**，只回执并留日志；每次派生写 `hostrun/runs.jsonl` 并标记为派生；`install report` 存在 `blocked` 项时拒绝派生并如实回复。
- 派生运行使用与定时任务相同的仓库、数据根、解释器与 `frontier-run` 技能，按同一条正向链路执行；它**不是第二个执行端**，受同一租约约束。

### 6. 监听巡检

- 每日 09:00 由宿主 agent 执行：读取心跳新鲜度（≤10 分钟）、进程存活、最近一次成功事件时间。
  - 解读：**在线判定仍为"心跳新鲜 + 进程存活"**；"最近一次成功事件时间"以 `last_event_age_seconds` 作为明确的诊断输入输出（心跳新鲜但超过 `listener.event_stale_seconds` 无成功事件时给出提示），不改变自动恢复行为。
- 判定不在线时，用记录的启动命令拉起一次，30 秒后复查：
  - 恢复成功：报告"已自动恢复"；
  - 仍失败：报告具体缺项并**停手**，不无限重试。
- 巡检证据单独记为 `listener_health` 步骤；**不**套用 `scheduled_run` 的"计划后 5 分钟"到点容差。到点容差用来证明"这次运行是调度器触发而非手动"，巡检不需要证明同一件事。

### 7. 时段与打扰

- 夜间不静默：派生运行与回执在收到用户主动命令后立即执行。即时运行只由用户主动的飞书命令触发，不存在系统自己半夜发起的情况。
- 08:00 自动推送时段不变。

### 8. 并发与身份

- 监听进程与宿主运行共用现有执行端租约（默认 45 分钟、时间租约）；监听进程永不强制、不抢占、不并行写知识库。
- 收发统一使用 bot 身份，不依赖 user 身份；这与当前 bot `ready`、user 身份受 DPoP 存储影响的实测状态一致。

## 验收标准

"24 小时在线"必须由真实证据支撑，缺一项只能记 `untested`：

1. 监听进程连续运行 ≥24 小时，心跳覆盖全程，日志无崩溃重启；
2. 至少一次真实飞书命令端到端：`状态` 立即回复；`推一篇` 成功派生并回执，或如实回复排队；
3. 巡检至少一次真实执行，并正确判定"在线"；
4. 人为杀掉监听进程后，巡检能发现并自动恢复一次；恢复不了就如实报告并停手；
5. 反馈提交后 ≤10 分钟被处理至少一次。

## 后果

- **代价**：多一个需要用户手动启动的进程；机器重启后短期内系统不在线，要等用户启动或巡检报告。取消每小时任务后，监听进程不在线时反馈会堆积到下一次监听启动或 08:00 推送运行。
- **收益**：反馈时延从"≤1 小时且依赖会话"降到"≤5 分钟"，且飞书操作在一天任何时刻都有响应。
- **安全边界**：只接受 owner 单聊、命令白名单、固定动作映射；不把消息正文当自然语言任务自由执行。ADR 0005 的"单用户、单执行端、只处理已提交反馈"继续成立。
- **证据语义变化**：`scheduled_run` 只覆盖两个瞬时任务；监听在线由 `listener_health` 单独记录。已知缺陷（DSH 投递到执行的延迟可能十几分钟，导致 `scheduled_run` 被判非到点）单独记录，不据此放宽巡检判定。
- **不再被启动的旧路径**：`trigger.service.listen`（opencode 无头 agent）与 `publisher.service.listen`（卡片回调）保持退役；新监听进程是 `hostrun.cli listener`，复用 `publisher.feishu.consume_events`、统一问题队列与执行端租约。

## 实现状态

本决策最初只确认设计、文档与验收标准。实施票据 #62–#68 已完成代码：

- `hostrun/listener.py`：单实例锁、心跳、滚动日志、有界事件消费、命令路由、5 分钟反馈轮询、派生运行护栏与退避；
- `hostrun/cli.py`：`listener install|start|stop|status|serve|health`、`run --intent listener-check`，并修正"no detached listeners"的模块说明；
- `hostrun/intents.py`：`listener-check`（只读健康判定、至多一次拉起、记录 `listener_health`，不写 `scheduled_run`）；
- `hostrun/schedules.py`：任务集改为 `frontier-daily` + `frontier-listener-check`，旧 `frontier-feedback` 迁入 `retired_tasks`；
- `hostrun/base.py`：`paths.dsh` 与 listener 配置项；`publisher/feishu.py`：可复用有界事件消费；
- 安装流程：`listener install` 启停脚本、`install check`/`report` 的 `listener` 与 `listener_health` 步骤；
- `tests/test_hostrun_listener.py` 等离线用例，不依赖真实飞书或真实 `dsh`。

上述代码通过离线测试（#69：538 passed / 3 skipped），**不代表真实验收通过**；本文件"验收标准"的 5 项真实证据仍全部为 `untested`，见 `docs/acceptance/README.md`。

## 2026-10-30 真实验收修订

真实运行暴露两处与实现假设不符的事实，已在实现与离线用例中修正：

1. **派生运行的 argv**：本机 `dsh`（DeepSeek Harness 0.2.1-rc.3）的 headless profile 把任务作为**位置参数**（`dsh --profile headless "<task>"`），没有 `--prompt` 选项。原实现按 `--prompt <brief>` 构造，真实派生会在参数解析阶段失败；现已改为位置参数并通过真实命令确认用法。
2. **`event consume` 退出码 3 的语义**：真实运行中一次到 `open.feishu.cn` 的 i/o 超时之后，事件长连接以退出码 3 退出，且 stderr 不含 `app_scope_not_applied`。原实现把所有退出码 3 判为 FATAL 会直接终止一个健康的监听进程，与"连续 ≥24 小时"的验收门槛冲突。现改为：**只有 stderr 出现 `app_scope_not_applied` 才是 FATAL**（需要人工修授权）；裸退出码 3 视为长连接掉线，按 4/5 的退避重试（5 s → 15 s → 30 s → 60 s 上限），连续失败只把心跳标为 `degraded`，不退出进程。

这两条都是实测优先于设计假设的修订，不改变本 ADR 的其他决策。
