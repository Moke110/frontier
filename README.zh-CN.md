# frontier

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Latest release](https://img.shields.io/github/v/release/Moke110/frontier?include_prereleases&label=release)](https://github.com/Moke110/frontier/releases)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11%20x64-0078D6)](#你需要什么)
[![Runtime](https://img.shields.io/badge/python-3.13%20bundled-3776AB)](#你需要什么)

[English](README.md) | **简体中文**

**一个替读论文、并把报道推回飞书的研究知识库。**

frontier 把你关注的主题积累成知识卡片，围绕卡片检索匹配的论文，由 agent 排序、撰写并生成带图的每日报道，推送到你的飞书。你给报道评分、并逐题确认知识更新；只有你采纳的更新才会写回知识库。久而久之，卡片、命题与证据会长成你自己的研究记忆，而不是一堆没有上下文的链接。

## 它能做什么

- **以卡片为准的检索**：每篇报道都从你确认过的知识卡片出发，而不是通用信息流，检索式因此不会跑题。
- **由 agent 写成的报道**：一次有界运行完成候选排序、写作与渲染，再以飞书文件消息投递。
- **人工确认，而不是静默改库**：agent 只提出知识更新建议；你给报道评分、逐题采纳或拒绝，只有被采纳的建议才写入权威的飞书多维表格。
- **不在你机器上常驻**：不注册 Windows 服务、不建系统定时任务、不写注册表与 PATH。唯一常驻的是一个前台控制台窗口，关掉即停止。

## 工作原理

```text
 你关注的主题 ──▶  飞书多维表格：卡片 · 命题 · 证据
                        │
                        │  检索（arXiv、Europe PMC 等）
                        ▼
                    候选论文
                        │
                        │  agent 排序、写作、渲染
                        ▼
                    一篇报道 ──▶  飞书文件消息
                        │                │
                        │                ▼
                        │        你评分并确认更新
                        │                │
                        ▼                ▼
                 采纳的更新 ◀────────────┘
                        │
                        └──▶  写回多维表格
```

知识本体存在飞书：多维表格保存卡片、命题与证据，云盘目录保存原文与推送件。本机保存的是可重建副本。资料目录**只**放 `originals/` 与 `pushes/`；配置、队列、日志、执行端租约与安装记录都放在代码目录的运行时区 `<code>\.frontier\`。

## 安装

### 你需要什么

- Windows 10/11 x64。
- 一个能执行本地命令、加载技能并启动前台控制台窗口的宿主 agent。DeepSeek Harness（Windows）是当前参考宿主，所以下面的安装由 agent 代你执行。
- 一个飞书账号与管理员权限，用于创建多维表格、两个云盘目录与机器人应用，并给你本人发私聊消息。
- 一个工作区目录。仅此而已：用户路径**不需要 git、uv、pip 或系统 Python**，发行包自带内置运行时。

安装后工作区结构：

```text
<workspace>\
  frontier\          代码目录：发行包文件、内置运行时、运行状态
  frontier-archive\  资料目录：只放 originals\ 与 pushes\
```

### 第 1 步：把下面整段发给宿主 agent

```text
请帮我在这台机器上安装 frontier：

1. 解析发行版：读取 https://github.com/Moke110/frontier 的 releases/index.json（或 v* GitHub Release），取最新一条的 version（不带 v）、channel、制品名 frontier-<version>-<channel>.zip 与 artifact sha256。当前索引只有 prerelease 渠道。只从 GitHub Release 与发布索引获取发行包，不引入包市场。
2. 下载制品与摘要：把 zip 与同名 .digest.json 下载到工作区内的临时目录，先不要解压进代码目录。
3. 解压前校验：用 PowerShell `Get-FileHash -Algorithm SHA256 "<zip>"` 计算 sha256，与 .digest.json 的 artifact.sha256 比较；不一致就在写入代码目录或安装锁之前停止。
4. 引导安装：用 `Expand-Archive` 把 zip 解压到临时引导目录（zip 条目在根目录，解压后得到 <temp>\bin\frontier.cmd），执行：
   <temp>\bin\frontier.cmd --code "<code>" --archive "<archive>" install package --from "<zip>" --digest "<digest.json>"
   代码目录必须为空、不存在，或是此前的发行包安装；成功后安装锁写在 <code>\.frontier\dist.lock.json，然后删除临时引导目录。
5. 生成控制台启动脚本：
   <code>\bin\frontier.cmd --code "<code>" --archive "<archive>" console install --dsh "<dsh 绝对路径>"
6. 注册技能入口指针，让本宿主下次还能找到 frontier：
   <code>\bin\frontier.cmd --code "<code>" --archive "<archive>" install skill --root "<code>" --target "<host skills dir>"
7. 启动控制台并把窗口交给我，我将在其中执行 /frontier-init。启动前先自检权限；需要写入飞书凭据或工作区外资料目录而权限不足时，提示我双击 <code>\bin\frontier-console.cmd 以完整权限重启，并保留已完成的初始化进度。
8. 我完成 /frontier-init 后，如实报告哪些真的运行了、哪些被阻塞、哪些未实测；不要把命令成功或任务已创建当成推送成功。
```

整条用户路径都由发行包提供：代码目录、内置运行时与安装锁来自发行包与安装命令，因此全程不需要系统工具链。发行包与源码是否对应，由包内清单的 `built_from_commit` 记录，它只是证据，不参与安装判断。

### 第 2 步：只有你能做的部分

在控制台窗口里，`/frontier-init` 会带你确认 frontier 无法替你决定的事：

1. 确认资料目录；
2. 确认执行 frontier 运行的 agent；
3. 飞书 CLI 登录并授权管理员 scope；
4. 点击 frontier 发给你的测试消息里的按钮；
5. 回复它创建的飞书设施的展示名称；
6. 选择每日推送时刻（默认 08:00）；
7. 决定是否现在就从一个 PDF 目录初始化知识库。

这些步骤完成前不会向飞书推送任何内容。中途中断也没关系：让宿主 agent「继续 frontier 安装」，进度会保留，不必从头创建知识库。

### 维护

| 目的 | 命令 |
|---|---|
| 核对安装锁与磁盘内容 | `<code>\bin\frontier.cmd --code "<code>" --archive "<archive>" install verify` |
| 查看安装报告 | `<code>\bin\frontier.cmd --code "<code>" --archive "<archive>" install report` |
| 升级 | 下载新版本的 zip 与 `.digest.json`，校验 sha256 后重跑 `install package --from "<zip>" --digest "<digest.json>"` |
| 回滚到保留的上一版 | `<code>\bin\frontier.cmd --code "<code>" --archive "<archive>" install rollback`，或 `install rollback --to "<version>"` |

升级只替换发行包文件：资料目录与 `<code>\.frontier\` 运行状态不变，并保留上一版可回滚。回滚不重新下载、不重新构建，只切回保留的版本目录并恢复安装锁。升级或回滚之后都要重跑一次技能指针步骤，让记录的版本跟着发行包走。

## 使用

三种驱动方式等价：

- **控制台**（始终是主界面）：前台窗口显示定时运行、飞书消息与卡片点击、agent 运行摘要与错误；底部输入行接受下表命令。
- **飞书私聊**（控制台开着时）：发下面六条短语之一。
- **宿主 agent**：写一个控制文件请求，控制台在一秒内读取执行。

| 控制台命令 | 作用 |
|---|---|
| `/frontier-init` | 首次初始化；也可续接中断的初始化 |
| `/frontier-start` | 暂停后恢复服务 |
| `/frontier-stop` | 暂停定时推送与飞书响应，控制台保持在前台 |
| `/frontier-status` | 当前状态、最近一次运行与失败原因 |
| `/frontier-push` | 立即再推一篇 |
| `/frontier-update-kb` | 增量初始化知识库，逐条审阅 |
| `/frontier-logs` | 查看最近的控制台与 agent 运行日志 |
| `/frontier-help` | 命令帮助 |
| `/exit` | 退出控制台（整个服务随之停止） |

| 飞书私聊短语 | 含义 |
|---|---|
| `推一篇` | 立即推一篇 |
| `处理反馈` | 处理已提交的反馈 |
| `状态` | 当前状态 |
| `暂停` | 暂停服务 |
| `恢复` | 恢复服务 |
| `测试飞书消息` | 给自己发一条测试消息 |

只认你本人的单聊消息，其他人和群聊一律忽略。服务暂停期间只放行 `恢复`，其余消息只回暂停提示。有两条命令需要参数——修改推送时间与修改资料目录——frontier 会先做一次只读意图判定，命中白名单才发确认卡片，你点击后才执行。

每篇推送附反馈入口。先评分，再逐题确认知识更新；编辑答案后须明确提交，下次处理才生效。未回答的问题会挡住下一篇推送，但不阻止存储维护。

控制台自己计时：每天在你选的时刻推送一次（默认 08:00），错过的天数最多合并成一次补推。反馈每 5 分钟轮询处理一次；每 10 分钟从多维表格把文本改动与「待复核」勾选拉回本地权威。没有变化时保持安静。

### 初始化或扩充知识库

`/frontier-update-kb` 先暂停正式服务，让你选一个目录，由 agent 分片读取全部内容，逐条打印候选卡片与命题给你审阅：回车接受、退格丢弃、Tab 保留但打上 `Under review`。带该标记的卡片与命题在正式工作中不启用，你之后在飞书多维表格里取消「待复核」勾选，它才会参与检索与写作。它是增量的：再次执行只读资料目录里尚未登记的文件。

## 暂停、换机与恢复

`/frontier-stop`（或飞书 `暂停`）暂停定时推送与飞书响应，控制台仍在前台；`/frontier-start`（或飞书 `恢复`）恢复。关闭控制台窗口则整个服务停止，飞书端不会有任何响应，直到你重新打开。重开控制台时按上次状态恢复：上次是暂停就保持暂停，上次是运行态则自动启动服务。

换机或换宿主时，先停止旧端控制台，再在新端运行安装流程，选择连接已有飞书知识库，由 agent 完成接管与恢复。同一知识库同时只允许一个执行端。

本地副本可以重建，但离线备份可能是已从云盘移除的原文的唯一副本，须单独保留。卸载运行配置不会删除飞书数据；删除云端原文需要单独确认，并先完成离线备份与校验。

## 遇到问题

- **控制台启动即退出**：多为权限不足或运行时损坏。按提示以完整权限重新启动，或让宿主 agent 读取 `install report` 与 `install verify` 的结论。
- **飞书命令没反应**：控制台必须开着。关闭窗口后飞书不会响应，反馈会堆积到下次启动再处理。
- **队列不推进**：检查答案是否已明确提交，以及是否存在更早的待答问题挡住下一篇。
- **推送失败**：`/frontier-status` 会显示最近一次失败原因与尝试次数。frontier **不会自动重试**：确认原因后用 `/frontier-push` 重新请求。
- **「正在运行」不等于已送达**：没有送达证据的定时运行会如实标记；请相信送达结果，而不是计时器。

## 开发者：源码安装

源码安装只用于开发 frontier 本身；普通用户走上文的发行包安装，两条路径互不覆盖。源码安装需要 git、uv 与 Python 3.13：

```powershell
git clone https://github.com/Moke110/frontier.git "<workspace>\frontier"
cd "<workspace>\frontier"
python -m hostrun.cli install workspace --root "<workspace>" --repo-url https://github.com/Moke110/frontier.git
python -m hostrun.cli --code "<code>" install toolchain --root "<workspace>"
python -m hostrun.cli --code "<code>" --archive "<archive>" console install --dsh "<dsh 绝对路径>"
python -m hostrun.cli install skill --root "<workspace>" --target "<host skills dir>"
```

源码安装的安装锁记录 `distribution: "source"` 与 git commit，不写发行包版本或制品摘要；`install verify` 对源码锁报告 `source_install`。私有环境位于 `<code>/.frontier/.venv`。开发检查、分支模型与 tag/发布约定见 [AGENTS.md](AGENTS.md)，模块契约见 [contracts/](contracts/README.md)。

## 文档与许可证

- 宿主 agent 的运行时技能：[skills/frontier-run/SKILL.md](skills/frontier-run/SKILL.md)
- 开发指引：[AGENTS.md](AGENTS.md) · 项目术语：[GLOSSARY.md](GLOSSARY.md)
- 模块契约：[contracts/](contracts/README.md)
- 许可证：[MIT](LICENSE)
