# frontier 安装与恢复参考（供宿主 agent 执行）

frontier 不再是一个要开机自启的后台服务，而是**由你正在用的宿主 agent 在本机按需执行**的一组命令。用户从仓库 README.md 的 prompt 启动；宿主加载 skills/frontier/SKILL.md 后按本参考执行安装与恢复。所有命令在仓库根执行，示例中的解释器和数据根替换为安装时验证的绝对路径。

- 不需要 WSL。
- 不需要 systemd、systemd timer、Windows 任务计划或任何常驻进程。
- 不需要写持久环境变量、PATH 或注册表。
- 数据根默认 `~/knowledge-loop`，可用 `--home` 指定（中文与含空格路径均支持）。

> 旧的 WSL + systemd 安装方式已归档到 [`docs/legacy/2026-10-systemd-install.md`](../../../docs/legacy/2026-10-systemd-install.md)。如果你机器上还留着旧的 `frontier-*` 单元，见本文末「清理旧安装」。

## 1. 支持的宿主与验证状态

| 宿主 | 形态 | 状态 |
|---|---|---|
| WorkBuddy（Windows 桌面端） | 本地会话 + 内置自动化 | 本机已实测命令行、项目目录、技能与本地 Python 执行；**内置调度的真实触发与无人值守权限仍待实测**，见 [`docs/acceptance/2026-10-27-host-matrix.md`](../../../docs/acceptance/2026-10-27-host-matrix.md) |
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

## 3. 执行安装

1. 获取或检查仓库副本；读取 [README.md](../../../README.md) 和 [运行时入口](../SKILL.md)。工作目录设为仓库根，数据根与代码分开；保留已有用户改动。
2. 探测宿主产品、版本、本地执行、技能加载与内置调度。用私有解释器准备 PyYAML 和飞书 CLI，配置显式路径，不使用失效的其他开发工具运行时。
3. 调用 `python -m hostrun.cli --home <home> install check --repo <repo>`，仅为亲自验证的能力提供 `--host-product`、`--host-version`、`--host-local-execution`、`--host-schedules` 和 `--permissions`。不要预先把所有能力标为可用。
4. 用已解析的飞书 CLI 引导登录，等待用户授权，再检查身份；输出只保留状态，不打印原始凭据。缺管理员权限则说明阻塞并保存进度。
5. 新库：用户提供空 Base 链接，`kb create --link <link>` 初始化后执行 `kb verify --expect-empty`。已有库：`kb attach --link <link>` 后列出缺表与兼容问题，经确认才 `kb create-tables`，不覆盖旧数据。
6. 与用户讨论初始主题，确认后 `kb initial-confirm --themes <themes.json> --yes`。只有用户确认过的知识进入初始构建。
7. 用 `schedules plan` 展示时区、每日检索、每小时反馈、每日维护。用户确认后，由宿主实际创建任务；每个任务保存本 skill、仓库、解释器和数据根的完整路径，唤醒时先读 skill，再执行计划中的命令。任务创建成功才能使用 `schedules confirm --yes --host-created`；该标志不是定时触发证据。
8. 运行一次 `run --intent feedback`，根据实际结果记录首跑；推送和真实调度的验收分别留证。最后 `install report` 汇报可用、阻塞、未实测与下一步，不以“状态命令成功”冒充完整安装验收。

所有子命令均通过 `python -m hostrun.cli --home <home>` 调用。状态保存在 `<home>/install/state.json`，中断后读取状态续接。若宿主必须注册技能，使用其当前已验证的项目加载方式，保持对本仓库完整参考文件的访问，不复制整个仓库到技能目录。

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
```

验收结论只看证据：宿主的真实触发记录、`feedback` 的持久化记录、`audit` 的连续自然日零差异。**没测过的写「未实测」，缺能力的写「阻塞」，不写成通过。**
