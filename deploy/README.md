# 已归档：systemd 单元模板（legacy）

这里的 `*.service.in` / `*.timer.in` 属于 WSL + systemd 时代的部署方式，**现行流程不再引用它们**。

- 现行安装方式：见仓库根目录 [`INSTALL.md`](../INSTALL.md)，由宿主 agent 在本机执行，不装服务、不装常驻监听。
- 旧安装全文（含这些单元的使用方法）：[`docs/legacy/2026-10-systemd-install.md`](../docs/legacy/2026-10-systemd-install.md)。
- 历史决策：`docs/adr/` 下的 ADR。

文件保留是为了两件事：查历史，以及识别你机器上仍存在的旧单元后按授权清理。任何现行脚本都不应再读取本目录。
