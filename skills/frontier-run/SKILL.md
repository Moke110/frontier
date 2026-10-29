---
name: frontier-run
description: "Install, run, pause or recover frontier on a local host agent. Deploy a private uv environment, create Feishu facilities, run a tagged acceptance test, initialize knowledge cards, keep the user-started listener online, and run the two bounded host tasks (daily push, listener health check). Use for frontier runtime operations, not repository development."
---

# frontier-run

本 skill 供 frontier 的宿主 agent 在运行时加载。仓库开发与 Matt Pocock 规划技能的约定由仓库根 AGENTS.md 管理，不属于本 skill。

## 定位运行环境

安装时生成的入口指针包含仓库、数据根、uv、私有环境、解释器和安装记录的绝对路径；以这些路径为准，不要根据本文件所在位置推断仓库。所有模块命令以仓库根为工作目录，数据根每次显式传 `--home <绝对路径>`。使用安装配置中记录的 Python 与飞书 CLI 完整路径，不依赖 `python3` 或全局 PATH；Windows 可用进程参数 `-X utf8`。

代码目录与数据根分开：代码默认 `<workspace>/frontier`，数据根默认 `<workspace>/frontier-archive`。uv 管理的私有环境与解释器在数据根内（`<home>/.venv`），代码目录只保留代码；uv 优先从工作区外解析。不修改系统/用户环境变量、PATH、注册表，不创建服务、系统任务或登录自启；唯一允许的常驻组件是用户手动启停的 `frontier-listener` 监听进程（[ADR 0008](../../docs/adr/0008-listener-process.md)）。

## 按请求执行

- **安装或继续安装**：读取 [installation.md](references/installation.md)，按顺序执行工作区、数据根私有 uv/解释器、`frontier-run` 入口指针、飞书 CLI/登录、设施命名与创建、关键词临时闭环、清理、正式知识初始化、监听进程启停脚本、两个瞬时宿主任务。用户安装入口是 [README.md](../../README.md)。只声明实际验证过的能力。
- **检索推送**：先执行 `python -m hostrun.cli --home <home> run --intent daily`。按返回的闸门与续接状态决定是否继续；获准写作时读取 [workflow.md](references/workflow.md)，由当前宿主完成排序、写作和校验，只推送一篇后报告实际完成结果。
- **反馈处理**：执行 `run --intent feedback`。它处理已提交答案、未完成工作和当天首次维护，**从不**创建检索请求；维护不受待答问题阻塞。
- **监听进程**：安装时用 `listener install` 生成 `<home>/bin/frontier-listener.cmd` 与 `frontier-listener-stop.cmd`，由用户双击启动、双击停止（窗口标题 `frontier-listener`）；agent 不装服务、不登录自启。`listener status` 读心跳与 pid；`run --intent listener-check` 做每日巡检（判定不在线时拉起一次并复查，仍失败就如实报告）。监听事件面与命令白名单见 [ADR 0008](../../docs/adr/0008-listener-process.md)。
- **临时验收**：用 `smoke` 以用户关键词跑一次带标记的真实闭环（检索、推送、飞书评分、采纳写入），再用 `cleanup` 按测试 ID 删除并读回确认。只有测试成功且清理通过才开放正式知识初始化。
- **正式知识**：用 `init intake` 收集 PDF/文本/索引与用户要求，`init propose` 生成候选卡片，用户确认后 `init apply` 写入飞书并完成一次标准检索。已有库用 `init adopt-existing` 沿用，不重建。
- **状态、暂停或恢复**：使用 `install report`、`status` 与安装参考。暂停须在宿主停用两个实际任务，并由用户停止监听进程；恢复前结束旧端执行，只允许一个执行端。

每次唤醒执行一次有界工作后退出，**不挂会话、不派生后台作业**。不启动 systemd 或系统定时任务；不创建独立常驻程序，除非它就是用户手动启停的 `frontier-listener`。监听进程可派生一次无头宿主运行，必须遵守 [ADR 0008](../../docs/adr/0008-listener-process.md) 的单飞行、租约、时限与不重试护栏。宿主关闭期间不承诺执行；错过多天的请求合并，避免连续补发。

## 用户决定与完成标准

- 先评分，再逐题确认更新；只处理当前活动题。`irrelevant` 丢弃该篇的更新题；待答问题挡住新推送。
- 知识更新必须经提交和采纳；agent 只生成提议，不能直接编辑权威存储。已处理反馈的更正另建请求。
- 论文、证据与图片来源必须可追溯。先校验再入库，失败修正输出，不绕过校验器。
- 正式知识卡片必须经用户确认；测试关键词不会自动成为研究范围。临时卡片的检索式不得复用为日常计划。
- 日常发送遵循安装时确认的收件人与授权范围；更换目标、删除资料或扩大权限须另行确认。
- 发送结果不明确时先核对，无法确认则暂停该项，不能盲目重发。离线测试、任务计划和标志位都不能代替真实交付证据。
- 状态如实区分可用、阻塞与未实测。产品验收记录在 [docs/acceptance](../../docs/acceptance/)，模块契约在 [contracts](../../contracts/README.md)。
