# 转移到 Windows 原生环境

本文件是 2026-10-26 那次 WSL → Windows 转移的**唯一交接文件**：项目是什么、原来怎么跑、这次做了什么、到 Windows 上还剩什么要做。

代码侧的决定与取舍见 [`docs/adr/0004-native-windows-python.md`](docs/adr/0004-native-windows-python.md)。

> **现状（2026-10-27 起）**：现行安装与运行方式以 [`INSTALL.md`](INSTALL.md) 为准——宿主 agent 在本机执行，不装 WSL / systemd / 常驻监听。旧的 systemd 安装步骤已归档到 [`docs/legacy/2026-10-systemd-install.md`](docs/legacy/2026-10-systemd-install.md)。本文件保留为那次转移的历史记录，不再作为操作指引。

---

## 1. 项目是什么

一个人用的知识循环流水线：**知识卡片 → 检索 → 排序 → 长文推送 → 飞书评分 → 卡片/命题更新**。

| 模块 | 职责 | 输入 → 输出 |
|---|---|---|
| `frontier` | checkpoint 词汇表 → 检索式 | `frontier.yaml` → `plan.json` |
| `retriever` | 取原文（fixture / arXiv / Europe PMC） | `plan.json` → `candidates.jsonl` |
| `editor` | 排序候选（agent 做语义排序，脚本学偏好） | candidates + ratings → `editor-task.json` → `selection.json` |
| `writer` | 写七段长文推送、校验、渲染自包含 HTML | selection + archive 上下文 → push JSON → HTML |
| `publisher` | 飞书推送、评分卡/审批卡、回调入库 | push + HTML → 消息 / `ratings.jsonl` / `decisions.jsonl` |
| `archive` | 本地缓存与物化视图（原文文本、推送、知识图、命题） | 任意 → `$KL_HOME/archive/**` |
| `knowledge` | 知识五表 ↔ Bitable 镜像、手工编辑回拉、漂移比对 | `KnowledgeStore` → Base 五表 |
| `library` | 云盘原文/推送件 + 四张运维表、配额、对账 | PDF/HTML + Base → 云盘文件 / `library/reports` |
| `question_queue` | 统一问题队列（同一时刻只有一个活动问题） | 评分/更新题 ↔ `$KL_HOME/queue` |
| `trigger` | 定时与手动补推的入口，拉起 headless agent | 关键词 / 定时 → 一次正向链路 |

三条必须记住的架构约束：

1. **模块之间零 Python import**，只通过 `$KL_HOME` 下的文件交换数据；唯一共享代码是根目录 `common.py`（纯 IO 工具）。
2. **飞书是唯一存储**（ADR 0003）：本地 `$KL_HOME` 可丢，靠 Base + 云盘可重建。
3. **editor / writer 不自带模型调用**：它们把要判断的部分打包成 `editor-task.json` / `writer-task.json`，由宿主 agent 读、推理、写回。

---

## 2. 原来怎么跑（转移前的 WSL 状态）

### 2.1 运行环境

| 项 | 值 |
|---|---|
| 仓库 | `~/frontier`（8.4M，含 4.4M `.git`） |
| Python | `/home/chang/miniconda3/bin/python3`（3.13.13） |
| 第三方依赖 | PyYAML；`pytest`（测试）；WeasyPrint（**仅 legacy PDF**，默认 HTML 不需要） |
| 外部 CLI | `lark-cli`（`~/.npm-global/bin`，`@larksuite/cli`）、`opencode`（`~/.opencode/bin`） |
| 数据根 | `$KL_HOME=~/knowledge-loop`（87M） |
| 测试 | 138 个，17 个测试文件 |

### 2.2 数据根结构

```
~/knowledge-loop/
├── archive/      四层物化视图：raw/{text,pages}、pushes/、cards/、propositions/
├── queue/        统一问题队列：state.json / request.json / events.jsonl
├── knowledge/    base.json（Base token + 9 个 table_id）、state.json（镜像基线）
├── publisher/    messages.jsonl、decisions.jsonl、trigger.log、trigger.lock
├── library/      reports/（对账）、cache/config.json（配额配置缓存）
├── state/        checkpoints.yaml
├── cache/raw/    下载缓存（2 个 PDF，58M，可再生）
└── ratings.jsonl 评分明细
```

### 2.3 常驻与定时（systemd user）

`deploy/*.in` 是模板，安装时把 `__PYTHON__` 替换成解释器路径，落在 `~/.config/systemd/user/`。

| 单元 | 类型 | 触发 | ExecStart |
|---|---|---|---|
| `frontier-listener.service` | simple，`Restart=always` | 登录常驻 | `python -m trigger.cli listen` |
| `frontier-rating-listener.service` | simple，`Restart=always` | 登录常驻 | `python -m publisher.cli listen --max-events 0 --timeout 0` |
| `frontier-daily.timer` | oneshot | 每天 08:00 Asia/Shanghai，`Persistent=false` | `python -m trigger.cli scheduled` |
| `frontier-retry.timer` | oneshot | `OnUnitActiveSec=2min` | `python -m trigger.cli run-request --quiet` |
| `frontier-sync.timer` | oneshot | `OnUnitActiveSec=10min` | `knowledge.cli pull` → `sync` → `compare`（compare 允许失败） |
| `frontier-library.timer` | oneshot | 每天 03:30，`Persistent=true` | `library.cli reconcile` → `quota --check` → `publisher.cli alerts`（首尾允许失败） |

两个 listener 的作用：`trigger-listener` 收 `im.message.receive_v1`（私聊「再推一篇」）；`rating-listener` 收 `card.action.trigger`（评分/更新题按钮）。**没有 rating-listener，点按钮不会推进队列。**

服务环境变量：`KL_HOME=%h/knowledge-loop`、`TZ=Asia/Shanghai`、`PATH`（含 `.opencode/bin`、`.npm-global/bin`、conda bin），外加 `EnvironmentFile=%h/.config/frontier/env`。

### 2.4 飞书侧

| 资源 | 值 |
|---|---|
| Base | `B39TbRl04asx1fs57eQczWmLnpf`（租户 `ncnuh1ao6njt`） |
| 表（key → 实际名 / 转移时条数） | `cards` 知识卡片 10 · `propositions` 命题 6 · `evidence` 证据 5 · `papers` 报道 10 · `logs` 变更日志 6 · `sources` 原文 175 · `pushes` 推送日志 0 · `decisions` 决定 0 · `config` 配置 1 |
| 原文目录、推送目录 | token 存在 Base「配置」表（不在本地文件里），所以目录不用单独交接 |
| 事件订阅 | `card.action.trigger`、`im.message.receive_v1`（WebSocket，bot 身份，无需公网 URL） |
| 本机凭据 | `~/.lark-cli/config.json`（user + bot 身份）、`~/.config/frontier/env`（owner open_id） |

### 2.5 agent 接入

三条软链（`git pull` 后自动生效）：

```
~/.config/opencode/skills/frontier       -> ~/frontier
~/.config/opencode/skills/frontier-loop  -> ~/frontier/skills/frontier-loop
~/.agents/skills/frontier-loop           -> ~/frontier/skills/frontier-loop
```

---

## 3. 本次转移记录（2026-10-26）

### 3.1 已停并已删（不可逆）

| 动作 | 对象 |
|---|---|
| 停 + disable | 2 个 listener、4 个 timer 全部 `disable --now`，确认无残留进程 |
| 删 | `~/.config/systemd/user/frontier-*.{service,timer}`（10 个文件）+ `wants/` 软链，`daemon-reload` + `reset-failed` |
| 删 | `~/.config/frontier/env`（owner open_id） |
| 删 | 上述 3 条 skills 软链 |
| 删 | `~/knowledge-loop`：**87M / 1291 文件** |

删除数据根的**永久损失**（这些不在飞书里）：`archive/pushes` 推送正文、`archive/raw/text` 原文文本、13 条 `ratings.jsonl` 评分明细、`queue/` 与 `publisher/` 事件日志、`cache/raw` 2 个 PDF、`library/reports` 对账报告。

**保留的**（云端还在，可从飞书重建）：Base 9 张表（卡片/命题/证据/论文/日志/原文/推送/决定/配置）、云盘原文与推送件。

**没动**：`~/.lark-cli`（全机共用，登出会连带废掉所有 lark-* skill）、飞书 Base / 云盘 / 事件订阅、`~/frontier` 仓库。

### 3.2 代码改动（本次提交）

| 文件 | 改动 | 原因 |
|---|---|---|
| `common.py` | 新增 `temp_dir()` 与 `file_lock()`（POSIX `fcntl.flock` / Windows `msvcrt.locking`） | `fcntl` 在 Windows 不存在；`/tmp` 在 Windows 不存在 |
| `question_queue/store.py` | 删掉顶层 `import fcntl`，`locked()` 改走 `common.file_lock` | 同上是 import 级阻塞 |
| `trigger/service.py` | `job_lock` 改走 `file_lock`；新增 `_kill_tree()`（POSIX `killpg` / Windows `taskkill /F /T`）与 `_agent_argv()`（解析 `opencode.exe`，npm shim 才走 `cmd /c`）；Windows 用 `CREATE_NEW_PROCESS_GROUP` 替代 `start_new_session`；prompt 里的 `/tmp`、`$(date +%F)`、`$FRONTIER_OWNER_ID` 全部换成 Python 侧算好的 `{tmp}` `{date}` `{owner}` | 原生 Windows 能 import、能跑，prompt 不再依赖 bash |
| `scripts/demo.py` | `mkdtemp(dir="/tmp")` → 系统临时目录；第 8 步补 `writer render --format html` 与 `--html` | 同上是路径问题；顺带修 demo 的陈旧调用 |
| `library/drive.py` | 仅注释（`/tmp` → 临时目录） | `tempfile` 本身已跨平台 |
| `requirements.txt` | **新增**：`PyYAML`；注明 `pytest` 与可选 `WeasyPrint` | 之前没有依赖清单，Windows 上无从下手 |
| `INSTALL.md` | 顶部加 Windows 指引；WeasyPrint / 中文字体降为"仅 PDF 需要" | 避免在 Windows 上照抄 WSL 步骤 |
| `docs/adr/0004-native-windows-python.md` | **新增** ADR | 记录取舍 |

顺带修掉两个**与跨平台无关的既有 bug**：

1. `REVIEW_PROMPT.format()` 必抛 `KeyError: 'op=update_proposition_review,'` —— 字面量花括号没转义，命题综述链路一跑就崩（已转义为 `{{...}}`）。
2. `scripts/demo.py` 发推送时不传 `--html`，而 `publisher.cli send` 早已要求 HTML；已补上渲染步骤。

### 3.3 验证结果

```bash
python3 -m pytest -q            # 138 passed
python3 -m compileall -q .      # ok
python3 -c "from trigger import service; service.build_prompt(...)"   # 两个 prompt 都能渲染，无残留 {…}
lark-cli base +table-list --base-token <BASE_TOKEN> --as user          # 9 张表都在，云端未受影响
```

`scripts/demo.py` **仍然不能完整跑通**：fixtures 里的推送是 v2 版式（只有 `body_md`），过不了 v3 的 `writer check`。这是 demo 与 fixtures 的陈旧，不影响 pytest 与主链路，本次不修。

### 3.4 交接凭据

以下两项**只在本会话终端打印过，没有落盘、没有进 git**（翻上面的历史即可）：

- `FRONTIER_OWNER_ID`（飞书 open_id）
- `base_token` + 9 个 `table_id`，形如：

```json
{
  "schema_version": 1,
  "base_token": "<BASE_TOKEN>",
  "base_url": "https://ncnuh1ao6njt.feishu.cn/base/<BASE_TOKEN>",
  "tables": {
    "cards": "<TBL>", "propositions": "<TBL>", "evidence": "<TBL>",
    "papers": "<TBL>", "logs": "<TBL>", "sources": "<TBL>",
    "pushes": "<TBL>", "decisions": "<TBL>", "config": "<TBL>"
  }
}
```

---

## 4. 到 Windows 上要做的（本次未执行）

### 4.1 前置

| 需要 | 检查命令 |
|---|---|
| Python ≥ 3.11 | `python --version` |
| PyYAML | `python -c "import yaml"`（缺则 `pip install pyyaml`） |
| Git | `git --version` |
| Node ≥ 16 + lark-cli | `lark-cli auth status --json`，`identities.user.tokenStatus` 必须是 `valid`，`identities.bot.available` 必须为 `true` |
| 中文输出不乱码 | 建议 `setx PYTHONUTF8 1` |

WeasyPrint、GTK3、Noto CJK **都不需要**（默认推送是自包含 HTML）。

### 4.2 目录与环境变量

```
仓库：<自选>\frontier
数据根：<自选>\knowledge-loop
```

```powershell
setx KL_HOME "D:\knowledge-loop"
setx PYTHONUTF8 1
```

### 4.3 恢复数据根与 Base 配置

```powershell
mkdir "%KL_HOME%"
xcopy /E /I frontier\fixtures\home "%KL_HOME%"
# 再把 3.4 的 JSON 存成 %KL_HOME%\knowledge\base.json
```

`base.json` 是**唯一**连接云端的配置。丢了不会自动重建 —— 代码里没有"创建 Base"的能力，`library.cli setup` 只往已存在的 Base 里建表，需要 `--base-token` 显式指定。

### 4.4 接入 agent

Windows 上 `ln -s` 不可用。两种做法：

- **目录联接（推荐）**：`mklink /J "%USERPROFILE%\.config\opencode\skills\frontier" "<仓库路径>"`（junction 不需要管理员）
- **直接复制**：以后 `git pull` 要重新复制

agent 的 skills 目录：opencode `%USERPROFILE%\.config\opencode\skills`、Claude Code `%USERPROFILE%\.claude\skills`、Codex `%USERPROFILE%\.codex\skills`、其他 `%USERPROFILE%\.agents\skills`。

### 4.5 systemd → 任务计划程序

任务计划程序的**最小重复间隔是 1 分钟**，下列频率都满足。路径里的引号与工作目录要写全，环境变量在任务里单独设置（`KL_HOME`、`FRONTIER_OWNER_ID`、`PATH` 含 python 与 npm 全局 bin）。

| 原单元 | 触发器 | 动作 | 备注 |
|---|---|---|---|
| `frontier-listener` | 登录时 | `python -m trigger.cli listen` | 用 `pythonw.exe` 隐藏窗口；勾"失败后重新启动" |
| `frontier-rating-listener` | 登录时 | `python -m publisher.cli listen --max-events 0 --timeout 0` | 同上 |
| `frontier-daily` | 每天 08:00 | `python -m trigger.cli scheduled` | 对应 `Persistent=false`：错过不补跑 |
| `frontier-retry` | 每 2 分钟 | `python -m trigger.cli run-request --quiet` | |
| `frontier-sync` | 每 10 分钟 | `knowledge.cli pull` → `sync` → `compare` | `compare` 允许非零退出 |
| `frontier-library` | 每天 03:30 | `library.cli reconcile` → `quota --check` → `publisher.cli alerts` | 首尾允许非零退出 |

工作目录统一设为仓库根。日志：任务计划程序只留历史记录，建议在动作里加 `>> "%KL_HOME%\logs\xxx.log" 2>&1`。

### 4.6 验证

```powershell
cd <仓库>
python -m pytest -q                                   # 期望 138 passed
python -m frontier.cli validate                       # 期望 ok: true
python -m frontier.cli plan --out "%TEMP%\frontier-plan.json"   # 不联网，产出 arXiv + Europe PMC 查询
python -m knowledge.cli config                        # 能读到 base.json 即云端配置正确
lark-cli event consume card.action.trigger --as bot --timeout 3s   # 看到 ready 即订阅正常
```

### 4.7 已知的坑

1. **两边不能同时跑**。飞书事件是 bot 级长连接消费，旧 WSL 与 Windows 同时 `listen` 会抢事件、重复推送。本机已停并已清理，启动 Windows 侧前不要再把旧的拉起来。
2. **listener 崩溃不会自动复活**（任务计划程序没有 systemd 的 `Restart=always`），必须显式勾选"失败后重新启动"。
3. **`lark-cli` 上传白名单**：`library/drive.py` 依赖"只接受 cwd / 临时目录 / `~/files` 下的文件"这个行为来上传和下载，Windows 上的具体白名单**没有验证过**。第一次跑 `library.cli reconcile` 时如果报路径错误，先看这里。
4. **`scripts/demo.py` 跑不满**（见 3.3），demo 不是验收标准。
5. 长路径：仓库路径过深可能触发 Win32 260 字符限制，保持在盘符根下一层。
6. 没有 journal：排查只能靠任务计划程序的历史记录或 4.5 里的重定向日志。
