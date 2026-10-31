# 验收记录与待补证据

本文件只记录验收证据与缺口，不替代 [GitHub 任务](https://github.com/Moke110/frontier/issues/29)。以下按日期归并证据；规格 [#51](https://github.com/Moke110/frontier/issues/51) 的历史离线实现与本轮文档修订分开记录。历史阻塞须在目标宿主重新探测，不能直接当作当前结果。代码通过离线测试不等于产品通过真实验收。

## 2026-10-31 发行包安装验收（spec #92 / ADR 0010；真实证据未取得，保持 `untested`）

本轮对应 spec #92 / ADR 0010 的 ticket #99 与 #100：ticket #99 把 README 安装段与 `skills/frontier-run` 参考切换为发行包安装，并补齐 tag/渠道开发指引与验收项；ticket #100 修复了发行包安装后的技能指针接缝，并用 fixture 发行包跑通离线端到端机制。本轮**未取得真实证据**，也没有执行真实 tag 发布、GitHub Release 下载、真实安装或 `/frontier-init`；下表中所有真实环境项仍是 `untested`，在 Lead 的线上 CI 与真实安装运行取得证据前，不得把本节当作验收通过，也不得把“命令存在”或“离线测试通过”当成安装方式已验收。

| 验收项 | 结果 | 离线覆盖 / 待补证据 |
|---|---|---|
| 用户在没有 git、uv、pip 或系统 Python 的机器上从 GitHub Release 安装（稳定或预发布渠道） | `untested` | 文档与命令面由离线测试覆盖；真实“无系统 Python”机器安装待 Lead 在真实 Release 上执行 |
| 下载不完整或被篡改时，摘要校验在解压前失败且不改代码目录 | `untested` | `hostrun/dist.py` 的摘要/清单/兼容性失败语义有离线测试；真实下载失败场景未执行 |
| 安装锁如实报告版本、渠道、来源与安装时间 | `untested` | 锁字段、`install verify` 与 `install report` 的 `release` 块有离线测试；真实安装锁未取得 |
| 升级只替换发行包，资料目录、运行状态与知识库数据不变 | `untested` | 保留/替换/清理陈旧文件的离线测试存在；真实升级未执行 |
| 回滚到上一版且不需要重新执行 `/frontier-init` | `untested` | 回滚切树、锁字段与运行状态不变的离线测试存在；真实回滚未执行 |
| 用户机器上不出现 git、uv、pip、`.venv` 或工具链目录 | `untested` | 发行包布局与包装器不引用 PATH 的离线测试存在；真实机器检查未做 |
| 测试工作区使用独立飞书设施（独立 Base + 两个 `-test` 云盘目录），不抢正式执行端 | `untested` | 仅有文档约束；真实测试安装与设施创建未执行 |
| CI 在 `v*` tag 上构建可重复的发行包并发布 Release | `untested` | tag→版本/渠道映射、两次构建同摘要、工作流 YAML 不变量有离线测试；真实 tag 触发需要 Lead 批准 |
| 发布索引记录 version/channel/artifact sha256 并由 `github-actions[bot]` 提交到 `main` | `untested` | 索引合并/校验/排序有离线测试；真实 Release 与索引提交未执行 |
| `/frontier-init` 在发行包安装上走完全流程 | `untested` | 控制台与初始化流程有既有离线覆盖；发行包安装的真实初始化未执行 |
| `install verify` / `install report` 与磁盘内容一致 | `untested` | 逐文件比对与报告字段有离线测试；真实安装上的执行未做 |
| 现有源码安装不被新发布流程自动改动 | `untested` | 源码锁与 `source_install` 报告有离线测试；真实既有安装未观察 |
| 离线端到端：安装发行包 → 控制台脚本 → 技能指针 → 升级 → 回滚 → 报告 | `offline-verified`（仅机制证据，不是验收） | `tests/test_dist_e2e.py::test_distribution_package_install_skill_upgrade_rollback_end_to_end` 在临时工作区用带合成 `runtime/` 的 fixture 发行包驱动 CLI：安装锁、`frontier-console.cmd` 委托、指针字段、`verify_skill`、运行状态哨兵、v1→v2 升级、回滚、`install report` 与未知版本回滚阻断均通过；`tests/test_dist_pending.py` 另覆盖安装/升级/回滚中断后的标记清除与恢复 |
| 离线文档命令面与套件回归 | `offline-verified`（仅机制证据，不是验收） | 同一模块的 `test_readme_documented_install_steps_exist_and_are_in_order` 校验 README 安装步骤顺序与 CLI 子命令；本分支全量 **1012 passed, 3 skipped**（2026-10-31，`python -X utf8 -m pytest -q ... tests`） |

**离线套件覆盖的机制（不等于验收）**：本轮离线全量 **1012 passed, 3 skipped**（2026-10-31，仓库 `.venv`，`python -X utf8 -m pytest -q`）；它只证明机制与文档一致，不构成真实安装证据。覆盖内容包括：发行包清单与 zip 可复现、摘要不符在解压前失败、安装锁字段、升级保留与回滚、`install report` 区分发行包/源码、启动包装器与内置运行时布局、tag→渠道映射、发布索引合并、文档中的命令与 CLI 子命令一致，以及 ticket #100 新增的离线端到端（fixture 源码 + 合成 runtime → 安装 → 控制台脚本 → 技能指针 → 升级 → 回滚 → 报告）。ticket #100 同时修复了 `install skill` 在发行包安装上因缺少工作区记录而被拒绝的接缝；技能指针仍由安装锁与发行包清单推导，不伪造源码锁。真实 CI tag 运行、Release 下载、独立飞书设施的测试安装与 `/frontier-init` 仍需 Lead 批准并执行，列入下节清单。

### 待真实取证（Lead，CI Release 后执行）

以下所有项均未执行，保持未勾选；离线测试不能代替真实证据。命令中的 `<...>` 替换为实际绝对路径或版本，发行包与摘要只从 GitHub Release / `releases/index.json` 获取。

```powershell
# 0. 目标机应没有可用的 git、uv、系统 Python（无输出才符合“无工具链”）
Get-Command git,uv,python -ErrorAction SilentlyContinue

$version = "<version>"; $channel = "prerelease"
$zip = "frontier-$version-$channel.zip"
$digest = "frontier-$version-$channel.digest.json"

# 1. 下载发行包与摘要，解压前校验摘要
gh release download "v$version" --repo Moke110/frontier --pattern $zip --pattern $digest
$expected = (Get-Content $digest -Raw | ConvertFrom-Json).artifact.sha256
$actual = (Get-FileHash -Algorithm SHA256 $zip).Hash.ToLower()
if ($actual -ne $expected) { throw "发行包摘要不符：期望 $expected，实际 $actual；停止安装，不解压" }

$temp = "<temp>"; $code = "<code>"; $archive = "<archive>"
$dsh = "<dsh 绝对路径>"; $hostSkills = "<host skills dir>"

# 2. 解压到临时引导目录，安装到代码目录并写安装锁
Expand-Archive -Path $zip -DestinationPath $temp -Force
& "$temp\bin\frontier.cmd" --code "$code" --archive "$archive" install package --from "$zip" --digest "$digest"

# 3. 校验、生成控制台脚本、注册技能入口指针（均使用内置运行时包装器）
& "$code\bin\frontier.cmd" --code "$code" --archive "$archive" install verify
& "$code\bin\frontier.cmd" --code "$code" --archive "$archive" install report
& "$code\bin\frontier.cmd" --code "$code" --archive "$archive" console install --dsh "$dsh"
& "$code\bin\frontier.cmd" --code "$code" --archive "$archive" install skill --root "$code" --target "$hostSkills"
# 这个命令会重算技能摘要并调用 verify_skill；同时检查 workspace/dependencies。
& "$code\bin\frontier.cmd" --code "$code" --archive "$archive" install check --workspace-root "$code"

# 4. 升级到预发布 v2（下载 v2 的 zip/digest 并重复摘要校验），刷新指针后校验
& "$code\bin\frontier.cmd" --code "$code" --archive "$archive" install package --from "<v2 zip>" --digest "<v2 digest>"
& "$code\bin\frontier.cmd" --code "$code" --archive "$archive" install skill --root "$code" --target "$hostSkills"
& "$code\bin\frontier.cmd" --code "$code" --archive "$archive" install verify

# 5. 回滚到保留的 v1，刷新指针后校验，并查看保留版本
& "$code\bin\frontier.cmd" --code "$code" --archive "$archive" install rollback
& "$code\bin\frontier.cmd" --code "$code" --archive "$archive" install skill --root "$code" --target "$hostSkills"
& "$code\bin\frontier.cmd" --code "$code" --archive "$archive" install verify
& "$code\bin\frontier.cmd" --code "$code" --archive "$archive" install report

# 6. 启动控制台，由用户执行 /frontier-init
& "$code\bin\frontier-console.cmd"
```

- [ ] 第 0 步证明目标机没有 git、uv 或系统 Python，且安装过程未调用它们。
- [ ] 第 1 步下载真实 Release 资产，摘要在解压前校验通过；篡改/截断场景另做一次并确认零写入。
- [ ] 第 2 步 `install package` 成功，`<code>\.frontier\dist.lock.json` 的 version/channel/artifact sha256 与资产一致。
- [ ] 第 3 步 `install verify`/`install report` 如实报告发行包版本与渠道；`frontier-console.cmd` 委托 `frontier.cmd`；技能指针含发行来源/版本/渠道/制品摘要/技能摘要/安装锁且 `install check --workspace-root` 中的 `workspace`/`dependencies` 为 ok、`skill` 由 `verify_skill` 证明为 ok。其余步骤（`lark_cli`、`identity`、`permissions`、`facilities`、`knowledge`）在用户尚未登录/授权/初始化时保持 pending 或 blocked，这是诚实结果，不是本项失败。
- [ ] 第 4 步升级到预发布 v2 后知识库与 `<code>\.frontier\` 运行状态不变，保留 v1，`install verify` 通过。
- [ ] 第 5 步回滚到 v1 后服务可继续运行、无需重新 `/frontier-init`，保留 v2，`install report` 显示回滚记录。
- [ ] 第 6 步 `/frontier-init` 只用独立 Base 与两个命名带 `-test` 的 Drive 目录；正式 Base、正式云盘与正式执行端未被触碰。
- [ ] 测试安装与开发安装并存，开发目录未被升级、回滚或初始化改动。

**已知边界（Lead 重点核对）**：升级或回滚会改写安装锁的 `version`；已注册指针中的发行版本会变旧。上面的清单在两类切换后都重跑 `install skill` 刷新指针。若不重跑，`verify_skill` 会以 `lock_version_mismatch` 阻塞，这是如实报告，不得当作通过。真实 bundled runtime 能否在无系统 Python 的机器上启动 `frontier.cmd`、控制台窗口、真实飞书设施与 `/frontier-init` 仍只能由这次真实运行证明。

**回滚语义说明**：spec #92 的“回滚只切指针”按“不重新下载/解压/构建，只切换版本指针”理解；实现还会从保留版本替换包文件与 `manifest.json` 并恢复安装锁/`current`，不触碰 `<code>/.frontier/` 运行状态与知识库。它不是只改一行指针文本，也不重新安装。该项仍是真实环境 `untested`。

## 2026-10-30 控制台化验收（spec #74 / ADR 0009；仅执行本机可安全运行项）

本轮按 ticket #91 执行**不发送真实飞书消息、不使用凭据、不迁移本机既有安装**的验收。离线全量：**723 passed, 3 skipped**（命令见 `E:\Desktop\frontier-dev\.spec74-notes\impl\91\report.md`；比 #87 基线少的部分是随监听进程/smoke/cleanup/schedules 一并删除的旧测试）。以下“pass”只表示对应命令在本机真实执行并得到记录的结果；ADR 0009 的九项真实验收不因离线或本地替身运行而改变状态。

### 本机真实执行通过的安全项（不构成 ADR 0009 验收）

| 项目 | 结果 | 证据 |
|---|---|---|
| 控制台 CLI 面 | `python -m hostrun.cli --help` 与 `console --help` 成功；只保留 `console` / `console control` / `console install`；`listener`/`schedules`/`smoke`/`cleanup` 子命令与 `run --intent listener-check` 均被 argparse 拒绝（exit 2） | 临时代码目录 `tmp-accept91` 的 `evidence.txt`（工作区外，摘要见 `.spec74-notes/impl/91/acceptance-evidence.md`） |
| `console install` | `--dsh <绝对路径>` 返回 `status=ok`，写入 `paths.dsh` 与 `<code>/bin/frontier-console.cmd`（标题 `frontier-console`、含 `--code/--archive`、`%*`），`processes_started=false`；相对路径 `--dsh` 返回 `status=blocked` 且仍生成脚本 | 同上 |
| 非 TTY 拒绝 | `'' \| python -m hostrun.cli console` → exit 1、`reason=not_a_tty`；未创建 `console/state.json` 或 `heartbeat.json` | 同上 |
| `console control status`（无控制台运行） | 返回 `consumed=false` 与本地只读快照（executor/queue/knowledge/install），不伪装控制台已执行 | 同上 |
| 控制台启动/关闭与暂停恢复 | 在带 TTY 的本地 shell 启动真实控制台进程：启动时执行补推路径（`trigger=scheduled`），知识库门禁未就绪时如实记录 `knowledge_not_ready` 且不发送飞书消息；EOF 退出后 `service=stopped`、日志记录终止在飞运行并标记请求未完成；重开时上次 `paused=true` 被恢复为“服务保持暂停”（`service=stopped, paused=true`），不触发推送。Agent 仅使用占位 `dsh.cmd`，未调用真实模型 | `tmp-accept91c` 的 console/console.log 与 state.json（摘要见同一 evidence 文件） |
| 既有安装迁移（**副本演练，非真实安装**） | 把本机旧数据根 `E:\Desktop\frontier-dev\frontier-archive` 复制到临时目录后执行 `install migrate --from <副本> --no-environment`：`status=migrated`，listener 配置段与启停脚本被移除，`listener.dsh_args` 迁入 `agent_run.dsh_args`，launcher 含 `%*`；旧根目录的 `listener/` 作为 leftover 报告、未迁入运行时区。**live 安装未被迁移**；环境重建、服务启停与知识库读写未执行（`--no-environment`） | `tmp-migrate91/migrate.json` 与生成配置（摘要见同一 evidence 文件） |

### ADR 0009 九项验收（真实证据缺失，保持 `untested`）

1. 控制台连续运行 ≥24 小时、事件流与日志无崩溃重启：**untested**（只做了分钟级本地启动/退出，不能代替）。
2. 至少一次每日推送由控制台计时真实到点触发并送达：**untested**（本地补推路径确实触发，但未连接真实飞书、未取得送达证据；不能把本地触发记作通过）。
3. 飞书指令白名单三条（`推一篇`/`处理反馈`/`状态`）真实往返：**untested**（未发送真实消息）。
4. 非白名单文本经意图判定产出确认卡片、点击后执行并回执：**untested**（无真实飞书回调）。
5. 暂停与恢复各一次、暂停期间飞书只回暂停提示且不派生运行：**untested**（真实飞书侧未验证；本地仅验证“上次暂停则重开保持暂停”）。
6. 关闭控制台窗口后服务确实停止（次日不推送、飞书无响应），重开后按上次状态恢复：**部分本地观察、整体 untested**。已见：EOF 退出即 `service=stopped`、终止在飞运行并标记未完成；重开暂停态保持暂停。未见：真实关闭按钮、次日无推送、飞书无响应。
7. `/frontier-init` 全流程（Lark 安装/登录、测试 HTML 与按钮点击、三项命名、owner 写入）：**untested**（无凭据/未发送消息）。
8. `/frontier-update-kb` 全流程（三种审阅决定、`Under review` 次日不参与检索）：**untested**（无真实 Base/Drive，未做 TTY 审阅）。
9. 既有安装迁移一次，迁移后服务与知识库读写正常：**untested**。仅完成上述副本演练；本机 live 安装 `E:\Desktop\frontier-dev` 未迁移，迁移后的服务启停与知识库读写未执行。

### 本轮真实验收发现并修复的缺陷

- 控制台默认每日运行器签名错误：`_default_run_daily(home, **kwargs)` 被以 `(home, "daily", ...)` 调用，真实补推时报 `TypeError`；离线测试一直注入假运行器所以未暴露。已修并新增 `tests/test_hostrun_console_service.py::test_default_daily_runner_matches_the_injected_seam`。
- 迁移生成的 launcher 未转发参数，`frontier-console control ...` 在迁移后不可用；已补 `%*`（#81 曾记录为跨票据遗留）。
- **2026-10-30 23:20 真实验收（迁移后 `/frontier-init`）**：用户看到传输测试发的是 HTML **文本**而不是 HTML 文件——已改为把测试 HTML 写入代码目录运行时区 `<runtime>/install/transport-test.html` 并以**文件消息**发送（`hostrun/console_init.py`）；新增默认发送器回归测试。
- **2026-10-30 23:20**：创建知识库设施时 lark-cli 输出被按 GBK 解码，`UnicodeDecodeError: 'gbk' codec can't decode byte 0xa2` 导致真实初始化失败。根因是 6 处 `subprocess` 使用 `text=True` 却未指定编码；已统一为 `encoding="utf-8", errors="replace"`（`publisher/feishu.py`、`library/admin.py`、`hostrun/lark.py`、`hostrun/base.py`、`hostrun/install.py`、`trigger/service.py`），并新增 `tests/test_lark_utf8_decoding.py` 回归。修复后离线全量 **739 passed, 3 skipped**。

> 原始命令输出与临时目录摘要保留在工作区外 `.spec74-notes/impl/91/acceptance-evidence.md`。未取得真实证据前，**不得**据本节宣称控制台化已验收。

> 词汇说明：#77（目录模型第三步）之后，位置只有代码目录（`--code`，运行时区 `<code>/.frontier/`）与资料目录（`--archive`，只放 `originals/` 与 `pushes/`）两个概念。本文件 2026-10-30 及更早的记录写于旧 `--home` 模型下，保留原话以如实反映当时的证据，不再代表当前契约。

## 2026-10-30 用户停止剩余真实验收（票据按此口径关闭）

2026-10-30 16:58 用户决定停止剩余真实验收并关闭相关票据。执行：`listener stop` 后监听进程停止（state offline）；三个 DSH 会话提醒全部删除；`schedules pause --yes` 已生效（`enabled=false`，任务全部停用）。本轮不再补测，未取得的证据保持 `untested`，不伪造。

| 今日真实取得（计入证据） | 内容 |
|---|---|
| 监听进程安装 | `listener install` 生成启停脚本，`listener` 步骤 `ok`；`paths.dsh` 记录为绝对路径 |
| 巡检在线判定 | 真实 `run --intent listener-check` 判定 `state=online`、`action=none` |
| 杀进程恢复 | 硬杀 pid 21816 后，真实 `listener-check` 返回 `action=restart_ok` |
| 停止 | `listener stop` 返回 `state=stopped` |
| 派生运行凭据 | `dsh --profile headless --patch <home>/install/dsh-headless-account.patch.yml "..."` 真实运行成功并回答“可用测试” |
| 本轮发现并修复的 4 个缺陷 | `c3262a0`（派生运行位置参数）、`9b557dd`（裸退出码 3 退避）、`e9e6a0d`（stop 等待 35 秒）、`7e16203`（`listener.dsh_args` 凭据 patch）；已并入 `main` `b046cb1` |
| 离线回归 | **584 passed, 3 skipped** |

**未取得（`untested`，不得据此宣称通过）**：

1. 真实飞书命令 e2e：`状态` / `推一篇` 用户从未发送；
2. 反馈提交后 ≤10 分钟被处理至少一次；
3. 监听进程连续运行 ≥24 小时：修复后的构建 2026-10-30T16:45:52 起运行到约 16:57（约 11 分钟）；更早 16:12–16:19 的运行因已修复的退出码 3 缺陷崩溃；
4. `frontier-daily` 08:00 与 `frontier-listener-check` 09:00 的真实到点触发（`scheduled_run` 仍 `untested`）。

因此 [#59 两类宿主任务与真实触发](https://github.com/Moke110/frontier/issues/59)、[#61 监听进程：24 小时飞书操作，宿主定时任务改为两个瞬时运行](https://github.com/Moke110/frontier/issues/61) 与 [#51 Windows 首次真实安装：私有环境移入数据根并完成端到端验收](https://github.com/Moke110/frontier/issues/51) 按本停止决定关闭；上述未取得项是该能力恢复验收时的检查清单。

## 2026-10-30 监听进程真实验收（进行中：机制证据已取得，命令 e2e 与到点触发待补）

本轮在目标宿主启动 spec [#61 监听进程：24 小时飞书操作，宿主定时任务改为两个瞬时运行](https://github.com/Moke110/frontier/issues/61) 的真实验收。机制证据（安装、任务集迁移、在线判定、杀进程恢复、停止、派生运行凭据）已取得；**真实飞书命令、反馈时延、08:00/09:00 到点触发与 ≥24 小时连续运行仍为 `untested`，不得据此宣称监听能力通过。**

| 项目 | 实测结果 |
|---|---|
| 监听进程安装 | `listener install` 生成 `<home>/bin/frontier-listener.cmd` 与停止脚本，`listener` 步骤 `ok`；`paths.dsh` = `D:\dsh\resources\runtime\cli\bin\dsh.cmd` |
| 任务集迁移 | `frontier-daily` 08:00 + `frontier-listener-check` 09:00（Asia/Shanghai）；`frontier-feedback` 移入 `schedules.retired_tasks`（旧宿主任务 `schedule-cb01bbc9-11f3-424e-abc1-7c39e98fadaf` 已于 2026-10-29 14:10 删除）；新 DSH 会话任务 daily `schedule-21ecfc84-7b7b-42ea-ac95-b94740972646`、listener-check `schedule-bb98dbf2-32af-45c7-971c-da2583682a82`；`schedules status` `created=true enabled=true`；`scheduled_run` 仍 `untested`（daily 尚未到点） |
| 在线判定 | 真实 `run --intent listener-check`：心跳新鲜，`state=online action=none` |
| 杀进程恢复 | 硬杀监听进程（pid 21816，`taskkill /F`）后，第二次真实 `listener-check` 返回 `action=restart_ok`，新 pid 在线 |
| 停止 | `listener stop` 返回 `state=stopped` |
| 派生运行凭据 | `dsh --profile headless --patch <home>/install/dsh-headless-account.patch.yml "..."` 真实运行成功并回答“可用测试”；`listener.dsh_args` 已记录该 patch |

### 本轮真实验收发现并修复的缺陷（`c3262a0`..`7e16203`，已并入 `main` `b046cb1`）

- 派生运行参数错误：传 `--prompt`，而 headless profile 以位置参数接收任务（`c3262a0`）。
- `event consume` 在飞书 i/o 超时后返回退出码 3，被误判为致命并杀掉健康监听进程；现仅 stderr 含 `app_scope_not_applied` 才致命，裸退出码 3 退避重试（`9b557dd`；日志 2026-10-30T16:19:20 记录崩溃与修复依据）。
- `listener stop` 等待 10 秒，而事件循环只在 30 秒分块之间检查停止哨兵；现改为 35 秒（`e9e6a0d`）。
- headless profile 无模型凭据（`MISSING_CREDENTIAL`，account/credentials 插件被禁用）；以通用方式记录 `listener.dsh_args = ["--patch", "<home>/install/dsh-headless-account.patch.yml"]` 修复并真实验证（`7e16203`）。

离线全量：**584 passed, 3 skipped**（修复后）。

### 仍缺（全部 `untested`，本轮不宣称通过）

1. 真实飞书命令端到端：`状态` 立即回复、`推一篇` 成功派生并回执或如实排队；
2. 反馈提交后 ≤10 分钟被处理至少一次；
3. `frontier-daily` 08:00 与 `frontier-listener-check` 09:00 的真实到点触发（手工 `run --intent listener-check` 的判定已取得，不计为到点证据）；
4. 监听进程连续运行 ≥24 小时、心跳覆盖全程、日志无崩溃重启。

因上述修复需重启进程，≥24 小时连续运行时钟从最终重启 **2026-10-30T16:45:52+08:00** 重新起算；16:12–16:19 那段运行因退出码 3 缺陷崩溃，仅记为缺陷依据，不计为干净运行。`listener_health` 的 09:00 到点证据与 `scheduled_run` 均保持 `untested`。

## 2026-10-29 监听进程方案（设计已定；当轮仅改文档）

用户要求：24 小时都能通过飞书操作 frontier，同时宿主定时任务只做瞬时运行、不长期挂着会话。决策见 [ADR 0008](../adr/0008-listener-process.md)。当轮**只改设计与文档/契约，未改代码**，未启动监听进程、未改动 DSH 现有调度、未写入飞书。

| 项目 | 约定 |
|---|---|
| 定时任务 | 两个瞬时任务：`frontier-daily` 每日 08:00、`frontier-listener-check` 每日 09:00；取消每小时反馈任务（历史 `frontier-feedback` 记录保留为过去证据，不再是目标状态） |
| 监听进程 | 用户手动启停的前台控制台进程（窗口标题 `frontier-listener`），bot 身份消费 `im.message.receive_v1`，只认 owner 单聊；命令白名单 `推一篇` / `处理反馈` / `状态` |
| 反馈处理 | 监听进程每 5 分钟执行 `run --intent feedback`；租约被占跳过本轮；无变化保持安静 |
| 派生运行 | 需要判断的工作以记录的 `dsh --profile headless` 绝对路径派生一次有界运行：单飞行、先取租约、≤20 分钟、失败不重试、写 `runs.jsonl` 标记 `derived`、飞书回执 |
| 巡检 | 心跳新鲜度（≤10 分钟）+ 进程存活 + 最近成功事件时间；不在线时拉起一次并 30 秒复查；证据记 `listener_health`，不套用 `scheduled_run` 的 ±5 分钟到点容差 |

验收门槛（任一缺失只能记 `untested`）：

1. 监听进程连续运行 ≥24 小时，心跳覆盖全程，日志无崩溃重启；
2. 至少一次真实飞书命令端到端（`状态` 立即回复；`推一篇` 成功派生或如实排队）；
3. 巡检至少一次真实执行并正确判定"在线"；
4. 人为杀掉监听进程后，巡检能发现并自动恢复一次；恢复不了就如实报告并停手；
5. 反馈提交后 ≤10 分钟被处理至少一次。

本轮已核实的现状（只读）：

- 本机当前**没有**任何监听进程；旧 lark 事件总线已干净退出，启动项中没有 frontier 相关条目。
- DSH 的两条调度为会话级提醒，挂在 `session-1f2834ce-…` 下；实测 13:05 投递、13:19 才执行，被运行日志的到点校验判为非到点运行。这说明"任务计划时间"与"实际执行时间"会分离，`scheduled_run` 证据要按启动时刻记录，且不能拿它衡量监听在线。
- bot 身份 ready；user 身份当前受 DPoP 存储影响（沙箱内读取受限，可能误报）。因此监听进程只用 bot 身份，不用 user 身份。
- `lark-cli event list` 确认 `im.message.receive_v1`（bot）可订阅；`event consume` 提供 `--max-events`、`--timeout` 与 `[event] ready event_key=…` 就绪标记，可作为单进程有界消费的基础。

当轮仍缺（全部 `untested`，后由实施票据 #62–#68 实现，见下一节）：监听进程实现与启停脚本、`listener` CLI 与 `listener_health` 证据、新两个任务的真实到点触发、上述 5 条验收门槛。<br>当轮列出的待同步代码与文档字符串——`hostrun/listener.py`、`hostrun/cli.py`、`hostrun/schedules.py`（任务集与巡检 intent）、`hostrun/intents.py`、`hostrun/__init__.py` 中"no detached listeners"的说明，以及退役 `trigger.service.listen` / `publisher.service.listen` 的引用——已由 #62–#68 完成；文档按退役处理。

## 2026-10-29 监听进程实现合入（离线回归通过；真实验收未执行）

实施票据 #62–#68 已把监听进程代码合入 `spec61-integration`（tip `e6e8433`），#69 在 `spec61-69` 做全量离线回归与契约一致性核对。本节只记录实现与离线证据，**不**把任何真实验收项写成通过。

| 项目 | 当前状态（2026-10-29，#69） |
|---|---|
| 代码 | `hostrun/listener.py`；`hostrun/cli.py`（`listener install|start|stop|status|serve|health`、`run --intent listener-check`）；`hostrun/intents.py`；`hostrun/schedules.py`（两个瞬时任务 + `retired_tasks` 迁移）；`hostrun/base.py`（`paths.dsh` 与 listener 配置）；`publisher/feishu.py`（有界事件消费）；安装流程的 `listener` / `listener_health` 步骤 |
| 离线回归 | 全量 **538 passed, 3 skipped**（`#69` 工作树 `spec61-69`；本分支基线 411 passed / 3 skipped；真实验收未执行） |
| 测试冲突修复 | `tests/test_hostrun_runtime.py` 中 #66 合并时重复定义的 5 个 schedule 测试已去重；`listener-check` 注册后删除过时的 fallback 分支 |
| 契约/文档对齐 | `contracts/README.md` §12 分步列表补 `listener` / `listener_health`；ADR 0008 状态与实现清单；ADR 0005 修订指针；`skills/frontier-run/references/installation.md` §3.7 补 `--dsh`；`deploy/README.md` 更正"不装常驻监听" |
| 产品代码缺陷 | 发现 1 项未修复：Windows `_pid_alive` 用 `OpenProcess(SYNCHRONIZE)` 判定，已终止但残留句柄的进程会被误报存活（影响杀进程恢复与 `listener stop`），建议改用 `WaitForSingleObject(...,0)==WAIT_TIMEOUT`；详见 #69 报告。产品代码未在 #69 修改 |
| 真实证据 | 上述 5 项验收门槛仍全部 `untested`：需真实 24h 运行、真实飞书命令、真实巡检、杀进程恢复与真实反馈时延；离线测试只覆盖契约形状 |

**不得**据本节宣称真实能力通过；真实证据补齐前 #61 的验收门槛维持 `untested`。

## 2026-10-29 真实端到端验收（DeepSeek Harness，用户授权 Full access；#53–#58 通过，#59 待到点触发）

用户明确授权把本会话权限切到 **Full access**（DSH 设置），以提供飞书 CLI 凭据存储（含 HKCU 注册表 keychain）所需写入权限；该授权是本轮通过账号层前置条件的显式决定，不是 agent 自行绕过。**本轮为真实读写：创建了独立 Base、真实检索、真实推送、用户本人在飞书评分与采纳、真实清理与正式知识写入。**

### 关键环境修复（非 code 变更，安装记录在此）

- **工作区低完整性标签**：DSH 的 ACL 沙箱曾把工作区文件标为 Low integrity；从工作区路径启动的解释器因此降级运行，lark-cli 无法访问 CNG/TPM 密钥库（`failed to acquire key storage lock`）。用 `icacls <python.exe> /setintegritylevel Medium` 修复代码目录与数据根两个 venv 的解释器后，`auth status` 恢复 user `ready`、DPoP `available`。这不是权限绕过，`-DiagnoseWindowsSandboxAcl` 判定为 `NOT_THIS_CLASS`（无 package ACE、无缺失 WRITE_DAC）。
- **DSH 事件回调**：卡片按钮需要 `lark-cli event consume card.action.trigger` 的长连接消费者在线；本轮以 `publisher.cli listen` 后台运行后，评分与采纳事件真实到达并写入队列。

### 真实结果（逐票据）

| 票据 | 真实证据 |
|---|---|
| #53 | `install check`：host/workspace/dependencies/skill/lark_cli/**identity/permissions 全部 ok**；真实 Base（`+table-list`）与 Drive 目录读取成功；报告不含 token |
| #54 | 新建 Base `CsCmbT96UaN5Z7sbsFqcWtpcnIe`（frontier 知识库），12 张契约表、原文/推送两个云盘目录；逐字段读回 `ok`，`facilities status` 结构完整 |
| #55 | 临时卡片 `card_smoke_…` 写入 Base；真实检索 40 条候选（arXiv 429 时为 20 条 EuropePMC）；`retrieved`/`written` 按序登记 |
| #56 | 七段推送 + 生成图渲染（65 KB 自包含 HTML）→ 推送库登记 → Drive 上传 → 真实送达飞书文件消息、评分卡、更新卡；**用户本人评分 `great`、本人采纳 `agree_all`**；写回后 Base 逐字段读回一致；七步 + `verified` 齐全，`test_loop=ok` |
| #57 | `cleanup run` 删除 3 条 Base 记录、撤回 1 条消息、删除 1 个云盘文件/3 个本地文件/2 个队列项；逐范围读回为空，`verified: true`，无残留、无不可撤回；`cleanup=ok` |
| #58 | 162 篇 PDF 全部摄取（可读 162/162，无缺口）；从真实全文提炼 9 张卡片草案，用户确认（草案哈希绑定）后写入正式 Base，读回一致；标准检索生成 18 条查询，`knowledge=ok` |
| #59 | 两个真实会话任务曾创建并确认（任务 ID + proof）。`frontier-feedback` 在 **14:05 真实到点触发并通过校验**：`scheduled=true`、proof 匹配、`at=14:05:04` 在 ±5 分钟内、`schedules trigger` 写入 `triggered_at`、`scheduled_runs=1`；13:05 首轮真实触发因完成时刻记录缺陷被拒，已修复（`a9f4edb`）。**2026-10-29 14:10 用户要求停止本会话的自动化任务**：已删除 DSH 两个会话提醒并 `schedules pause`（`enabled=false`），故 `frontier-daily` 不会再到点触发，**`scheduled_run` 保持 untested**。维护对账按契约报告 19 个分片孤儿差异（有差异退出码 1；无害、未删除）。<br>监听方式改由其他会话按 ADR 0008 实施（`spec61-*` 分支），本会话不再承担。 |

### 本轮修复的真实验收阻塞缺陷（`21b90fe`；离线 410 passed / 3 skipped）

`install check` runner 空指针；`base-create` 嵌套返回结构解析；ontology 文本单元格换行序列化与读回归一化；多词 ontology 精确短语召回为 0（改为逐词 OR 召回）；单一检索来源失败中断整条链路（保留 `source_errors` 继续）；publisher/library/knowledge 未使用记录的 lark-cli 绝对路径与 UTF-8 解码（`WinError 2`/解码崩溃）；`KL_HOME` 未随 `--home` 传入；Base 记录删除与消息撤回缺 `--yes` 被服务端拒绝；清理后的 `failed_cleaned` 永久阻塞新测试；rendered 校验错误要求同时出现两类图注（契约只要求图注可区分来源）。

### 仍缺

1. `scheduled_run`：小时任务曾在 14:05 通过真实到点校验（`triggered_at=14:05:04`、`scheduled_runs=1`）；**2026-10-29 14:10 用户要求停止本会话自动化任务**，两个 DSH 会话提醒已删除、`schedules pause` 已生效（`enabled=false`），因此 `frontier-daily` 不会再真实触发，`scheduled_run` 保持 untested，且不再在**本会话**补测。监听/巡检与新任务集由其他会话按 ADR 0008 实施与验收。
2. ~~GitHub 推送~~：代理恢复后已推送；远端由其他会话推进到 `eb24b2f`（ADR 0008 文档），本轮验收提交均已在远端历史中。
3. ~~旧卡片残留~~：早前中止轮次的卡片消息已按消息 ID 撤回并逐条读回：5 条此前仍在的消息全部撤回且确认已消失，3 条文件消息此前已由清理撤回。

## 2026-10-29 安装工作区重试（数据根可写；飞书凭据存储与 user 身份仍阻塞）

本轮把 DeepSeek Harness 0.2.1-rc.3 的会话工作区改为**安装工作区** `E:\Desktop\frontier-dev`：代码目录 `frontier` 与数据根 `frontier-archive` 为同级子目录，数据根不再落在会话工作区之外。**未创建 Base、未发送任何消息、未创建宿主任务、未删除任何云端数据。**

| 项目 | 实测结果 |
|---|---|
| 工作区与数据根 | `install workspace --root E:\Desktop\frontier-dev --repo-url …` → `ok`，`layout_valid: true`；数据根 `frontier-archive` 创建/复用成功，指针 `.frontier/install.json` 记录 root/repo/home 三个独立路径 |
| 数据根写入 | 真实临时探针写入并删除成功（`install check` 的 `writes.data_root.status: ok`） |
| 私有解释器 | `install toolchain --root E:\Desktop\frontier-dev` → `ok`；uv 0.11.19 在数据根创建 CPython 3.13.13，`yaml`/`fitz` 导入自检通过；解释器、venv、uv 路径写入安装配置 |
| 依赖来源（非纯在线） | 宿主对 `files.pythonhosted.org` 的大文件传输长时间停滞：PyMuPDF 2.0（60.1 MiB）、numpy（12.0 MiB）、onnxruntime（14.2 MiB）经 uv 与 Node 直连均在数分钟内无进展；累计约 100 MB 后停住。依赖包因此取自工作区已有 uv 环境 `frontier\.venv` 的同版本安装（PyYAML 6.0.3、PyMuPDF 2.0 等），随后由官方 `install toolchain` 记录并通过导入自检。**这不是 `uv pip install -r requirements.txt` 的完整真实下载证据**；网络恢复后应按官方路径重建并复核。 |
| 飞书 CLI | `lark discover --cli <npx 缓存绝对路径>` → `ok`（1.0.98），绝对路径写入安装配置（ADR 0007）；PATH 中的 `lark-cli.cmd` 首次运行仍因 EPERM 写 `D:\nodejs` 失败 |
| 身份 | bot `ready`/`verified`；user `missing`（DPoP `failed to acquire key storage lock`，`dpopKeyStatus: missing`；令牌 `needs_refresh`，刷新窗口至 2026-11-03 23:56） |
| 授权与资源 | `lark status`：CLI `ok`、授权范围 `ok`（用户令牌已授予 222 项细粒度 scope，含 `base:*`、`drive:file:*`、`im:message`）；user 身份不可用时真实 Base/Drive 读取全部 `untested` |
| 技能入口 | `install skill --target C:\Users\Chang\.agents\skills\frontier-run` → `PermissionError [WinError 5]`；宿主技能目录不可写，`skill` 步骤 `blocked` |
| 权限预检 | `install check` 的 `permissions` → `blocked`：数据根探针 `ok`；`C:\Users\Chang\.lark-cli` 探针 `PermissionError`；DPoP 密钥库锁位于 `%LOCALAPPDATA%\lark-cli\keysigner\key_store.lock`，同样不可达 |
| 报告 | `install report`：`working = [host, workspace, dependencies, lark_cli]`；`blocked = [skill, identity, permissions]`；`facilities/test_loop/cleanup/knowledge/schedules/scheduled_run` 仍 `pending` |
| 研究输入 | 工作区 `PDFs` 含 162 个 PDF（路径由 `E:\Desktop\PDFs` 变为 `E:\Desktop\frontier-dev\PDFs`）；本轮仅核对数量，未重新执行全文提取 |
| 离线代码基线 | **395 passed, 3 skipped**（在 `0bbc2c9` 上修复下列 4 个验收阻塞缺陷后） |

本轮修复的验收阻塞缺陷（均已补离线测试）：

| 缺陷 | 影响 | 修复 |
|---|---|---|
| `hostrun.lark.user_open_id` 在 user 身份不可用时仍返回缓存的 open_id | 收件人核验会在身份未就绪时错误通过，违背 #56 “身份未就绪返回 `recipient_unverified`” | 复用 `parse_auth` 的同一就绪规则；未就绪一律 `ok: false` |
| `publisher.feishu` 只从 PATH 调用裸 `lark-cli` | 裸命令名不会解析到 PATH 中的 `.cmd` 垫片（CreateProcess 不做 PATHEXT 扩展），真实发送与事件监听必然 `FileNotFoundError`；且数据根没有通过 `--home` 传给 publisher，记录路径查不到，即使权限齐全也无法完成 #56 投递 | 优先使用 `install/config.json` 记录的绝对路径，记录失效即拒绝并给出 `lark discover` 指引；`publisher.cli` 现在把 `--home` 解析出的数据根导出为 `KL_HOME` 供记录查找；临时闭环 brief 的 send 命令与日常 pipeline brief 都补上 `--home` |
| `publisher.cli` 缺少 `deliver` 子命令 | `workflow.md` 与 `hostrun/intents.py` 指引的恢复命令不可用 | 补上 `deliver --to/--dry-run/--as` 解析 |
| `hostrun.workspace.register_skill` 在宿主技能目录不可写时抛未捕获异常 | `install skill` 以 traceback 结束而非记录 `blocked`，安装报告无法如实分项 | 返回 `skill_target_not_writable` 的 blocked 结果并说明所需宿主授权 |

### 结论与仍缺的真实证据

数据根写入与私有解释器两个历史阻塞已在正确的安装工作区中解除；`host`、`workspace`、`dependencies`、`lark_cli` 四项为 `working`。真实端到端闭环仍阻塞于宿主与账号层前置条件，不属于本轮代码可修复范围：

1. **DeepSeek Harness 需允许飞书 CLI 凭据存储写入**：`C:\Users\Chang\.lark-cli` 与 `%LOCALAPPDATA%\lark-cli\keysigner`（DPoP 密钥库锁）当前对沙箱进程树只读。需要宿主权限（窄范围路径放行或等价授权），不是解释器位置问题，也不能用“全局完全访问”或迁移凭据绕过。
2. **飞书 user 身份需重新可用**：凭据存储可写后由用户本人执行 `lark-cli auth login`；刷新窗口到 2026-11-03 23:56，过期需重新登录。
3. **宿主技能目录需可写**：`C:\Users\Chang\.agents\skills` 当前拒绝写入；需要宿主允许该路径，或确认 DSH 支持的工作区内技能目录后再注册 `frontier-run` 入口指针。
4. 应用 scope 以用户令牌计已具备；`drive files list --as bot` 仍报 app 缺 `drive:drive` 等，bot 不作为验收路径，记录在案。

在上述前置条件就绪前 #53–#59 保持开放，不宣称通过；本轮未写入任何真实飞书数据。

## 2026-10-29 DeepSeek Harness 重新预检（真实只读；未写云端）


本轮在 DeepSeek Harness 0.2.1-rc.3（`D:\dsh\DeepSeek Harness.exe` 的产品版本；会话工作区 `E:\Desktop\frontier`，策略 workspace-write）重新执行规格 #51 要求的权限预检。**未创建 Base、未发送消息、未创建宿主任务、未删除任何云端数据。**

| 项目 | 实测结果 |
|---|---|
| 数据根写入 | 创建 `E:\Desktop\frontier-archive` 失败（`E:\Desktop` 不可写）；在 `E:\Desktop` 内写探测文件被拒绝（Access denied）。会话工作区 `E:\Desktop\frontier` 与会话临时目录可写。 |
| CLI 凭据存储写入 | 写 `%USERPROFILE%\.lark-cli` 被拒绝（Access denied）。`lark-cli auth status --json --verify` 告警 `local DPoP setup failed ... failed to acquire key storage lock`；`dpopKeyStatus: missing`。 |
| CLI 可执行 | `lark-cli 1.0.98`（npx 缓存中的绝对路径）可运行。 |
| 身份 | bot `ready` 且 `verified: true`；user `missing`（DPoP 密钥不可用；令牌 `needs_refresh`，刷新窗口至 2026-11-03）。 |
| 授权 / 真实资源读取 | user：`drive files list --as user` → 退出码 5，`file_io: failed to acquire token storage lock`；bot：→ 退出码 3，`app_scope_not_applied`，缺 `drive:drive`、`drive:drive:readonly`、`space:document:retrieve`。真实 Base 与 Drive 读取均未成功。 |
| 研究输入 | `E:\Desktop\PDFs` 的 162 个 PDF 全部可提取（3046 页、13,573,742 字符；提取失败 0）。这只是可读性证据，未执行正式初始化。 |

结论：#53 的真实预检仍然阻塞，阻塞项为（1）宿主对数据根与 CLI 凭据存储的写入权限；（2）飞书 user 身份（DPoP 存储锁）；（3）应用未申请 Drive scope。三者都是宿主/账号层前置条件，属于需要用户完成的登录、授权与宿主权限，不能通过移动解释器、重建数据根或改用全局完全访问绕过。因此 #53–#59 继续保持开放；本轮不宣称任何真实闭环通过。

**会话边界。** 安装设计要求宿主会话的工作区是“安装工作区”，即同时包含代码目录与数据根两个子目录的宿主项目文件夹（README 的“工作区”）。本次会话工作区是代码目录 `E:\Desktop\frontier` 本身，数据根 `E:\Desktop\frontier-archive` 因而位于会话工作区之外，这是本轮数据根写权限阻塞的直接原因之一；需要在以安装工作区（例如 `E:\Desktop`）为工作区的宿主会话中重新预检。CLI 凭据存储位于用户目录（`%USERPROFILE%\.lark-cli`），即使工作区正确也仍需宿主允许该路径写入；前置条件未具备时按要求记录 blocked，不迁移凭据。

## 2026-10-29 规格 #51 修订标准补全（离线完成；真实验收未执行）

2026-10-28 首次实现后，规格 #51 与 #53–#59 的验收标准于当晚更新，新增了写权限预检、既有库只读预检、独立新 Base、临时卡片隔离、收件人核验与提交/发送证据、清理消息读回、到点触发与知识就绪闸门等要求。本轮按更新后的标准补齐代码与离线测试：

| 票据 | 补全内容 | 离线测试 |
|---|---|---|
| #53 | 数据根与 CLI 凭据存储写权限探针（写后即删，拒绝即 `blocked`）；DPoP 状态进入报告；`lark status` / `install check` 支持显式 Base/目录 token 的只读预检且不接入既有库；依赖导入探针含 PyMuPDF | `test_hostrun_install.py`、`test_hostrun_lark.py` |
| #54 | `facilities create` 不再按同名自动收养既有库，而是创建独立新 Base；同名既有库只在 plan 中提示、不改动；重跑仍按记录 ID 幂等 | `test_hostrun_facilities.py` |
| #55 | 正式检索加载知识卡片时排除 `card_smoke_*` 临时卡片，临时检索式不进入日常输入 | `test_frontier.py`、`test_hostrun_smoke.py` |
| #56 | 收件人必须是已认证 user 的 open_id；评分/采纳须有用户本人提交的已提交答案且与记录一致；发送前登记尝试，结果不明时拒绝盲目重发并可对账；`rendered` 须关联本次测试的推送库记录 | `test_hostrun_smoke.py`、`test_publisher.py` |
| #57 | 撤回消息后读回确认；清理报告按 Base、消息、云盘文件、本地文件与队列分范围给出删除计数 | `test_hostrun_cleanup.py` |
| #59 | 触发证据须落在任务计划窗口内（每日 08:00 / 每小时第 5 分钟，15 分钟启动容忍）；`host_created` 一律要求知识就绪，暂停路径同样拒绝 | `test_hostrun_schedules.py` |

离线全量：**386 passed, 3 skipped**（本机 `python -X utf8 -m pytest -q … tests`，pytest 临时目录使用本地 shim，未进入仓库）。本轮未执行真实 Base/Drive 读取、真实推送与用户评分/采纳、清理读回、正式知识初始化或到点触发；#53–#59 的缺口与阻塞见各自票据评论，票据保持开放。

## 2026-10-28 文档与规格修订（未执行真实验收）

本轮仅统一安装说明并修订规格 #51，未新增真实飞书读写、用户评分与采纳、清理读回、正式初始化或宿主定时触发证据。#53–#59 保持开放；本轮研究输入与调度选择仅记录在 GitHub 规格，不在此维护任务副本。

下一轮在 DeepSeek Harness 重新核实数据根及 CLI 凭据存储权限，再推进 #51 的新库验收链；私有解释器的位置不能证明沙箱权限已解除。设施按现行 12 表契约验收，两类任务各需真实触发。其他宿主与存量恢复继续按各自票据独立验收。

## 2026-10-28 规格 #51 实现（离线完成；真实验收阻塞）

用户当日决定：本轮只实现代码与离线测试，真实验收记为阻塞，不写入真实飞书数据。宿主机当时记录为 DeepSeek Harness 44.7.0（2026-10-27 的历史版本号；2026-10-29 重新预检时产品版本为 0.2.1-rc.3，见上节；[ADR 0006](../adr/0006-deepseek-harness-as-a-host.md)），其 workspace-write 策略实测把整个进程树限制在会话工作区与会话临时目录：

- 允许写 `E:\Desktop\frontier` 与会话临时目录；拒绝写 `E:\Desktop\frontier-archive`、`%USERPROFILE%\.lark-cli`、`C:\Python314`、`D:\nodejs`。
- 用仓库 `.venv` 解释器、`C:\Python314\python.exe` 与 `node.exe` 分别验证，结果一致：限制与解释器位置、工作目录无关。因此规格“把解释器移到数据根即可写 CLI 令牌存储”的假设在本机不成立。
- 飞书 CLI 1.0.98 可执行文件存在（`D:\nodejs\node_cache\_npx\…\@larksuite\cli\bin\lark-cli.exe`）；`auth status` 显示 bot `ready`，user `missing`（DPoP key storage lock 无法获取），bot 调用 Drive 因 app 未申请 `drive:*` scope 被拒。真实 Base/Drive 读取未执行。

| 阶段 | 代码与离线证据 | 真实证据 | 结论 |
|---|---|---|---|
| workspace（数据根私有解释器） | `hostrun/workspace.py`、`install.py`；`tests/test_hostrun_workspace.py`、`tests/test_hostrun_install.py` | 用 `C:\Python314\python.exe` 执行 `install workspace`：数据根创建、指针写入、代码目录 `git status` 为空；`install toolchain --uv D:\uv\uv.exe` 在数据根创建 Python 3.13.13 环境，解释器路径在代码目录之外 | 代码与离线验收通过；真实依赖下载未在时限内完成，导入探针仅离线覆盖 |
| lark_cli | `hostrun/lark.py`、`install.py`；绝对路径权威、失效即 `blocked`、`lark discover` 持久化 | 可执行存在且可运行；记录路径 | 代码与离线验收通过；真实 `discover` 持久化未执行 |
| identity / permissions | 同一就绪规则、user/bot 分列、`needs_refresh` 窗口、细粒度 scope 与旧宽授权、缺项列出、报告脱敏；数据根与 CLI 凭据目录的临时探针写入实测；DPoP 状态词；`--base-token/--folder` 只读预检既有库且不写设施 | user `missing`（DPoP 存储锁）；bot `ready` 但缺 drive/base app scope | 离线通过；真实写入权限与 Base/Drive 读取 blocked |
| facilities | 12 张契约表 + 字段级读回 + 两个云盘目录 + 稳定 ID + 改名不改 ID + 幂等 | 未创建（未写飞书） | 离线通过；真实创建 untested |
| test_loop | 测试标识、`retrieved` 从真实 `--plan` 产物取候选数、`written` 选中论文 ID、`rendered` 按 `writer/render.py` 契约校验七段与原文图/生成图图注、评分先于采纳、`verify` 累计逐字段读回 | 未推送、未评分、未采纳 | 离线通过；真实闭环 untested |
| cleanup | 按测试 ID 与记录 ID 删除、消息撤回、逐范围读回、报道表作用域、失败中止、初始化闸门、幂等 | 未删除任何云端数据 | 离线通过；真实清理 untested |
| knowledge | intake 闸门、草案确认绑定、归一化字段级读回、拒绝覆盖既有卡片（快照失败即拒绝提案）、标准检索 | 未初始化正式知识 | 离线通过；真实初始化 untested |
| schedules | 两类宿主任务、绝对解释器/数据根/仓库/技能、触发校验、暂停与恢复、报告区分创建与触发 | 未创建任务、无到点触发 | 离线通过；真实触发 untested |

离线全量：**331 passed, 3 skipped**（在本机用 `python -X utf8 -m pytest -q … tests`；本机 pytest 临时目录需要本地 shim，未进入仓库）。逐票据的离线验收证据见对应 GitHub 票据评论；真实证据缺口见下方“宿主与恢复”和“下一次真实验收”。

结论：规格 #51 的代码与离线验收完成；真实端到端验收仍因宿主写策略与飞书身份/scope 阻塞。#52 与 #60 可按离线证据关闭，#53–#59 保持开放并在票据中记录缺口。

## 2026-10-27 首次 Windows 真实安装（进行中，未改动飞书数据）

目标宿主为 [DeepSeek Harness 44.7.0](../adr/0006-deepseek-harness-as-a-host.md)（2026-10-27 当时版本；第三款运行宿主）；飞书 CLI 复用用户已配置的 `@larksuite/cli` 1.0.98（[ADR 0007](../adr/0007-reuse-configured-lark-cli.md)），实际可执行文件在 npx 缓存中。代码目录 `E:\Desktop\frontier`（`dev`），数据根 `E:\Desktop\frontier-archive`。

已取得的真实只读证据：

| 项目 | 证据 |
|---|---|
| CLI 可执行 | `lark-cli 1.0.98` 可运行；全局 `lark-cli.cmd` 首次运行自装平台二进制失败（`EPERM` 写 `D:\nodejs`），不影响显式指定缓存路径 |
| 身份 | `auth status --json --verify`：`verified: true`；bot ready；user 状态 `needs_refresh` 但刷新窗口到 2026-11-03，实际调用自动续期；DPoP 密钥 `available` |
| 授权范围 | 租户授予细粒度 scope（`base:*`、`drive:file:*`、`im:message` 等），覆盖 frontier 所需能力 |
| Drive 读取 | `drive files list --as user` 成功；根目录含「frontier」目录与两个 bitable |
| Base 读取 | `base +table-list` 成功 |
| 既有租户设施 | Base「frontier 知识库」`B39T…`：知识卡片 10、命题 6、证据 5、报道 10、变更日志 6、原文 175、推送日志 0、决定 0、配置 1；缺「问题/反馈/更正」三张反馈表。云盘「frontier」`TtbM…` 下有「原文」「推送」两个目录 |

代码改动（已提交 `dev`）：`lark status` 与安装报告改用当前细粒度 scope 判定，兼容旧宽授权；`needs_refresh` 在刷新窗口内视为可用；两处身份判定合并为同一规则。离线结果：**270 passed, 3 skipped**。

阻塞（未执行任何写操作的原因）：当时观察到宿主沙箱对**位于工作区内部的可执行文件**施加写入限制：仓库 `.venv` 的 `python.exe` 与复制进仓库的 `python.exe` 只能写 `E:\Desktop\frontier`，创建 `E:\Desktop\frontier-archive`、写 `%USERPROFILE%\.lark-cli` 均返回 `WinError 5`。影响：按 [ADR 0005](../adr/0005-agent-owned-execution.md) 放在"仓库内"的 uv 环境无法创建数据根、也无法驱动 lark-cli 的令牌存储，`install workspace` 在写 `.frontier` 指针时即失败。

**2026-10-28 复核更正：** 用仓库 `.venv`、`C:\Python314\python.exe` 与 `node.exe` 分别重测，三者同样被拒绝写工作区外路径，且与执行目录无关；即限制针对整个被沙箱化的进程树，不只针对"工作区内部的可执行文件"。因此把解释器移到数据根不能解除 `%USERPROFILE%\.lark-cli` 的写入限制；见上文 2026-10-28 一节。

决定（2026-10-27 记录；代码已于 2026-10-28 实现）：私有 uv 环境与解释器移到数据根内，代码目录只保留代码，uv 从工作区外解析；见 [ADR 0005 修订](../adr/0005-agent-owned-execution.md) 与规格 [#51](https://github.com/Moke110/frontier/issues/51)。

本轮**未**创建 Base、未发送消息、未建定时任务；`install` 各阶段仍为 pending，真实 `smoke`/`cleanup`/`init`/`schedules` 均未实测。

## 2026-10-27 安装增量（#41 的子票据）

本轮实现了工作区/uv、飞书 CLI 预检、设施创建、关键词临时闭环、精确清理、正式知识初始化和两类宿主任务。离线证据：

| 能力 | 代码 | 离线测试 |
|---|---|---|
| 工作区获取/复用、私有 uv、uv 解释器、`frontier-run` 指针 | `hostrun/workspace.py` | `tests/test_hostrun_workspace.py`（16） |
| CLI 发现/私有安装、登录状态、授权范围、Base/Drive 读取预检 | `hostrun/lark.py`、`library/admin.py` | `tests/test_hostrun_lark.py`（12） |
| Base 本身/表/目录创建、确认命名、稳定 ID、同名去重、已有库接入 | `hostrun/facilities.py` | `tests/test_hostrun_facilities.py`（11） |
| 关键词临时卡片、步骤状态机、读回验证 | `hostrun/smoke.py` | `tests/test_hostrun_smoke.py`（9） |
| 按测试 ID 清理、删除读回、不可撤回/残留报告、幂等重跑、私有 CLI 撤回 | `hostrun/cleanup.py` | `tests/test_hostrun_cleanup.py`（8） |
| 文献/要求摄取、卡片校验、用户确认、写入飞书、标准检索、已有库导入 | `hostrun/initialize.py` | `tests/test_hostrun_initialize.py`（11） |
| 两类任务、小时维护、启用闸门、任务 ID 去重、真实触发证据 | `hostrun/schedules.py`、`hostrun/intents.py` | `tests/test_hostrun_schedules.py`（10） |

本机（2026-10-27）全量离线结果：**265 passed, 3 skipped**（PyMuPDF 2.0 已安装，含 `tests/test_initial_build.py` 与 `tests/test_pdf_ingest.py`）；当日另一条记录为 **270 passed, 3 skipped**（见上节），差异来自记录时点不同。2026-10-28 规格 #51 实现后为 **318 passed, 3 skipped**，代码审查修复后为 **331 passed, 3 skipped**。这些是离线测试，不等于真实文献库或真实租户已通过。

仍缺的真实证据：

1. 2026-10-27 时本机没有可用的 `lark-cli`；2026-10-28 已定位并验证可执行文件 1.0.98，但 user 身份因 DPoP 存储锁不可用、bot 缺 drive/base app scope，`lark status`、设施创建、真实推送与反馈仍未真实执行；只有进程边界与离线 Base/Drive 测试。详见 2026-10-28 一节。
2. 两款宿主的**内置调度真实触发**与无人值守权限仍无证据；`schedules trigger` 只接受运行日志中的 `scheduled=true` 记录，手动调用不计。
3. 真实飞书展示、评分、采纳写入、消息撤回和清理读回需要目标租户与用户操作。
4. 真实文献库的 PDF 摄取、原文登记与卡片证据核对仍需在目标环境执行；离线 PDF 测试只证明本地摄取链。

因此 #42–#48 的代码与离线验收标准已满足；#49/#50 保持开放，直到真实宿主与飞书证据齐全。

## 宿主与恢复

| 范围 | 已有证据 | 尚缺证据 | 任务 |
|---|---|---|---|
| ChatGPT 本地宿主 | 安装续接、知识库和队列机制有离线测试 | 具体版本与权限、真实新装/恢复、本地定时触发、离线反馈续接 | [ChatGPT 接入与本地定时验收](https://github.com/Moke110/frontier/issues/37) |
| WorkBuddy 本地宿主 | 历史开发会话验证过项目访问、技能加载、本地命令 | 内置调度实际触发、无人值守权限、真实飞书闭环 | [WorkBuddy 接入与本地定时验收](https://github.com/Moke110/frontier/issues/38) |
| 云端存量恢复 | 基线核对、分片顺序、配额计算与故障测试；空库会正确报告缺失 | 真实 174 篇核对、云端恢复演练、配额实测与连续三天零差异 | [存量核对与云端恢复验收](https://github.com/Moke110/frontier/issues/39) |
| 安装说明 | 现行用户入口与运行时技能已统一 | 在目标宿主按最终说明完成新装、恢复并留证 | [统一安装说明并退役旧部署入口](https://github.com/Moke110/frontier/issues/40) |
| 新安装增量 | 工作区、uv、CLI 预检（含写入权限探针、DPoP 状态与只读既有资源预检）、设施、临时闭环、清理、正式知识、两类任务均有离线测试；规格 #51 的 #52–#59 代码已合入 `dev`，离线 386 passed / 3 skipped | 真实 CLI/租户/宿主触发；真实 Base/Drive 读、推送/评分/采纳、清理读回、正式初始化与到点触发 | [#41](https://github.com/Moke110/frontier/issues/41) 的子票据 #42–#50；#51 的子票据 #52–#60 |

核对时发现 ChatGPT 任务已被标为关闭，但其最后一条验收评论仍写“未实测”，未附新的通过证据；因此本表保留证据缺口，不以 issue 状态推断验收通过。后续执行者须先核对关闭原因与最新证据；本轮不更改 tracker 状态。

2026-10-27 的原始安装检查只确认 `dependencies: ok`；当时 `lark_cli/identity: blocked`、`host: untested`，其余步骤 pending。它描述当时环境，不能当作当前安装检查；后续必须重新探测。原 WorkBuddy 开发解释器已失效，也不能沿用其 venv 作为有效安装证据。

空库恢复演练的原始结果为 `baseline_expected: 174`、`registered_sources: 0`、`missing: 174`、`zero_diff: false`、`streak: 0`。这证明核对工具没有把空库误报为完整恢复，不证明真实数据已经恢复。

## 下一次真实验收

0. 在实际目标宿主重新实测数据根与飞书 CLI 的令牌/DPoP 存储写入权限；2026-10-29 的实测见本轮预检，两者仍被拒绝。宿主的会话工作区必须是安装工作区（同时包含代码目录与数据根两个子目录）；以代码目录为工作区的会话无法创建数据根。数据根私有解释器不能解除该限制。必要权限未具备时记录 `blocked`，不能开始真实闭环。
1. 由宿主按 [用户安装流程](../../README.md) 准备私有依赖并引导用户完成飞书授权，连接实际 Base。仅报告身份状态，不输出凭据。
2. 分别在目标宿主验证版本、工作目录、技能、权限，以及两类任务各至少一次真实到点触发；保存任务配置、时间、运行输出和反馈续接记录。一款宿主的结果不能替代另一款。
3. 使用 `fixtures/pdf-manifest.jsonl` 复核历史 174 篇原文，只补实际缺口；检查分片、原文关联、测试推送引用和配额差异（小于 1%）。不得将上传失败改成无原件来通过验收。
4. 在真实库上执行 `audit run --baseline <manifest> --record`，取得连续三个实际执行自然日的零差异记录，再用 `audit streak` 验证；不模拟日期或伪造补跑。
5. 在独立可丢弃目录从云端恢复知识、已发问题与决定，按需下载原文并完成一篇推送。不删除原工作目录、唯一离线备份或用户云端资料。
6. 将结果和原始证据追加到对应 GitHub issue；只在满足验收条件后关闭任务。稳定、可复现的结论可精炼到本表，原始长日志留在 issue 或相应工件。

## 历史证据

旧环境的成功记录只证明当时的 WSL/systemd 或迁移阶段，不证明现在的宿主方案通过。完整历史固定在清理前提交，避免工作区重复维护长日志：

- [2026-10-21 首轮端到端](https://github.com/Moke110/frontier/blob/978cbfc/docs/acceptance/2026-10-21-e2e.md)：曾有自动续推与重复论文问题。
- [2026-10-22 端到端复验](https://github.com/Moke110/frontier/blob/978cbfc/docs/acceptance/2026-10-22-e2e-followup.md)：旧服务模式下两项问题修复通过。
- [命题 v3 与 HTML](https://github.com/Moke110/frontier/blob/978cbfc/docs/acceptance/2026-10-22-v3-phase2.md)、[Bitable 镜像](https://github.com/Moke110/frontier/blob/978cbfc/docs/acceptance/2026-10-22-bitable-phase3a.md)：当时的功能与切换边界。
- [宿主原始检查](https://github.com/Moke110/frontier/blob/978cbfc/docs/acceptance/2026-10-27-host-matrix.md)、[云端恢复原始检查](https://github.com/Moke110/frontier/blob/978cbfc/docs/acceptance/2026-10-27-cloud-recovery.md)。
- [v1 到 v2 迁移记录](https://github.com/Moke110/frontier/blob/978cbfc/docs/migrations/2026-10-20-v1-to-v2.md)。旧 Base 回填结果另见 [旧迁移任务](https://github.com/Moke110/frontier/issues/28) 的历史评论，当前工作仍需复核。
