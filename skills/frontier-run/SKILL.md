---
name: frontier-run
description: "Install, run, pause or recover frontier on a local host agent. Install the distribution package from a GitHub Release (bundled runtime, no git, uv or system Python), or a source checkout for development; register the skill pointer, start the user-owned console, create Feishu facilities, verify the owner and channel, initialize the knowledge base through the console, and run bounded agent runs on the console's schedule. Use for frontier runtime operations, not repository development."
---

# frontier-run

本 skill 供 frontier 的宿主 agent 在安装与运行时加载。仓库开发与 Matt Pocock 规划技能的约定由仓库根 AGENTS.md 管理，不属于本 skill。

## 两条安装路径

- **发行包安装（用户路径）**：从 GitHub Release 下载 `frontier-<version>-<channel>.zip` 与 `.digest.json`，校验 sha256 后解压；`install package` 写入安装锁，`console install` 生成启动脚本，`install skill` 注册入口指针。代码目录自带内置运行时，用户机器不需要 git、uv、pip 或系统 Python。
- **源码安装（开发者路径）**：在开发者源码 checkout 上用 `install workspace`、`install toolchain` 建 uv 私有环境，再 `install skill`。只有开发 frontier 本身时才使用；与发行包安装互不覆盖。

## 定位运行环境

安装时生成的入口指针包含代码目录、资料目录、解释器、安装记录与发行信息，以这些路径为准，不要根据本文件所在位置推断仓库。指针字段固定为：`发行来源`、`发行版本`、`发行渠道`、`制品摘要`、`发行包来源`（以上为发行包安装）、`源码提交`、`工作区改动`、`源码来源`（以上为源码安装）、`技能摘要`、`安装锁`；旧指针没有这些字段时按源码安装处理。指针的 `技能摘要` 是 `<code>/skills/frontier-run/SKILL.md` 的 sha256，必须与安装锁的 `skill_digest` 一致，`install check` 会重新核对。

所有模块命令以**代码目录**为工作目录执行，资料目录与资料登记目录每次显式给出（`--code <代码目录>` 与 `--archive <资料目录>`；旧 `--home` 已移除，被派生的子进程沿用 `FRONTIER_CODE` / `FRONTIER_ARCHIVE` / `FRONTIER_RUNTIME`）。命令入口按安装方式区分：

- 发行包安装：用 `<code>\bin\frontier.cmd` 执行 `hostrun.cli` 子命令（它调用 `<code>\runtime\python.exe`）；其他模块命令用 `<code>\runtime\python.exe -m <module>`。不要退回 `python`、`py` 或 PATH 上的解释器。
- 源码安装：用安装配置中记录的私有解释器执行 `python -m hostrun.cli ...`；Windows 可用进程参数 `-X utf8`。

代码与资料分开：代码、内置运行时或私有环境、配置、运行状态、日志与资料登记都在代码目录（运行时区 `<code>/.frontier/`）；资料目录只放原文 `originals/` 与推送件 `pushes/`。发行包安装没有 `<code>/.venv` 与 uv；源码安装的私有环境与解释器在 `<code>/.frontier/.venv`，uv 优先从工作区外解析。不修改系统/用户环境变量、PATH、注册表，不创建服务、系统定时任务或登录自启；**唯一允许的常驻组件是用户可见、关闭即停的控制台**（[ADR 0009](../../docs/adr/0009-console-as-service.md)）。

## 按请求执行

- **安装或继续安装**：读取 [installation.md](references/installation.md)，先确认走发行包安装还是源码安装。发行包安装按 README 的安装 Prompt 执行：解析 release/index、下载并校验摘要、解压引导副本后 `install package`、`console install`、`install skill`、启动控制台并等用户执行 `/frontier-init`。源码安装按工作区与目录迁移、代码目录私有 uv/解释器、`frontier-run` 入口指针、控制台启动脚本、飞书 CLI 三级检测、设施命名与创建、测试消息与收件人验证、首次知识库初始化的顺序执行。用户安装入口是 [README.md](../../README.md)。只声明实际验证过的能力，中断后从已完成步骤续接。
- **启动控制台**：用记录的 `frontier-console.cmd`，或 `frontier.cmd --code <code> --archive <archive> console`（源码安装为 `python -m hostrun.cli console`）启动前台控制台（窗口标题 `frontier-console`），由用户在控制台内执行 `/frontier-init` 等命令。控制台自检权限；需要飞书凭据或工作区外资料目录的写入而权限不足时，提示用户双击启动脚本以完整权限重启并保留进度。agent 不代为常驻，也不代用户输入控制台命令。
- **操作正在运行的控制台**：用 `frontier.cmd ... console control start|stop|status|push`（源码安装为 `python -m hostrun.cli console control ...`）写控制文件，由控制台在下一秒内读取执行；不要启动第二个控制台或第二个执行端。
- **检索推送**：控制台按每日时刻启动一次 agent 运行，或在用户要求「再推一篇」时启动。你若被控制台派生为这次运行（`dsh --profile headless --json`），先执行 `run --intent daily` 看闸门与续接状态；获准写作时读取 [workflow.md](references/workflow.md)，由你亲自完成排序、写作和校验，只推送一篇后报告实际完成结果。不要自行创建后台作业或宿主定时任务。
- **反馈处理**：控制台每 5 分钟执行一次 `run --intent feedback`（纯机械，不创建检索请求）。它处理已提交答案、未完成工作和当天首次维护，维护不受待答问题阻塞。
- **知识库初始化**：用户执行 `/frontier-update-kb` 时，控制台暂停正式服务、收集目录、编排分片读取并逐条审阅。你作为读取子运行只产出候选卡片与命题，不写入知识库；作为合并运行负责去重并提交审阅；用户决定后由控制台写入。
- **状态、暂停或恢复**：使用 `install report`、`status` 与控制台 `/frontier-status`。暂停由 `/frontier-stop` 或飞书 `暂停` 完成，停止定时推送与飞书响应但保持控制台在前台；关闭控制台窗口即停止整个服务。恢复前结束旧端执行，只允许一个执行端。

每次 agent 运行都是有界工作：完成当前工作后退出，**不挂会话、不派生后台作业、不创建宿主定时任务**。宿主或控制台关闭期间不承诺执行；错过多天的请求合并成一次，避免连续补发。

## 用户决定与完成标准

- 先评分，再逐题确认更新；只处理当前活动题。`irrelevant` 丢弃该篇的更新题；待答问题挡住新推送。
- 知识更新必须经提交和采纳；agent 只生成提议，不能直接编辑权威存储。已处理反馈的更正另建请求。
- 论文、证据与图片来源必须可追溯。先校验再入库，失败修正输出，不绕过校验器。
- 正式知识卡片必须经用户确认；`Under review` 标记的卡片与命题不参与检索、排序与写作。
- 日常发送遵循安装时确认的收件人与授权范围；更换目标、删除资料或扩大权限须另行确认。
- 发送结果不明确时先核对，无法确认则暂停该项，不能盲目重发。离线测试、任务计划和标志位都不能代替真实交付证据。
- 状态如实区分可用、阻塞与未实测。产品验收记录在 [docs/acceptance](../../docs/acceptance/)，模块契约在 [contracts](../../contracts/README.md)。
