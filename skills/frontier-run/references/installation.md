# frontier 安装与恢复参考（供宿主 agent 执行）

frontier 不是后台服务，而是**由你正在用的宿主 agent 在本机按需执行**的一组命令。用户从仓库 [README.md](../../../README.md) 的安装 Prompt 启动；宿主加载 `skills/frontier-run/SKILL.md` 后按本参考执行。示例中的 `<workspace>`、`<home>`、`<repo>`、解释器与 CLI 路径都替换为安装时验证过的绝对路径。

- 代码目录与数据根分开：工作区内代码子目录默认 `frontier`，数据根默认 `frontier-archive`。
- 不需要 WSL、systemd、Windows 任务计划或常驻进程；不写持久环境变量、PATH 或注册表。
- 单执行端：同一知识库同一时刻只由一个宿主驱动。
- 判断标准只有 `python -m hostrun.cli install report` 的分项：`working` 才是通过，`blocked` 是缺能力，`untested` 是没测过。**离线测试、任务计划、手动调用都不代替真实交付/到点证据。**

## 1. 支持的宿主

| 宿主 | 形态 | 状态 |
|---|---|---|
| WorkBuddy（Windows 桌面端） | 本地会话 + 内置自动化 | 历史验证过项目访问、技能与本地命令；内置调度真实触发与无人值守权限仍待验收 |
| ChatGPT（Windows 桌面端本地模式） | 本地会话 + 计划任务 | 未实测；不得把旧票据状态当作通过 |
| Linux / macOS 终端 | 直接跑 CLI | 与宿主无关的命令行链路由离线测试覆盖 |

## 2. 前置条件

| 需要 | 说明 |
|---|---|
| 宿主本地执行 | 能运行命令、读写项目目录、加载技能、创建内置定时任务 |
| Node.js / npm | 仅在系统里没有可用 `lark-cli` 时用于私有安装；不装全局包 |
| 飞书账号 | 由你本人完成登录与管理员授权；agent 只给直达命令 |
| 用户确认 | 数据根/展示名称、关键词测试、正式知识卡片、时区与任务启用 |

## 3. 安装顺序

### 3.1 工作区与私有环境

```bash
python -m hostrun.cli install workspace --root <workspace> --repo-url https://github.com/Moke110/frontier.git
python -m hostrun.cli --home <home> install toolchain --root <workspace>
python -m hostrun.cli --home <home> install skill --root <workspace> --target <host-skill-dir>/frontier-run
```

- `install workspace` 只**检查**已有副本：有未提交改动、origin 不符或不是 git 仓库时报告 blocked，不拉取、不覆盖；数据根只创建不删除。若数据根落在代码目录内，明确拒绝且不写入。
- `install toolchain` 先在**工作区外**解析 `uv`（记录过的或系统 PATH 中的），都没有才把 `uv` 装到 `<home>/bin`；由它在**数据根**建私有环境 `<home>/.venv` 并安装 `requirements.txt`（含 PDF 初始化需要的 PyMuPDF），安装后跑一次 `yaml`/`fitz` 导入探针。解释器的绝对路径同时写入工作区指针记录与安装配置；重跑复用现有环境，不重建。
- 解释器缺失或损坏时 `dependencies` 为 `blocked` 并给出可执行的修复命令（`install toolchain --root <workspace> --clear`）；按命令加 `--clear` 重跑才重建数据根环境，不会静默重建。修复后重跑恢复为 `ok`。
- `install skill` 写入的是**入口指针**，不是仓库副本；指针包含绝对仓库、数据根、uv、私有环境与解释器路径，技能目录移动后仍能定位代码。步骤可重复执行，已完成的组件不重做。

### 3.2 飞书 CLI、登录与权限

```bash
python -m hostrun.cli lark discover --root <workspace>
python -m hostrun.cli lark install --root <workspace>     # 缺失时私有安装 @larksuite/cli
python -m hostrun.cli lark login --root <workspace>       # 只输出用户要执行的登录命令
python -m hostrun.cli lark status --root <workspace>      # 可执行 / 身份 / 授权范围 / 资源读取
```

- 可执行、已登录、授权范围、真实资源读取是四件事，分别报告。
- 登录、管理员授权必须由用户完成；agent 不伪造、不静默扩大权限。
- 设施创建前，资源检查只能标 `untested`；Base/Drive 读取证据在设施就绪后补。
- 状态命令与报告都不含 token；凭据只保存在 `lark-cli` 自己的机制里。

### 3.3 设施（Base、表、云盘目录）

```bash
python -m hostrun.cli facilities plan   --home <home>
python -m hostrun.cli facilities create --home <home> --yes   # agent 创建 Base 本身
# 或接入已有库
python -m hostrun.cli facilities attach --home <home> --link <base-link> --yes
python -m hostrun.cli facilities status --home <home>
```

- 先集中确认数据根与默认展示名称（Base、各表、原文库/推送库目录可改），确认后才写入。
- 新建路径由 agent 创建 Base 本身、表、字段与两个云盘目录，不需要用户先手工准备空 Base。
- 记录稳定 ID；改展示名不改 ID。同名 Base 有多个时阻塞，不猜测、不切换。
- 重跑复用已记录设施；本地确认丢失时按名称查找，只有唯一匹配且包含 frontier 首表才复用。已有库只检查与补缺，不清空、不重建。
- 部分创建/权限拒绝/网络中断会报告已完成动作与缺项；修复后重跑继续。

### 3.4 关键词临时闭环（不改正式知识）

```bash
python -m hostrun.cli smoke start --home <home> --keyword "<用户给的关键词>" --owner <open_id> --yes
python -m hostrun.cli smoke plan  --home <home>
python -m hostrun.cli smoke brief --home <home>          # 给宿主 agent 的下一步命令
python -m hostrun.cli smoke record --home <home> --step retrieved --plan <已存在的计划/候选文件>
python -m hostrun.cli smoke record --home <home> --step written --paper <选中 paper_id>（可重复）
python -m hostrun.cli smoke record --home <home> --step rendered --push <push_id> --html <渲染文件>
# ... sent（必须带 --push --message --question；上传文件用 --file，可重复）
python -m hostrun.cli smoke record --home <home> --step rated --item <id> --verdict great
python -m hostrun.cli smoke record --home <home> --step decided --item <id> --decision agree_all
python -m hostrun.cli smoke record --home <home> --step applied --target <被采纳目标 id> --applied-field <字段>（每字段重复一次）
python -m hostrun.cli smoke verify --home <home> --target-key cards --target-id <card_id> --field <字段>=<值>（可重复）
```

- 只取本次临时卡片的检索式；临时卡片同时写入本地与 Base，ID/标签带测试标记。
- `retrieved` 必须指向真实存在的计划/候选文件，候选数由该文件得出（可选 `--candidates` 必须与之一致）；`written` 至少一个选中论文 ID（`--paper`）；`rendered` 必须带推送 ID 与渲染文件，并按 `writer/render.py` 契约校验七段段落和 `原文图`/`生成图` 图注；这些证据与 `sent` 的副作用 ID 一并写入测试记录，供精确清理。
- `applied` 用 `--target` 与 `--applied-field` 登记被采纳的目标与字段（省略时按临时卡片、只要求至少一个字段）；`verify` 必须覆盖每个已登记目标字段才完整，覆盖不足返回 `verification_incomplete`，字段不一致判失败。
- 使用标准检索、写作、publisher、统一队列与反馈链路；只推一篇，评分先行，采纳后才写入。
- 用户在飞书检查展示并提交反馈；agent 处理并读回验证。只有全部步骤 + 读回一致才算通过。
- 任何失败先核对；发送超时不能确认则暂停，不重发。失败不开启正式初始化或日常推送。

### 3.5 清理测试产物

```bash
python -m hostrun.cli cleanup plan --home <home>
python -m hostrun.cli cleanup run  --home <home> --yes
# 失败测试的产物（明确授权时）
python -m hostrun.cli cleanup run  --home <home> --yes --abort
```

- 只按本次测试的卡片 ID、推送 ID、问题 ID、选中论文 ID、文件 token、消息 ID 删除；不用目录/名称匹配或清空整库。
- 删除 Base 记录、上传文件、临时卡片、推送 JSON、问题与反馈、可撤回消息；正式数据与用户原件不动。
- 删除后**读回确认**；不可删除或不可撤回的产物如实报告为清理未完成，正式初始化闸门保持关闭。
- 保留安装环境、配置、空设施与最小验收状态（不含论文内容）。

### 3.6 正式知识初始化

```bash
python -m hostrun.cli init intake --home <home> --pdf <p1> --text <p2> --index <p3> --requirements "<用户要求>"
python -m hostrun.cli init propose --home <home> --cards <cards.json>
python -m hostrun.cli init review  --home <home>
python -m hostrun.cli init confirm --home <home> --yes
python -m hostrun.cli init apply   --home <home>
```

- 仅在临时闭环通过且清理读回通过后开放。
- `init propose` 需要先完成 `init intake` 且至少有可读全文与用户要求；缺输入、无可读全文或既有卡片快照读取失败时拒绝生成草案。
- 支持 PDF、文本、索引列表（JSON/JSONL/CSV/逐行标题）加用户直接要求；读不到的文献列为缺口，不编造全文或引文。
- 候选卡片由宿主 agent 提炼，写出前必须经用户确认；确认与草稿哈希绑定，草案改动后需重新确认。写入后按归一化字段读回校验，不一致即报告 `base_readback_mismatch`。
- `init apply` **不会覆盖**草案生成前已存在的卡片 ID（没有覆盖开关）；冲突时拒绝并保留 Base 原行，请为新卡片使用新 ID。
- 重复执行幂等；中断后重跑只补未完成部分。已有库使用 `init adopt-existing` 导入现有卡片，不重建、不清空。
- 就绪后执行一次标准知识卡片检索（`init retrieve`），不把安装测试关键词当作研究计划。

### 3.7 两类宿主任务

```bash
python -m hostrun.cli schedules plan    --home <home> --timezone Asia/Shanghai
python -m hostrun.cli schedules confirm --home <home> --yes --host-created \
  --task-id frontier-daily=<宿主任务ID> --task-id frontier-feedback=<宿主任务ID>
python -m hostrun.cli schedules trigger --home <home> --task frontier-daily
python -m hostrun.cli schedules pause   --home <home> --yes
python -m hostrun.cli schedules resume  --home <home> --yes
```

- 只创建两个任务：用户时区每日 08:00 推送、每小时反馈检查（默认第 5 分钟）。维护并入每天首次小时检查，不建第三个任务。
- 每个任务保存 `frontier-run`、仓库、数据根、解释器与 CLI 的绝对路径；唤醒时先读 skill 再执行。
- 小时检查只处理反馈/恢复/维护，**从不**创建检索请求；未答问题不阻塞维护。
- 正式知识未就绪不启用每日推送；允许确认后暂不启用。
- 任务创建成功只写 `schedules`；真实到点触发才写 `scheduled_run`。手动运行、旧成功标记、云任务都不能替代。两类任务都至少真实触发一次后，`scheduled_run` 才为 `ok`。
- `schedules confirm` 为两个任务各生成一个 proof 并写入实际命令；`run --scheduled` 不带匹配 proof 时只当普通运行，不写入触发证据。确认后请使用 `schedules confirm` 返回的任务命令，不要手写不带 proof 的命令。
- 暂停会停用配置并要求在宿主里停用实际任务；换机先停旧端，再 `executor handover`。

### 3.8 报告

```bash
python -m hostrun.cli --home <home> install report
```

报告分步给出 `working / blocked / untested / pending`、路径、时区、任务与真实触发状态。最后按实际结果报告，不把“命令成功”冒充“安装通过”。

## 4. 日常运行

| 意图 | 频率 | 做什么 | 不做 |
|---|---|---|---|
| `daily` | 每天 08:00 | 处理反馈/恢复 → 维护（若到期）→ 请求并开始一篇推送 | 不并发多篇 |
| `feedback` | 每小时 | 处理已提交答案与未完成工作；当天首次做维护 | **不创建**检索请求 |

```bash
python -m hostrun.cli run --intent daily
python -m hostrun.cli run --intent feedback
python -m hostrun.cli run --intent daily --finish ok
python -m hostrun.cli status
```

错过就错过：电脑或客户端关闭时该次不发生；错过的每日请求合并成一次。

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

## 5. 权限、在线条件与无人值守

- 需要：跑本地命令、读写项目目录、调用飞书 CLI。不需要全局网络代理、管理员权限或开机自启。
- 自动运行只使用已授予范围；权限模型无法限制时报告 `blocked`，不要用“完全访问”绕过。
- 电脑开机、客户端运行并登录；否则该次不发生（这是设计）。
- 状态文件与报告不含 token；`token/secret/password/cookie/key` 字段写 `***`。

## 6. 暂停、切换与清理

- 暂停：在宿主停用两个任务（`schedules pause` 只改配置并要求宿主停用实际任务）。
- 查看：`install report`、`status`。清理旧 WSL/systemd 安装只在确实装过时执行；删运行配置不等于删飞书知识库或唯一离线备份。

## 7. 自检与验收

```bash
python -m hostrun.cli install report
python -m hostrun.cli facilities status
python -m hostrun.cli smoke status
python -m hostrun.cli cleanup status
python -m hostrun.cli init status
python -m hostrun.cli schedules status
python -m hostrun.cli audit streak
```

真实结论只看：宿主到点运行日志、飞书真实推送与反馈、清理读回、正式知识读回、两类任务实际触发。没测过写“未实测”，缺能力写“阻塞”。
