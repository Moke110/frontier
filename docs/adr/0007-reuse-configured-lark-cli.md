# ADR 0007：复用已配置的 lark-cli，不重复私有安装

- 日期：2026-10-27
- 状态：已接受
- 相关决策：[ADR 0005](0005-agent-owned-execution.md)；`hostrun/lark.py` 的私有安装保留为后备

安装流程要求 agent 自动准备飞书 CLI，且不修改 PATH、注册表或系统环境。因此实现默认在 `<workspace>/.frontier` 下私有安装 `@larksuite/cli`，并用一个私有启动器固定绝对路径。实际验收时用户已经用官方 `@larksuite/cli` 1.0.98 完成 app 注册与 user 登录：配置在 `~/.lark-cli`，DPoP 密钥在 Windows 密钥存储，授权范围齐全。全局 `lark-cli.cmd` 首次运行会尝试把平台二进制下载进全局 `node_modules`，在受限写权限下失败；真正可运行的是 npx 缓存里的 `lark-cli.exe`。

因此安装期记录**实际可执行文件的绝对路径**（`lark discover --cli <path>`，写进 `install/config.json` 的 `paths.lark_cli`），复用用户已经完成的授权；私有安装只在确实没有可用 CLI 时使用。这样不产生第二份 CLI、不重复一次设备授权，也不改用户环境。

## 后果

- 记录的路径属于用户环境，npx 缓存可能被清理。路径失效时安装报告必须回到 `lark_cli=blocked` 并给出重装指引，不能静默降级。
- 凭据仍只由 lark-cli 自己保存；frontier 只记录路径，不读取、不复制 token。
- 私有安装路径仍可用，用于真正干净的新机器。
