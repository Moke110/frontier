---
name: frontier
description: "Install, run, pause or recover frontier on a local host agent. Retrieve and rank research papers, write HTML reports, deliver them through Feishu, process submitted ratings and knowledge updates, and maintain the source and push libraries. Use for frontier runtime operations, not repository development."
---

# frontier

本 skill 供 frontier 的宿主 agent 在运行时加载。仓库开发与 Matt Pocock 规划技能的约定由仓库根 AGENTS.md 管理，不属于本 skill。

## 定位运行环境

从本文件向上两级定位仓库根。所有模块命令以仓库根为工作目录，文件契约中的路径也相对仓库根。使用安装配置中记录的解释器和飞书 CLI 完整路径；不要依赖名为 `python3` 的全局命令。

数据根默认 `~/knowledge-loop`，每次显式传 `--home <绝对路径>`。命令示例中的 `python` 代表安装验证过的解释器；Windows 可用进程参数 `-X utf8`，不写持久环境变量。读取登录状态时只报告身份就绪信息，不输出 token。

安装时优先让宿主直接加载本文件并读取同目录参考文件；如果宿主要求注册技能，使用其已验证的项目技能接入方式。不要复制整个仓库到技能目录或假定特定产品能自动发现自定义 skill。定时任务须保存仓库、数据根、解释器和本 skill 的绝对路径，每次唤醒先加载本 skill，再调用安装计划生成的命令。

## 按请求执行

- **安装或继续安装**：读取 [installation.md](references/installation.md)，检查能力、私有依赖、登录、知识库和进度。用户安装入口是 [README.md](../../README.md)。只声明实际验证过的能力。
- **检索推送**：先执行 `python -m hostrun.cli --home <home> run --intent daily`。按返回的闸门与续接状态决定是否继续；获准写作时读取 [workflow.md](references/workflow.md)，由当前宿主完成排序、写作和校验，推送一篇后报告实际完成结果。
- **反馈处理**：执行 `run --intent feedback`，只处理已提交答案和未完成工作，不因小时检查自行创建检索请求。反馈补充操作见安装参考。
- **维护**：执行 `run --intent maintenance`，检查两库对账和配额。维护不受待答问题阻塞；无变化不通知，不自动删除云端资料。
- **状态、暂停或恢复**：使用 `install report`、`status` 与安装参考中的交接流程。暂停须停用宿主实际创建的任务；恢复前结束旧端执行，只允许一个执行端。

每次唤醒执行一次有界工作后退出。不启动 systemd、系统定时任务、常驻事件监听或另一个无头 agent。宿主关闭期间不承诺执行；错过多天的请求合并，避免连续补发。

## 用户决定与完成标准

- 先评分，再逐题确认更新；只处理当前活动题。`irrelevant` 丢弃该篇的更新题；待答问题挡住新推送。
- 知识更新必须经提交和采纳；agent 只生成提议，不能直接编辑权威存储。已处理反馈的更正另建请求。
- 论文、证据与图片来源必须可追溯。先校验再入库，失败修正输出，不绕过校验器。
- 日常发送遵循安装时确认的收件人与授权范围；更换目标、删除资料或扩大权限须另行确认。
- 发送结果不明确时先核对，无法确认则暂停该项，不能盲目重发。离线测试、任务计划和标志位都不能代替真实交付证据。
- 状态如实区分可用、阻塞与未实测。产品验收记录在 [docs/acceptance](../../docs/acceptance/)，模块契约在 [contracts](../../contracts/README.md)。
