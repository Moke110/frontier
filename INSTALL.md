# 安装 frontier（Windows 原生，由宿主 agent 执行）

frontier 不再是一个要开机自启的后台服务，而是**由你正在用的宿主 agent 在本机按需执行**的一组命令。你在 WorkBuddy 或 ChatGPT 桌面端的本地会话里贴一段 prompt，agent 会自己完成安装、接入知识库、配置宿主的定时任务，并在之后每次被唤醒时执行一次有界运行。

- 不需要 WSL。
- 不需要 systemd、systemd timer、Windows 任务计划或任何常驻进程。
- 不需要写持久环境变量、PATH 或注册表。
- 数据根默认 `~/knowledge-loop`，可用 `--home` 指定（中文与含空格路径均支持）。

> 旧的 WSL + systemd 安装方式已归档到 [`docs/legacy/2026-10-systemd-install.md`](docs/legacy/2026-10-systemd-install.md)。如果你机器上还留着旧的 `frontier-*` 单元，见本文末「清理旧安装」。

## 1. 支持的宿主与验证状态

| 宿主 | 形态 | 状态 |
|---|---|---|
| WorkBuddy（Windows 桌面端） | 本地会话 + 内置自动化 | 本机已实测命令行、项目目录、技能与本地 Python 执行；**内置调度的真实触发与无人值守权限仍待实测**，见 [`docs/acceptance/2026-10-27-host-matrix.md`](docs/acceptance/2026-10-27-host-matrix.md) |
| ChatGPT（Windows 桌面端本地模式） | 本地会话 + 计划任务 | **未实测**，只有安装脚本与说明，不作为「已通过」宣称 |
| Linux / macOS 终端 | 直接跑 CLI | 命令行链路可用（与宿主无关的部分由测试覆盖） |

判断标准只有一条：`python -m hostrun.cli install report` 里标为 `working` 的项才算通过；`blocked` 是缺能力，`untested` 是没测过。**模拟与离线测试不代替宿主实测。**

## 2. 前置条件

| 需要 | 说明 |
|---|---|
| Python ≥ 3.11 | 用宿主能找到的私有解释器；`install check` 会记录路径与版本 |
| PyYAML | `python -m pip install pyyaml` |
| 仓库副本 | 放在任意本地目录即可，安装步骤只读它，不软链到系统目录 |
| 飞书 CLI（`lark-cli`） | 装到**私有目录**（如 `<home>/bin`），登录/授权由你本人完成 |
| 飞书知识库 | 一个 Base：新建空库，或已有库的链接 |

`lark-cli` 由显式路径解析：先看 `install/config.json` 的 `paths.lark_cli`，再看 `<home>/bin`，最后才做一次只读的 PATH 查找。**「找到可执行文件」不等于「已登录」**——登录状态是 `identity` 这一步单独验证的。

## 3. 把这段 prompt 发给宿主 agent

```
在当前项目里完成 frontier 的安装与接入，只做这些事，不要装服务或系统定时任务：

1. python -m hostrun.cli install check --repo . --host-product <你的产品名> --host-version <版本号> \
     --host-local-execution --host-schedules --permissions "shell,file_write"
   —— 只声明你实际验证过的能力；没验证的不要加参数，状态留 pending/untested。
2. 把 install report 的 blocked 项逐条告诉我，需要我做的登录/授权停下来问我。
3. 知识库二选一：
   新建空库：python -m hostrun.cli kb create --link <空 Base 链接>（建表后 verify --expect-empty 必须为 ok）
   接入已有库：python -m hostrun.cli kb attach --link <Base 链接>，把 missing 表清单给我确认后再 create-tables
4. 初始主题先给我看草案，我说确认后再：
   python -m hostrun.cli kb initial-confirm --themes <themes.json> --yes
5. 用 python -m hostrun.cli schedules plan 告诉我每日检索 / 每小时反馈 / 每日维护的时间，
   我确认时区与启用后再 schedules confirm --yes，并由你在宿主里真正创建这三个任务。
6. 最后跑一次 python -m hostrun.cli run --intent feedback，把结果贴给我。
```

agent 会把每一步的状态写进 `<home>/install/state.json`，**中断后重跑会续接**，不会重复建表、不会覆盖已验证的组件。

## 4. 装完之后：日常是怎么跑的

宿主按三个意图唤醒 agent，每个意图都是「做完就退出」：

| 意图 | 频率 | 做什么 | 不做 |
|---|---|---|---|
| `daily` | 每天一次 | 先处理反馈，再做一次维护（若今天没做过），然后请求并开始**一篇**推送 | 不并发多篇 |
| `feedback` | 每小时 | 只处理已提交的答案与未完成的题 | **不创建**检索请求 |
| `maintenance` | 每天至多一次 | 原文库/推送库对账 + 配额检查 | 不删除、不检索 |

```bash
python -m hostrun.cli run --intent daily           # 宿主每日任务调用
python -m hostrun.cli run --intent feedback        # 宿主每小时任务调用
python -m hostrun.cli run --intent daily --finish ok   # 链路做完后回报结果
python -m hostrun.cli status                       # 一个只读快照
```

错过就错过：宿主机没开机、客户端没运行，这一次运行就**不发生**，不会补跑出一串积压；错过的每日请求会合并成一次。

### 反馈闭环

```bash
python -m hostrun.cli feedback setup     # 建「问题 / 反馈 / 更正」三表（幂等）
python -m hostrun.cli feedback sync      # 把本地队列镜像到飞书
python -m hostrun.cli feedback status    # 只读：多少待处理
python -m hostrun.cli feedback process   # 应用已提交的答案（只处理当前活动题）
python -m hostrun.cli feedback submit --item q_01 --verdict great      # 显式提交
python -m hostrun.cli feedback submit --item q_03 --decision agree_all # 显式采纳
python -m hostrun.cli feedback correct --item q_03 --reason "机制写错了" # 更正请求，只入队
```

规则：**提交是边界**——不 submit 就不处理；只处理当前活动题；只有 `agree_all` / `adopt` 才写入知识；更正只生成新问题，不直接改数据。

### 换机器 / 恢复

```bash
python -m hostrun.cli executor status                                  # 现在谁在驱动
python -m hostrun.cli executor handover --to <新宿主> --from <旧宿主>   # 旧端还活着会被拒绝
python -m hostrun.cli executor handover --to <新宿主> --force           # 确认旧端已停用后再强制
python -m hostrun.cli feedback rebuild                                 # 从飞书重建本地队列
```

同一时刻只有一个执行端。租约是时间租约（不是进程号），所以另一台机器上的 pid 不会被误判。重建只恢复未完成的题，**已处理的决定不会被再次应用**。

## 5. 权限、在线条件与无人值守

- 需要授予的能力：跑本地命令、读写项目目录、调用飞书 CLI。**不需要**全局网络代理、不需要管理员权限、不需要开机自启。
- 自动运行只使用你**已授予**的范围。如果宿主的权限模型无法把范围限制到这几项，安装报告会把该步骤标为 `blocked` 并说明原因——**不要用「完全访问」绕过**。
- 电脑需开机、客户端需运行且已登录；否则该次运行不发生（这是设计，不是故障）。
- 凭据只留在 `lark-cli` 自己的机制里；`install report` 与所有状态文件都不含 token（`token` / `secret` / `password` / `cookie` / `key` 字段一律写 `***`）。

## 6. 暂停、切换与清理

```bash
# 暂停：在宿主里停用（或禁用）那三个任务即可；不需要动任何文件
# 换机：先在新机上 install check + kb attach，再 executor handover，最后 feedback rebuild
# 查看：python -m hostrun.cli install report
```

**清理旧安装**（只有你确实装过 WSL/systemd 版本时才需要）：

```bash
systemctl --user disable --now frontier-listener frontier-rating-listener \
  frontier-daily.timer frontier-retry.timer frontier-sync.timer frontier-library.timer 2>/dev/null || true
systemctl --user list-unit-files 'frontier-*'    # 确认没有残留
```

清掉运行配置**不等于**删除知识库：飞书里的 Base、云盘里的原文与推送都不要动。确认新方式跑通、云端对账零差异之后，再决定是否清理旧工作目录。

## 7. 自检与验收

```bash
python -m hostrun.cli install report                      # working / blocked / untested 三段
python -m hostrun.cli kb verify --expect-empty            # 新库必须为空
python -m hostrun.cli audit run --baseline <174 篇清单>    # 存量核对（只读）
python -m hostrun.cli audit streak                        # 连续零差异天数
python -m pytest -q                                       # 仓库自测
```

验收结论只看证据：宿主的真实触发记录、`feedback` 的持久化记录、`audit` 的连续自然日零差异。**没测过的写「未实测」，缺能力的写「阻塞」，不写成通过。**
