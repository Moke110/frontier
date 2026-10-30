# frontier 安装与恢复参考（供宿主 agent 执行）

> 状态：控制台化设计已定（[ADR 0009](../../../docs/adr/0009-console-as-service.md)），代码尚未实现。本文件描述目标流程；当前仓库仍按旧流程运行。

frontier 的安装与日常操作由**用户可见的前台控制台**承担，宿主 agent 负责准备工作区、环境、设施与用户对话。用户从仓库 [README.md](../../../README.md) 的安装 Prompt 启动；宿主加载 `skills/frontier-run/SKILL.md` 后按本参考执行。示例中的 `<workspace>`、`<code>`、`<archive>`、解释器与 CLI 路径都替换为安装时验证过的绝对路径。

- 工作区（`<workspace>`）下是代码目录（`<code>`，默认 `<workspace>/frontier`）与资料目录（`<archive>`，默认 `<workspace>/frontier-archive`）。
- 代码、私有环境（`<code>/.venv`）、配置、运行状态、日志与资料登记（`<code>/runtime/archive-index.jsonl`）都在代码目录；资料目录只放 `originals/` 与 `pushes/`。
- 不需要 WSL、systemd、Windows 任务计划或登录自启；不写持久环境变量、PATH 或注册表。唯一常驻组件是用户可见、关闭即停的控制台（[ADR 0009](../../../docs/adr/0009-console-as-service.md)）。
- 单执行端：同一知识库同一时刻只由一个控制台驱动。
- 判断标准只有 `python -m hostrun.cli install report` 的分项：`working` 才是通过，`blocked` 是缺能力，`untested` 是没测过。**离线测试、任务计划、手动调用都不代替真实交付证据。**

## 1. 支持的宿主

| 宿主 | 形态 | 状态 |
|---|---|---|
| WorkBuddy（Windows 桌面端） | 本地命令 + 技能 + 启动前台控制台 | 历史验证过项目访问、技能与本地命令；控制台流程未实测 |
| ChatGPT（Windows 桌面端本地模式） | 本地命令 + 技能 + 启动前台控制台 | 未实测；不得把旧票据状态当作通过 |
| DeepSeek Harness（Windows 本地会话） | 本地命令 + 技能 + 启动前台控制台 | 第三款运行宿主（见 [ADR 0006](../../../docs/adr/0006-deepseek-harness-as-a-host.md)）；控制台安装闭环与真实交付仍待验收 |
| Linux / macOS 终端 | 直接跑 CLI | 与宿主无关的命令行链路由离线测试覆盖 |

控制台化后不再要求宿主内置定时任务：推送时刻由控制台计时。每款宿主分别记录实际版本、权限与运行证据，不能互相替代。宿主或控制台关闭后不承诺定时触发；机器必须开机。必须在目标宿主中观察真实运行。

## 2. 前置条件

| 需要 | 说明 |
|---|---|
| 宿主本地执行 | 能运行命令、读写项目目录、加载技能、启动前台控制台 |
| Node.js / npm | 仅在系统里没有可用 `lark-cli` 时用于私有安装；不装全局包 |
| 飞书账号 | 由你本人完成登录与管理员授权；agent 只给直达链接与设备码 |
| 用户确认 | 资料目录、执行 agent、设施展示名称、每日推送时刻、是否初始化知识库 |

## 3. 安装顺序

### 3.1 工作区、代码目录与私有环境

先实测当前宿主对代码目录、资料目录与飞书 CLI 凭据存储（令牌与 DPoP 密钥）的必要写入权限。私有环境位于代码目录只隔离依赖，不解除宿主沙箱对进程树的限制；改变解释器位置不能作为权限已解决的证据。失败时记录实际路径、错误与所需授权范围，不搬迁凭据或使用全局完全访问绕过。

```bash
python -m hostrun.cli install workspace --root <workspace> --repo-url https://github.com/Moke110/frontier.git
python -m hostrun.cli --code <code> install toolchain --root <workspace>
python -m hostrun.cli --code <code> install skill --root <workspace> --target <host-skill-dir>/frontier-run
```

- `install workspace` 只**检查**已有副本：有未提交改动、origin 不符或不是 git 仓库时报告 blocked，不拉取、不覆盖；资料目录只创建不删除；资料目录落在代码目录内时明确拒绝且不写入。
- `install toolchain` 先在**工作区外**解析 `uv`（记录过的或系统 PATH 中的），都没有才把 `uv` 装进代码目录内的运行目录并由安装记录保存绝对路径；由它在代码目录建私有环境 `<code>/.venv` 并安装 `requirements.txt`（含 PDF 初始化需要的 PyMuPDF），安装后跑一次 `yaml`/`fitz` 导入探针。解释器的绝对路径同时写入入口指针与安装配置；重跑复用现有环境，不重建。
- 解释器缺失或损坏时 `dependencies` 为 `blocked` 并给出可执行的修复命令（`install toolchain --root <workspace> --clear`）；按命令加 `--clear` 重跑才重建环境，不会静默重建。
- `install skill` 写入的是**入口指针**，不是仓库副本；指针包含绝对代码目录、资料目录、uv、私有环境与解释器路径，技能目录移动后仍能定位代码。步骤可重复执行，已完成的组件不重做。
- **既有安装迁移**：对旧流程安装（数据根承载环境与运行状态）执行一次迁移，把环境、配置、运行状态、日志与资料登记移入代码目录的运行目录，原文与推送件留在资料目录，并读回确认：

```bash
python -m hostrun.cli install migrate --root <workspace> --code <code> --archive <archive>
```

  迁移前报告将要移动的路径与文件数；任何一步失败都停手并报告已完成的动作，不删除源数据。迁移后旧启动脚本与监听进程配置作废。

### 3.2 控制台

```bash
python -m hostrun.cli --code <code> --archive <archive> console install --dsh "<dsh 绝对路径>"
python -m hostrun.cli --code <code> --archive <archive> console install --dsh "<dsh 绝对路径>" \
  --dsh-arg=--patch --dsh-arg "<overlay.yml 绝对路径>"   # 本机 headless 缺模型凭据时记录 overlay
python -m hostrun.cli --code <code> --archive <archive> console
```

- `console install` 只生成 `<code>/bin/frontier-console.cmd`（窗口标题 `frontier-console`）并写入代码目录、资料目录、解释器、`dsh` 绝对路径与 `dsh_args`；**不**创建服务、不登录自启、不写注册表。`dsh` 必须显式记录：未给 `--dsh` 且记录为空或失效时，脚本仍生成但控制台步骤记 `blocked`，agent 运行也会拒绝启动。
- `--dsh-arg`（可重复）记录 agent 运行在 `--profile headless` 与任务文本之间的额外参数。本机实测：`dsh --profile headless` 的出厂层把 `deepseek-account` 与 `credentials` 插件置为 disabled，只留 API-key 路由，没有 `DEEPSEEK_API_KEY` 时会报 `MISSING_CREDENTIAL`。用 `--patch` 指定一个启用账号授权路由的 overlay 即可复用交互会话已有凭据，不另配 key。
- 控制台前台运行：`Ctrl+C`、`/exit` 或关闭窗口即停止服务；单实例锁保证同一安装只有一个控制台；心跳写 `<code>/runtime/console/heartbeat.json`，日志写 `<code>/runtime/logs/console.log`（滚动）。
- 控制台启动时**自检权限**：需要写飞书凭据库或工作区外资料目录而当前进程受限时，打印提示要求用户双击 `frontier-console.cmd` 以完整权限重启，并保留已完成的初始化进度（`<code>/runtime/state/init.json`）。这是唯一改变权限范围的机制；另开子终端不能解除沙箱。
- 控制台运行时由宿主 agent 用控制文件操作服务，不等价于替用户输入：`python -m hostrun.cli console control start|stop|status|push`。
- 控制台职责：按每日时刻触发一次推送、消费飞书消息与卡片回调、每 5 分钟反馈轮询、每 10 分钟 `knowledge.cli pull`、按需启动一次 agent 运行，并在事件流里显示 agent 运行的开始/结束/失败摘要。
- 控制台内命令：`/frontier-init`、`/frontier-start`、`/frontier-stop`、`/frontier-status`、`/frontier-push`、`/frontier-update-kb`、`/frontier-logs`、`/frontier-help`、`/exit`。

### 3.3 飞书 CLI、登录与权限（全部在控制台内完成）

```bash
python -m hostrun.cli lark discover --root <workspace>
python -m hostrun.cli lark install  --root <workspace>   # 缺失时私有安装 @larksuite/cli
python -m hostrun.cli lark login    --root <workspace>   # 只输出登录命令与设备码
python -m hostrun.cli lark status   --root <workspace>   # 可执行 / 身份 / 授权范围 / 资源读取
# 对既有库做只读预检，不接入也不修改：
python -m hostrun.cli lark status --root <workspace> --base-token <base-token> --folder <drive-folder-token>
```

- 私有安装落在代码目录的运行目录（`<code>/runtime/lark`，launcher `<code>/runtime/bin/lark-cli.cmd`），不装全局包、不写 PATH 或注册表。
- **三级检测**分别处理：没有可用 CLI → 安装；CLI 在但身份未登录 → 登录；已登录但授权范围不足或真实读操作失败 → 给出飞书开发者后台链接与缺失清单，等用户开权限后复检。bot scope 只能在开发者后台开通，`auth login` 从不用于 bot。
- 登录是拆分式设备码流程：`lark-cli auth login --domain all --no-wait --json` 返回授权链接与设备码，用户浏览器授权后由控制台执行 `auth login --device-code <code>` 完成。全程不新开终端，也不要求用户自己敲命令；需要时把授权链接或二维码发到飞书。
- 控制台等待登录最长 15 分钟；窗口内每 5 秒复检 `lark status`。失败或超时给用户「重试 / 中止（保留进度）」两个选项，**不允许跳过**进入下一步。
- `install check` 在 `permissions` 步骤**实测**飞书 CLI 凭据目录（`LARK_CLI_HOME`，未设置时 `~/.lark-cli`）的写入：创建随机临时探针文件再删除，任一失败即 `blocked`，note 给出具体路径与错误。身份证据另报 `dpop_key_status`/`dpop_mode`，不含密钥或用户标识原文。
- 状态命令与报告都不含 token；凭据只保存在 `lark-cli` 自己的机制里。

### 3.4 设施（Base、表、云盘目录）与命名

```bash
python -m hostrun.cli facilities plan   --code <code> --archive <archive>
python -m hostrun.cli facilities create --code <code> --archive <archive> --yes
# 或接入既有库
python -m hostrun.cli facilities attach --code <code> --archive <archive> --link <base-link> --yes
python -m hostrun.cli facilities status --code <code> --archive <archive>
```

- 命名由控制台集中询问**三项**：Base 名、原文云盘目录名、推送云盘目录名。直接回车用默认值，输入后回车用用户输入；逐项校验非空、无非法字符、同一 Base 内不重名。表名固定，不询问。
- 新建路径由控制台自动创建 Base 本身、表、字段与两个云盘目录，不需要用户手工准备空 Base。
- 记录稳定 ID；改展示名不改 ID。`create` 总是新建独立 Base，绝不按名称复用已有库；接入已有库必须显式 `facilities attach`，只检查与补缺，不清空、不重建。
- 现行契约包含 12 张表：知识卡片、命题、证据、报道、变更日志、原文、推送日志、决定、配置、问题、反馈、更正。按契约逐字段读回，缺字段报告为阻塞。
- 重跑复用已记录设施；本地记录丢失时不会按名称猜测复用。部分创建/权限拒绝/网络中断会报告已完成动作与缺项，修复后重跑继续。

### 3.5 测试消息与收件人验证

- 设施就绪后，控制台发一条测试消息给用户本人：一份测试 HTML 与一张带 1 个按钮的交互卡片，等用户点击卡片按钮。
- 用户点击后，控制台核对点击者与当前登录身份一致，**同时完成 owner 验证并写入 `<code>/runtime/install/recipient.json`**（用户标识原文只留在运行目录，不进入安装配置或报告）；后续只认该收件人的单聊。
- 测试消息可重发；重发前重新核对收件人，不清理聊天记录。没有点击、超时或身份不一致时报告 `recipient_unverified`/`recipient_mismatch`（不回显 open_id），初始化暂停在该步骤。
- 不再有临时关键词闭环与测试产物清理：链路验证由这次传输测试与首次知识库初始化后的正式推送演练承担。

### 3.6 `/frontier-init` 流程与门禁

用户在控制台输入 `/frontier-init`，控制台按步骤执行并显示进度。步骤结果写 `<code>/runtime/state/init.json`，可重入：

1. **确认资料目录**：`Y`/`y` 用默认 `<workspace>/frontier-archive`；`N`/`n` 打开系统文件夹对话框选择，允许工作区外，但要求控制台已以完整权限运行，否则提示重启。
2. **确认执行 agent**：展示将调用的 agent、`dsh` 绝对路径、`--patch` overlay 与授权范围，用户回车确认。v1 只支持当前安装宿主（DeepSeek Harness 适配器）。
3. **飞书 CLI**：按 3.3 的三级检测完成安装、登录与权限复检。
4. **测试消息与 owner 验证**：按 3.5 完成。
5. **设施命名与创建**：按 3.4 完成。
6. **每日推送时刻**：默认 08:00，用户可改；v1 只支持一个每日时刻，不做工作日过滤。
7. **是否初始化知识库**：是 → 进入 `/frontier-update-kb`；否 → 初始化结束，控制台启动服务但每日推送被知识库门禁挡住，并明确显示「待初始化知识库，推送已阻塞」。

- init 运行中正式服务在跑时**拒绝重跑**，提示先 `/frontier-stop` 或关闭控制台；不在后台隐式停止服务。
- 已完成的步骤重跑时跳过并显示「已完成：…」；已存在的同名设施询问「复用 / 新建」。中断后重新 `/frontier-init` 从断点继续。
- 设施、测试消息、`recipient.json`、每日时刻写入安装记录后，控制台不把“命令成功”当作安装通过。

### 3.7 `/frontier-update-kb`（知识库初始化与增量更新）

用户选中目录后，控制台按以下顺序执行：

1. **暂停正式服务**：停止定时推送与飞书响应，记录暂停原因与可恢复状态；控制台仍在前台并显示进度。
2. **复制原文**：把目录中的文件**复制**进资料目录 `originals/`（md5 校验，原目录不动），按业务 id 登记到 `<code>/runtime/archive-index.jsonl`，再按现有 `library ensure-source` 上传云盘；付费墙或无法读取的文件记为缺口并报告，不阻断其余文件。
3. **分片读取**：控制台按整文件打包，每片不超过上下文窗口约 10% 的字符估算；**单个文件可超过预算**，不做文件内切分；单个文件估算超过窗口 50% 时记为「未读取：超出读取上限」。最多 2 个读取子运行并发，串行提交，单次失败重试 1 次后跳过并报告。每个子运行只产出候选卡片/命题 JSON 到 `<code>/runtime/init/staging/`，不写入知识库。
4. **合并去重**：主运行合并候选、按来源去重，生成待审阅清单与 `draft_hash`。
5. **逐条审阅**：控制台一次一条打印候选知识卡片与命题（含 `第 N / M` 与完整字段）。单键读取：**Enter 接受**、**Backspace 丢弃**、**Tab 保留并打 `Under review`**；`q` 中止，已决定的立即生效，未决定的留待下次。stdin 不是 TTY 时拒绝进入审阅并提示在控制台窗口中执行。
6. **写入**：接受项写入知识库；保留项写入并标 `under_review`；丢弃项不写入 Base，但记入 `<code>/runtime/init/decisions.jsonl`（`{draft_id, decision: accept|discard|hold, at, source: console}`）以便追溯与续接。写入后按归一化字段读回校验，不一致报告 `base_readback_mismatch`。
7. **恢复服务与演练**：恢复正式服务，用刚入库的卡片跑一次标准检索、推送、评分与采纳的真实推送演练；失败则如实报告并保持初始化未完成。
8. **增量**：重复执行时只读资料目录中尚未登记的文件；不重复整库读取，已存在的卡片不覆盖（ID 冲突时拒绝并保留 Base 原行）。

`Under review` 的状态落在卡片与命题记录的可选布尔字段 `under_review` 与 Base 的「待复核」勾选框：不参与检索、排序与写作，但仍同步、计数、占配额。该字段不作为必备列：缺列时视为未标记，既有 Base 在 `init`/`attach` 时补建，不因缺列判安装失败。用户在 Base 取消勾选后，由控制台每 10 分钟的 `knowledge.cli pull` 拉回本地并生效；该字段不写 `变更日志`。

### 3.8 报告与验收

```bash
python -m hostrun.cli --code <code> --archive <archive> install report
```

报告分步给出 `working / blocked / untested / pending`、路径、时区、每日时刻、控制台状态与真实运行证据。最后按实际结果报告，不把“命令成功”冒充“安装通过”。真实证据至少覆盖：控制台连续运行、定时到点触发、飞书指令与确认卡片往返、暂停/恢复、关闭控制台即停、init 全流程、update-kb 全流程、既有安装迁移；没测过写“未实测”，缺能力写“阻塞”。

## 4. 日常运行

| 意图 | 频率 | 由谁执行 | 做什么 | 不做 |
|---|---|---|---|---|
| `daily` | 每天用户设定时刻（默认 08:00） | 控制台计时启动一次 agent 运行 | 处理反馈/恢复 → 维护（若到期）→ 请求并开始一篇推送 | 不并发多篇 |
| `feedback` | 每 5 分钟 | 控制台轮询 | 处理已提交答案与未完成工作；当天首次做维护 | **不创建**检索请求 |
| `maintenance` | 每天最多一次 | 由 `daily`/`feedback` 触发 | 原文库、推送库与配额维护 | 不删除资料 |
| `pull` | 每 10 分钟 | 控制台轮询 | 从多维表格拉取文本改动与「待复核」勾选 | 不写变更日志、不改结构列 |

```bash
python -m hostrun.cli --code <code> --archive <archive> run --intent daily
python -m hostrun.cli --code <code> --archive <archive> run --intent feedback
python -m hostrun.cli --code <code> --archive <archive> run --intent daily --finish ok
python -m hostrun.cli --code <code> --archive <archive> status
python -m hostrun.cli console control status
python -m hostrun.cli console control push
```

- agent 运行统一为 `dsh --profile headless --json`：控制台解析事件流、记录 `session_id` 到 `runs.jsonl`，事件流只显示开始/结束/失败摘要，完整输出写 `<code>/runtime/logs/agent-<run_id>.log`；`/frontier-logs` 查看最近一次运行尾部。
- **补推**：控制台启动或从暂停恢复时，若当天还没有推送请求就立即补一次；错过多天最多合并成一次待推请求，不连续补发。
- **暂停**：`/frontier-stop` 或飞书 `暂停` 停止定时推送与飞书响应，控制台仍在前台；`/frontier-start` 或飞书 `恢复` 继续。关闭窗口是整个服务停止。
- **状态恢复**：重开控制台时按上次状态恢复——上次是暂停则保持暂停并提示恢复命令，上次是运行态则自动启动服务。
- **在飞运行**：关闭控制台时显式终止在飞的 agent 运行，并把当前请求标记为未完成，交由既有「恢复未完成工作」机制续接，不丢单。
- 错过多天不补发；控制台不在线时反馈会堆积，直到控制台启动或下一次推送运行。

### 飞书入口与两层白名单

- **指令白名单**（trim 后精确匹配）直接执行操作：`推一篇`、`处理反馈`、`状态`、`暂停`、`恢复`、`测试飞书消息`、`修改推送时间`、`修改资料目录`；控制台 slash 指令同样映射到这些操作。
- **操作白名单**同一集合：状态、再推一篇、处理反馈、暂停、恢复、测试飞书消息、修改每日推送时间、修改资料目录。初始化、更新知识库与停止服务**不在**飞书操作白名单内，飞书端回「请在控制台执行」。操作不能修改 frontier 本身的定义。
- 未命中指令白名单的文本进入**意图判定运行**：只读、独立于推送运行的单飞行锁、不占执行端租约、强制输出 JSON（`{op, params, reason}`，`op` 必须是操作白名单之一）、60–90 秒上限、同一时刻最多一个、同一文本 10 分钟内复用结果。判定失败回「无法判断」。
- 判定命中后发**确认卡片**：显示操作、参数与「不修改 frontier 程序本身」，按钮 `执行` / `取消`，10 分钟过期，一次性 nonce，只有 owner 点击有效；点击后执行并回执，拒绝或过期回执说明。
- 判定无对应操作回「无权限」；不把自由文本直接交给 agent 执行。评分与采纳卡片按钮不走这套流程，仍按既有链路直接生效。

### 反馈闭环

```bash
python -m hostrun.cli feedback setup
python -m hostrun.cli feedback sync
python -m hostrun.cli feedback status
python -m hostrun.cli feedback process
python -m hostrun.cli feedback submit --item <id> --verdict great
python -m hostrun.cli feedback submit --item <id> --decision agree_all
python -m hostrun.cli feedback correct --item <id> --reason "..."
```

提交是边界；只处理当前活动题；只有采纳才写入；更正只入队，不直接改数据。

### 换机 / 恢复

```bash
python -m hostrun.cli executor status
python -m hostrun.cli executor handover --to <新宿主> --from <旧宿主>
python -m hostrun.cli executor handover --to <新宿主> --force
python -m hostrun.cli feedback rebuild
```

换机前先关闭旧端控制台；新端完成安装后选择连接已有飞书知识库，再由 `executor handover` 接管。

## 5. 权限、在线条件与无人值守

- 需要：跑本地命令、读写项目目录、调用飞书 CLI（含 bot 身份的事件长连接）。不需要全局网络代理、管理员权限或开机自启。
- 24 小时在线只由前台控制台提供；它不是服务，机器重启或用户关闭窗口后要由用户重新启动。
- 控制台运行所在进程必须有：代码目录写入（环境、运行状态、日志、资料登记）、资料目录写入、飞书 CLI 凭据存储写入。受限时按 3.2 提示以完整权限重启控制台，不静默提权。
- 自动运行只使用已授予范围；权限模型无法限制时报告 `blocked`。
- 电脑开机、控制台运行并登录；否则定时该次不发生（这是设计）。
- 状态文件与报告不含 token；`token/secret/password/cookie/key` 字段写 `***`。

## 6. 暂停、切换与清理

- 暂停：控制台 `/frontier-stop` 或飞书 `暂停`；关闭控制台窗口即停止整个服务。没有需要另行停用的宿主任务。
- 查看：`install report`、`status`、`console control status`、`/frontier-logs`。
- 清理旧 WSL/systemd 安装只在确实装过时执行；删运行配置不等于删飞书知识库或唯一离线备份。

## 7. 自检与验收

```bash
python -m hostrun.cli install report
python -m hostrun.cli facilities status
python -m hostrun.cli init status
python -m hostrun.cli console control status
python -m hostrun.cli audit streak
```

真实结论只看：控制台连续运行与日志、定时到点运行、飞书真实推送与反馈、确认卡片点击、关闭控制台后服务确实停止、正式知识读回、`under_review` 过滤生效、迁移读回。没测过写“未实测”，缺能力写“阻塞”。
