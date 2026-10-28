# 验收记录与待补证据

本文件只记录验收证据与缺口，不替代 [GitHub 任务](https://github.com/Moke110/frontier/issues/29)。以下按日期归并证据；规格 [#51](https://github.com/Moke110/frontier/issues/51) 的历史离线实现与本轮文档修订分开记录。历史阻塞须在目标宿主重新探测，不能直接当作当前结果。代码通过离线测试不等于产品通过真实验收。

## 2026-10-28 文档与规格修订（未执行真实验收）

本轮仅统一安装说明并修订规格 #51，未新增真实飞书读写、用户评分与采纳、清理读回、正式初始化或宿主定时触发证据。#53–#59 保持开放；本轮研究输入与调度选择仅记录在 GitHub 规格，不在此维护任务副本。

下一轮在 DeepSeek Harness 重新核实数据根及 CLI 凭据存储权限，再推进 #51 的新库验收链；私有解释器的位置不能证明沙箱权限已解除。设施按现行 12 表契约验收，两类任务各需真实触发。其他宿主与存量恢复继续按各自票据独立验收。

## 2026-10-28 规格 #51 实现（离线完成；真实验收阻塞）

用户当日决定：本轮只实现代码与离线测试，真实验收记为阻塞，不写入真实飞书数据。宿主机为 DeepSeek Harness 44.7.0（[ADR 0006](../adr/0006-deepseek-harness-as-a-host.md)），其 workspace-write 策略实测把整个进程树限制在会话工作区与会话临时目录：

- 允许写 `E:\Desktop\frontier` 与会话临时目录；拒绝写 `E:\Desktop\frontier-archive`、`%USERPROFILE%\.lark-cli`、`C:\Python314`、`D:\nodejs`。
- 用仓库 `.venv` 解释器、`C:\Python314\python.exe` 与 `node.exe` 分别验证，结果一致：限制与解释器位置、工作目录无关。因此规格“把解释器移到数据根即可写 CLI 令牌存储”的假设在本机不成立。
- 飞书 CLI 1.0.98 可执行文件存在（`D:\nodejs\node_cache\_npx\…\@larksuite\cli\bin\lark-cli.exe`）；`auth status` 显示 bot `ready`，user `missing`（DPoP key storage lock 无法获取），bot 调用 Drive 因 app 未申请 `drive:*` scope 被拒。真实 Base/Drive 读取未执行。

| 阶段 | 代码与离线证据 | 真实证据 | 结论 |
|---|---|---|---|
| workspace（数据根私有解释器） | `hostrun/workspace.py`、`install.py`；`tests/test_hostrun_workspace.py`、`tests/test_hostrun_install.py` | 用 `C:\Python314\python.exe` 执行 `install workspace`：数据根创建、指针写入、代码目录 `git status` 为空；`install toolchain --uv D:\uv\uv.exe` 在数据根创建 Python 3.13.13 环境，解释器路径在代码目录之外 | 代码与离线验收通过；真实依赖下载未在时限内完成，导入探针仅离线覆盖 |
| lark_cli | `hostrun/lark.py`、`install.py`；绝对路径权威、失效即 `blocked`、`lark discover` 持久化 | 可执行存在且可运行；记录路径 | 代码与离线验收通过；真实 `discover` 持久化未执行 |
| identity / permissions | 同一就绪规则、user/bot 分列、`needs_refresh` 窗口、细粒度 scope 与旧宽授权、缺项列出、报告脱敏 | user `missing`（DPoP 存储锁）；bot `ready` 但缺 drive/base app scope | 离线通过；真实 Base/Drive 读取 blocked |
| facilities | 12 张契约表 + 字段级读回 + 两个云盘目录 + 稳定 ID + 改名不改 ID + 幂等 | 未创建（未写飞书） | 离线通过；真实创建 untested |
| test_loop | 测试标识、`retrieved` 从真实 `--plan` 产物取候选数、`written` 选中论文 ID、`rendered` 按 `writer/render.py` 契约校验七段与原文图/生成图图注、评分先于采纳、`verify` 累计逐字段读回 | 未推送、未评分、未采纳 | 离线通过；真实闭环 untested |
| cleanup | 按测试 ID 与记录 ID 删除、消息撤回、逐范围读回、报道表作用域、失败中止、初始化闸门、幂等 | 未删除任何云端数据 | 离线通过；真实清理 untested |
| knowledge | intake 闸门、草案确认绑定、归一化字段级读回、拒绝覆盖既有卡片（快照失败即拒绝提案）、标准检索 | 未初始化正式知识 | 离线通过；真实初始化 untested |
| schedules | 两类宿主任务、绝对解释器/数据根/仓库/技能、触发校验、暂停与恢复、报告区分创建与触发 | 未创建任务、无到点触发 | 离线通过；真实触发 untested |

离线全量：**331 passed, 3 skipped**（在本机用 `python -X utf8 -m pytest -q … tests`；本机 pytest 临时目录需要本地 shim，未进入仓库）。逐票据的离线验收证据见对应 GitHub 票据评论；真实证据缺口见下方“宿主与恢复”和“下一次真实验收”。

结论：规格 #51 的代码与离线验收完成；真实端到端验收仍因宿主写策略与飞书身份/scope 阻塞。#52 与 #60 可按离线证据关闭，#53–#59 保持开放并在票据中记录缺口。

## 2026-10-27 首次 Windows 真实安装（进行中，未改动飞书数据）

目标宿主为 [DeepSeek Harness 44.7.0](../adr/0006-deepseek-harness-as-a-host.md)（第三款运行宿主）；飞书 CLI 复用用户已配置的 `@larksuite/cli` 1.0.98（[ADR 0007](../adr/0007-reuse-configured-lark-cli.md)），实际可执行文件在 npx 缓存中。代码目录 `E:\Desktop\frontier`（`dev`），数据根 `E:\Desktop\frontier-archive`。

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
| Base 本身/表/目录创建、确认命名、稳定 ID、同名 Base 提示而不复用、已有库显式接入 | `hostrun/facilities.py` | `tests/test_hostrun_facilities.py`（15） |
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
| 新安装增量 | 工作区、uv、CLI 预检、设施、临时闭环、清理、正式知识、两类任务均有离线测试；规格 #51 的 #52–#59 代码已合入 `dev`，离线 331 passed / 3 skipped | 真实 CLI/租户/宿主触发；真实 Base/Drive 读、推送/评分/采纳、清理读回、正式初始化与到点触发 | [#41](https://github.com/Moke110/frontier/issues/41) 的子票据 #42–#50；#51 的子票据 #52–#60 |

核对时发现 ChatGPT 任务已被标为关闭，但其最后一条验收评论仍写“未实测”，未附新的通过证据；因此本表保留证据缺口，不以 issue 状态推断验收通过。后续执行者须先核对关闭原因与最新证据；本轮不更改 tracker 状态。

2026-10-27 的原始安装检查只确认 `dependencies: ok`；当时 `lark_cli/identity: blocked`、`host: untested`，其余步骤 pending。它描述当时环境，不能当作当前安装检查；后续必须重新探测。原 WorkBuddy 开发解释器已失效，也不能沿用其 venv 作为有效安装证据。

空库恢复演练的原始结果为 `baseline_expected: 174`、`registered_sources: 0`、`missing: 174`、`zero_diff: false`、`streak: 0`。这证明核对工具没有把空库误报为完整恢复，不证明真实数据已经恢复。

## 下一次真实验收

0. 在实际目标宿主重新实测数据根与飞书 CLI 的令牌/DPoP 存储写入权限。2026-10-28 的历史 workspace-write 限制针对整棵进程树，不代表当前策略；数据根私有解释器不能解除该限制。必要权限未具备时记录 `blocked`，不能开始真实闭环。
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
