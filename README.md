# frontier

面向研究者的知识库与论文报道推送系统。围绕你关注的知识卡片检索论文，由 agent 排序、撰写报道并推送到飞书；你评分、确认更新后，研究知识逐步积累为命题与证据。

frontier 依赖一款能在本机执行命令、使用技能并启动前台控制台的 agent，以及飞书 CLI。代码、运行时与运行配置由 agent 管理，你无需自己配置环境；日常通过控制台和飞书操作。飞书保存知识、原文、推送件和已发出的待答问题，本地保存可重建副本。

## 目录与运行模型

- 工作区（`root`）下是代码目录 `frontier/` 与资料目录 `frontier-archive/`。
- 发行包安装的代码目录是解压后的发行包：程序代码、agent 可读资产（`skills/`、`contracts/`、`docs/`）、内置运行时 `<code>\runtime\` 与启动包装器 `<code>\bin\frontier.cmd`。源码安装的代码目录是 git checkout，另在 `<code>/.frontier/.venv` 保存 uv 管理的私有环境。
- 代码目录的运行时区 `<code>/.frontier/` 存放配置、状态、队列、提议、日志、执行端租约、控制台、安装记录（安装锁 `<code>/.frontier/dist.lock.json`、保留版本 `<code>/.frontier/releases/`）、初始化中间文件、飞书 CLI 与启动脚本。
- 资料目录**只**放 `originals/`（原文）与 `pushes/`（推送件）；其中的文件登记在 `<code>/.frontier/archive-index/index.jsonl`，资料目录里没有台账。
- 唯一常驻组件是**控制台**，入口为 `<code>\bin\frontier-console.cmd`（发行包安装）或 `python -m hostrun.cli console`（源码安装）：前台窗口、关掉即停止 frontier 服务；不注册 Windows 服务、不随开机启动、不写注册表或 PATH。
- 控制台启动脚本由 `<code>\bin\frontier.cmd --code <code> --archive <archive> console install --dsh <dsh 绝对路径>` 生成并记录 Agent 运行所需的凭据覆盖层；它只写配置与脚本，不启动进程。
- 既有源码安装用 `<code>\bin\frontier.cmd --code <code> --archive <archive> install migrate`（或源码安装的 `python -m hostrun.cli ...`）迁移到该目录模型。

## 安装

在 Windows 上打开宿主 agent 的本地会话，以 frontier 工作区为源文件夹创建项目，把下面整段发给它：

```text
请帮我安装 frontier：

1. 解析发行版：读取 https://github.com/Moke110/frontier/blob/main/releases/index.json（或 v* GitHub Release），在稳定渠道 stable 与预发布渠道 prerelease 中选择要安装的版本；记录 version（不带 v）、channel、制品名 frontier-<version>-<channel>.zip 与发布索引/摘要文件里的 artifact sha256。只从 GitHub Release 与发布索引获取发行包，不引入包市场。
2. 下载发行包与摘要：把 frontier-<version>-<channel>.zip 与同名 .digest.json 下载到工作区内的临时目录，不要直接解压到代码目录。
3. 校验摘要：用 PowerShell `Get-FileHash -Algorithm SHA256 "<zip>"` 计算 sha256，与 .digest.json 的 artifact.sha256 比较；不一致就在解压前停止，绝不写入代码目录或安装锁。
4. 引导安装：用 `Expand-Archive` 把 zip 解压到临时引导目录（zip 条目在根目录，解压后得到 <temp>\bin\frontier.cmd），执行：
   <temp>\bin\frontier.cmd --code "<code>" --archive "<archive>" install package --from "<zip>" --digest "<digest.json>"
   代码目录必须为空或不存在，或者是此前的发行包安装；成功后安装锁写在 <code>\.frontier\dist.lock.json，然后删除临时引导目录。
5. 生成控制台启动脚本：<code>\bin\frontier.cmd --code "<code>" --archive "<archive>" console install --dsh "<dsh 绝对路径>"。
6. 注册技能入口指针：<code>\bin\frontier.cmd --code "<code>" --archive "<archive>" install skill --root "<code>" --target "<host skills dir>"；指针记录发行来源、发行版本、发行渠道、制品摘要、发行包来源、技能摘要与安装锁，实测宿主能读取入口与参考文件。升级或回滚后可重跑此步刷新指针版本。
7. 启动控制台并把窗口交给我，我将在其中执行 /frontier-init；控制台启动前先自检权限；需要写入飞书凭据或工作区外资料目录而权限不足时，明确提示我双击 <code>\bin\frontier-console.cmd 以完整权限重启，并保留已完成的初始化进度。
8. 我完成 /frontier-init 后，如实报告已运行、阻塞与未实测项；把命令成功、任务计划与真实交付分开。
```

整条用户路径不需要 git、uv、pip 或系统 Python：代码目录、内置运行时与安装锁都由发行包和安装命令提供。发行包与源码的一致性由发行包清单里的 `built_from_commit` 记录，它只是证据，不参与安装判断。发行包安装没有 `install workspace` 生成的记录时，`install skill` 会从 `<code>\.frontier\dist.lock.json` 与 `manifest.json` 推导工作区记录（不伪造源码锁或 git commit），并让入口指针指向 `<code>\bin\frontier.cmd` 内置运行时包装器；该步骤可重复执行。

安装后的维护命令：

| 目的 | 命令 |
|---|---|
| 核对安装锁与磁盘内容 | `<code>\bin\frontier.cmd --code "<code>" --archive "<archive>" install verify` |
| 查看安装报告 | `<code>\bin\frontier.cmd --code "<code>" --archive "<archive>" install report` |
| 回滚到保留的上一版 | `<code>\bin\frontier.cmd --code "<code>" --archive "<archive>" install rollback`，或 `install rollback --to "<version>"` |
| 升级 | 下载新版本的 zip 与 .digest.json，校验摘要后重复第 4 步的 `install package --from ... --digest ...`；只替换发行包文件，资料目录与 `<code>\.frontier\` 运行状态不变，保留上一版可回滚 |

需要在控制台里亲自完成或确认的步骤：确认资料目录、确认执行 agent、Lark CLI 登录与管理员授权、在飞书点击测试消息里的按钮、回复设施展示名称、选择每日推送时刻、决定是否初始化知识库。

| 目标宿主 | 所需能力 | 当前状态 |
|---|---|---|
| ChatGPT Windows 桌面端 | 本地命令 + 技能 + 启动前台控制台 | 控制台流程未实测 |
| WorkBuddy Windows 桌面端 | 本地命令 + 技能 + 启动前台控制台 | 本地命令与项目访问有历史记录；控制台流程未实测 |
| DeepSeek Harness（本机会话） | 本地命令 + 技能 + 启动前台控制台 | 2026-10-27 起作为第三款运行宿主（[ADR 0006](docs/adr/0006-deepseek-harness-as-a-host.md)）；控制台离线测试通过，真实安装与运行未实测 |

宿主不再需要内置定时任务：推送时刻由控制台自己计时。具体版本、账号权限和证据见 [宿主验收记录](docs/acceptance/README.md)。电脑须开机、宿主运行且能访问飞书；网页云任务不能代替对本机依赖和凭据的访问。每款宿主独立验收，一款宿主安装成功不能证明另一款可用。

发行包安装的机制由离线测试覆盖，真实安装与 `/frontier-init` 仍待取得证据；未取得真实证据前不宣称已验收。

代码目录、内置运行时与运行目录都位于工作区内，但仍受宿主沙箱限制。安装与控制台启动前须实测必要的写入权限（代码目录、资料目录、飞书 CLI 凭据存储含令牌与 DPoP 密钥）；受限时由控制台提示以完整权限重启，并如实报告，不静默绕过。

## 开发者：源码安装

只有开发 frontier 本身时才使用源码安装；普通用户走上节的发行包安装，两条路径不要混用。源码安装需要 git、uv 与 uv 提供的 Python 3.13，在源码 checkout 上执行：

```powershell
git clone https://github.com/Moke110/frontier.git <workspace>\frontier
python -m hostrun.cli install workspace --root "<workspace>" --repo-url https://github.com/Moke110/frontier.git
python -m hostrun.cli --code "<code>" install toolchain --root "<workspace>"
python -m hostrun.cli --code "<code>" --archive "<archive>" console install --dsh "<dsh 绝对路径>"
python -m hostrun.cli install skill --root "<workspace>" --target "<host skills dir>"
```

源码安装的安装锁记录 `distribution: "source"` 与 git commit，不写发行包版本或制品摘要；`install verify` 对源码锁报告 `source_install`，没有发行包清单可校验。开发检查、分支模型与 tag/发布约定见 [AGENTS.md](AGENTS.md)。

## 使用

三种操作方式：

- **控制台（服务运行期间）**：前台事件流显示定时推送、飞书消息与卡片点击、agent 运行摘要与错误；底部输入行接受 `/frontier-init`、`/frontier-start`、`/frontier-stop`、`/frontier-status`、`/frontier-push`、`/frontier-update-kb`、`/frontier-logs`、`/frontier-help`、`/exit`。
- **飞书私聊（只要控制台在前台）**：给 frontier 机器人发 `推一篇`、`处理反馈`、`状态`、`暂停`、`恢复`、`测试飞书消息`。控制台只认你本人的单聊消息，其他人和群聊一律忽略。这六条无参数短语直接执行；`修改推送时间`、`修改资料目录` 需要参数，先由一次只读的意图判定运行映射到操作白名单，命中则发确认卡片给你点击后才执行，未命中回“无权限”。服务暂停期间只放行 `恢复`，其余消息只回“服务已暂停”且不触发任何运行。初始化、更新知识库与停止服务不在飞书操作白名单内，飞书端会提示在控制台执行。评分与采纳按钮不走这套流程，仍直接生效。
- **宿主 agent**：`<code>\bin\frontier.cmd --code "<code>" --archive "<archive>" console control start|stop|status|push`（源码安装用 `python -m hostrun.cli console control ...`）写控制文件，由控制台在下一秒内读取并执行，与在控制台输入等价。

控制台通过 `<code>\bin\frontier-console.cmd` 或 `<code>\bin\frontier.cmd --code "<code>" --archive "<archive>" console`（源码安装为 `python -m hostrun.cli console`）启动（窗口标题 `frontier-console`），`/exit`、`Ctrl+C` 或关闭窗口即停止服务。它不是 Windows 服务，不随开机启动；机器重启后需要你重新启动。

每日按你选择的时刻触发一次推送（默认 08:00）；控制台启动或从暂停恢复时，若当天还没有推送请求就立即补一次。错过多天最多合并成一次待推请求，不连续补发。反馈由控制台每 5 分钟轮询处理，当天首次同时做维护（原文库、推送库和配额）；每 10 分钟做一次 `knowledge.cli pull`，把你在多维表格里的文本改动与「待复核」勾选拉回本地权威。没有变化时保持安静。

每篇推送附反馈入口。先评分，再逐题确认知识更新；编辑答案后须明确提交，下次处理才生效。只有采纳的提议会更新知识库。“不在关注领域”会丢弃该篇的更新题。未回答的问题会挡住下一篇推送，但不阻止存储维护。

已处理的答案不会因后来编辑表格而自动撤销；需要纠正时，请提出新的更正请求。发送超时且结果不明时，控制台先核对，无法确认则暂停该项。

知识库初始化用 `/frontier-update-kb`：它先暂停正式服务，让你选一个目录，由 agent 分片读取全部内容，逐条打印候选知识卡片与命题给你审阅——回车接受、退格丢弃、Tab 保留但打上 `Under review`。带该标记的卡片与命题在正式工作中不启用、不读取；你之后在飞书多维表格里取消「待复核」勾选，它才会参与检索与写作。完成后恢复服务并做一次正式推送演练。再次执行是增量：只读资料目录里尚未登记的文件。

## 暂停、换机与恢复

暂停用 `/frontier-stop`（或飞书 `暂停`）：停止定时推送与飞书响应，控制台仍在前台，用 `/frontier-start` 恢复。关闭控制台窗口则整个服务停止。重开控制台时按上次状态恢复：上次是暂停就保持暂停并提示恢复命令，上次是运行态则自动启动服务。

换机或换宿主时，先停止旧端控制台，再在新端运行安装流程，选择连接已有飞书知识库，由 agent 完成接管与恢复。同一知识库同时只使用一个执行端。

本地缓存可以重建；离线备份可能是已从云盘移除的原文的唯一副本，须单独保留。卸载运行配置不会自动删除飞书数据。删除云端原文需要单独确认，并先完成离线备份与校验。

## 遇到问题

把问题交给宿主 agent 或控制台，先看 `/frontier-logs` 与最近一次 agent 运行的日志：

- **阻塞**：缺依赖、未登录、权限不足等，需要修复后继续。
- **未实测**：没有真实运行证据；控制台显示“正在运行”不等于交付成功。
- **队列未推进**：检查答案是否已提交，以及是否存在更早的待答问题。
- **推送失败**：`/frontier-status` 会显示最近一次失败原因与尝试次数；系统**不会自动重试**，确认原因后用 `/frontier-push` 重新请求。控制台关闭时被终止的推送请求会在下次启动续接一次。
- **飞书命令没反应**：确认控制台窗口还在运行；控制台关闭时飞书不会有任何响应，反馈会堆积到下次启动。
- **控制台启动即退出**：多为权限不足或运行时损坏；按提示以完整权限重新启动，或让宿主 agent 读取 `install report` 与 `install verify` 的结论。

代码目录默认在工作区的 `frontier`，资料目录默认在工作区的 `frontier-archive`；安装时 agent 会记录实际位置。中断后可要求“继续 frontier 安装”，不必从头创建知识库。存量迁移和云端恢复的限制见 [恢复验收记录](docs/acceptance/README.md)。

运行时技能由宿主加载 [skills/frontier-run/SKILL.md](skills/frontier-run/SKILL.md)。开发指引在 [AGENTS.md](AGENTS.md)，项目术语在 [GLOSSARY.md](GLOSSARY.md)。许可证见 [MIT License](LICENSE)。
