# 验收记录与待补证据

本文件只记录验收证据与缺口，不替代 [GitHub 任务](https://github.com/Moke110/frontier/issues/29)。以下按日期归并证据；规格 [#51](https://github.com/Moke110/frontier/issues/51) 的历史离线实现与本轮文档修订分开记录。历史阻塞须在目标宿主重新探测，不能直接当作当前结果。代码通过离线测试不等于产品通过真实验收。

## 2026-10-29 监听进程方案（设计已定；代码与真实验收均未执行）

用户要求：24 小时都能通过飞书操作 frontier，同时宿主定时任务只做瞬时运行、不长期挂着会话。决策见 [ADR 0008](../adr/0008-listener-process.md)。本轮**只改设计与文档/契约，未改代码**，未启动监听进程、未改动 DSH 现有调度、未写入飞书。

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

仍缺（全部 `untested`）：监听进程实现与启停脚本、`listener` CLI 与 `listener_health` 证据、新两个任务的真实到点触发、上述 5 条验收门槛。<br>需要同步修改的代码与文档字符串：`hostrun/listener.py`、`hostrun/cli.py`、`hostrun/schedules.py`（任务集与巡检 intent）、`hostrun/intents.py`、`hostrun/__init__.py` 中"no detached listeners"的说明，以及退役 `trigger.service.listen` / `publisher.service.listen` 的引用（文档已按退役处理）。

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
| #59 | 两个真实会话任务已创建并确认（任务 ID + proof）。`frontier-feedback` 在 **14:05 真实到点触发并通过校验**：`scheduled=true`、proof 匹配、`at=14:05:04` 在 ±5 分钟内、`schedules trigger` 写入 `triggered_at`、`scheduled_runs=1`；13:05 首轮真实触发因完成时刻记录缺陷被拒，已修复（`a9f4edb`）。`frontier-daily` 尚未到点（次日 08:00），因此 **`scheduled_run` 仍为 untested**。维护对账按契约报告 19 个分片孤儿差异（有差异退出码 1；无害、未删除）。<br>注：ADR 0008 计划改为“监听进程 + 每日 08:00 与 09:00 巡检两个瞬时任务”，其代码在 `spec61-*` 分支尚未并入 `dev`；本条验收基于当前 `dev` 代码。 |

### 本轮修复的真实验收阻塞缺陷（`21b90fe`；离线 410 passed / 3 skipped）

`install check` runner 空指针；`base-create` 嵌套返回结构解析；ontology 文本单元格换行序列化与读回归一化；多词 ontology 精确短语召回为 0（改为逐词 OR 召回）；单一检索来源失败中断整条链路（保留 `source_errors` 继续）；publisher/library/knowledge 未使用记录的 lark-cli 绝对路径与 UTF-8 解码（`WinError 2`/解码崩溃）；`KL_HOME` 未随 `--home` 传入；Base 记录删除与消息撤回缺 `--yes` 被服务端拒绝；清理后的 `failed_cleaned` 永久阻塞新测试；rendered 校验错误要求同时出现两类图注（契约只要求图注可区分来源）。

### 仍缺

1. `scheduled_run`：小时任务已在 14:05 通过真实到点校验（`triggered_at=14:05:04`、`scheduled_runs=1`）；**每日任务需在次日 08:00 真实触发一次**，两类任务都有证据后该步骤才会转 ok。若 ADR 0008 的监听进程设计落地，任务集改为 08:00 + 09:00 两个瞬时任务，需按新任务集重新验收（ADR 明确 `listener_health` 不复用 `scheduled_run` 的到点容差）。
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
