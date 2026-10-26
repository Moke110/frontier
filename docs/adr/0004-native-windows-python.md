# ADR 0004：运行环境改为原生 Windows Python

- 日期：2026-10-26
- 状态：已接受
- 相关决策：ADR 0003（飞书是唯一存储）；`WINDOWS-TRANSFER.md`（本次转移的可执行清单）

## 背景

开发机从 WSL 换到 Windows。frontier 的代码大量依赖 POSIX 特性，原生 Windows 下连导入都过不了：`question_queue/store.py` 与 `trigger/service.py` 直接 `import fcntl`；`trigger/service.py` 用 `os.killpg` 杀超时进程组；`trigger/service.py` 的 agent prompt 里写死 `/tmp`、`$(date +%F)`、`$FRONTIER_OWNER_ID`（bash 语法，PowerShell 下是废的）；常驻与定时全部由 systemd 承担；`INSTALL.md` 用 `fc-list` 检查中文字体。

可选路线有两条：新机器再装一个 WSL2 沿用现有部署，或者把代码改到能原生跑。

## 决策

1. **运行环境是原生 Windows Python**，不装 WSL2。仓库和数据根都放在 Windows 文件系统上，编辑器与运行环境是同一份路径。
2. **文件锁抽象进 `common.file_lock`**：POSIX 走 `fcntl.flock`，Windows 走 `msvcrt.locking`。两个平台各自 import，不在模块顶层碰 `fcntl`。
3. **进程树终止分平台**：POSIX 保留 `killpg(SIGKILL)`，Windows 用 `taskkill /F /T`，并给子进程加 `CREATE_NEW_PROCESS_GROUP`。
4. **临时目录一律走 `tempfile.gettempdir()`**，agent prompt 里的路径、日期、owner 一律由 Python 算好再填进去，prompt 不再含任何 shell 语法。
5. **常驻与定时迁到任务计划程序**：2 个常驻 listener 用「登录时触发」，4 个定时任务用 `schtasks`；注意任务计划程序的最小重复间隔是 1 分钟。
6. **推送只走自包含 HTML**：WeasyPrint 与 Noto CJK 从"安装前置条件"降级为"仅 legacy PDF 分支需要"。

## 被否决的替代方案

- **新机器再装 WSL2**：systemd、apt、字体全部原样可用，成本最低；但"在 Windows 上开发"会退化成两套文件系统、两条路径（`\\wsl$` 与 `C:\`），编辑器索引与 Python 解释器来回映射，正是这次想摆脱的东西。
- **NSSM 把 listener 装成 Windows 服务**：比任务计划更接近 systemd，但要额外引入一个第三方二进制，且用户级安装还得管理员权限。
- **只写文档、不改代码**：到 Windows 上第一步 `import trigger.service` 就 `ModuleNotFoundError: fcntl`，文档救不了。
- **保留 bash 语法、让 agent 自己在 PowerShell 里翻译**：prompt 是硬约束清单，不该让执行者去猜意图。

## 后果

- Windows 上的锁是**字节区间锁**，语义比 `flock` 窄；只在"本项目的进程都按约定锁同一个文件"时成立，不能当通用文件锁。
- `msvcrt` 分支在 CI 里跑不到（当前只在 Linux 跑测试），代码里标了 `pragma: no cover`。**Windows 侧没有自动化验证**，第一次真跑要人工确认 listener、定时任务、超时终止三条路径。
- 任务计划程序没有 `Restart=always`，listener 崩溃后不会自动拉起；需要"失败后重新启动"选项或外层看护。
- 飞书事件是 bot 级长连接消费：旧机器与 Windows 同时 `listen` 会抢事件、重复推送。转移期间必须保证只有一边在跑。
