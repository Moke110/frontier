# ADR 0006：DeepSeek Harness 作为第三款运行宿主

- 日期：2026-10-27
- 状态：已接受；本机安装验收执行中
- 相关决策：[ADR 0005](0005-agent-owned-execution.md)（由宿主 agent 承担安装与运行）

[ADR 0005](0005-agent-owned-execution.md) 把 frontier 的运行交给一款能在 Windows 本机执行命令、加载技能并创建定时任务的 agent，并把首批目标定为 ChatGPT 与 WorkBuddy 桌面端。2026-10-27 首次 Windows 安装验收时，本机没有安装 ChatGPT 桌面端，WorkBuddy 5.8.3 虽已安装，但它的宿主会话只能由用户亲手操作，agent 无法在那里产出可核对的运行证据。执行安装的 DeepSeek Harness（DSH）本身满足那三项能力：本机命令执行、技能加载、以及按计划拉起会话的内置定时。

因此把 DSH 记为第三款运行宿主：DSH 产出的证据只证明 DSH 可用，不替代 [ChatGPT 验收 #49](https://github.com/Moke110/frontier/issues/49) 与 [WorkBuddy 验收 #50](https://github.com/Moke110/frontier/issues/50)；两款原有宿主的验收义务不变。这样做的代价是运行宿主从两款变成三款，好处是首次端到端验收不必依赖用户手工搬运证据。

## 后果

- `README.md` 的宿主表新增 DSH 一行；安装时 `install check` 的宿主声明取 `deepseek-harness`，与实际产品名一致。
- DSH 的定时是会话级提醒：宿主关闭或会话结束后不再触发。这与另两款宿主的"电脑开机且应用运行"是同一边界，不承诺关机可用。
- 第三款宿主不改变 ADR 0005 的约束：不注册服务或系统定时任务，不创建独立常驻程序。
- 若 DSH 的定时无法真实拉起一次运行，`scheduled_run` 保持未实测，不得用手动运行代替。
- DSH 同时是本仓库的实现执行者；宿主验收与开发职责是两件事，此决策只涉及前者。
- **2026-10-29 权限决定（用户授权）**：DSH workspace-write 的 Windows 受限令牌会拒绝 lark-cli 凭据库所需的 HKCU 注册表写入，宿主也没有窄路径白名单。用户在验收时会话临时切到 **Full access**，作为"必要宿主权限"的显式授权；这不是 agent 自行绕过，`scheduled_run` 等证据仍须真实到点后才算通过。切回 workspace-write 后定时任务的令牌刷新可能失败，运行环境需保持该授权档位。
