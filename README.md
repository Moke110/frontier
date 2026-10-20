# frontier

个人知识循环的**原型实现**：checkpoint（前沿）→ 检索 → 排序 → 写作 → 飞书推送 → 评分 → 知识图 / 命题更新提议 → 审批 → 反哺。

本仓库当前只有原型，不是生产系统。设计语义来自 `.scratch/knowledge-loop/`（spec + 决策票），实现进度见 `.scratch/frontier-prototypes/map.md`。

## 六个模块（互不 import）

| 模块 | 职责 | 输入 → 输出 |
|---|---|---|
| `archive` | 四层存储：**原文 / 推送 / 知识图 / 命题列表** | 任意 → `$KL_HOME/archive/**` |
| `frontier` | checkpoint 词汇表 → 检索式；记录评分反馈到权重 | `frontier.yaml` → `plan.json` |
| `retriever` | 按计划取原文（fixture / arXiv / Europe PMC） | `plan.json` → `candidates.jsonl` |
| `editor` | 排序候选；agent 做语义排序，脚本学偏好与校验 | candidates + ratings → `editor-task.json` → `selection.json` |
| `writer` | agent 写四段式推送；脚本提供上下文与校验 | selection + archive 上下文 → `writer-task.json` → push JSON |
| `publisher` | 飞书卡片推送、收集评分、征集更新同意 | push → 卡片 / `ratings.jsonl` / `decisions.jsonl` |

模块之间**零 Python import**，只通过 `contracts/README.md` 定义的文件交换数据。唯一共享代码是根目录 `common.py`（纯 IO 工具，无领域逻辑）。因此每个模块都能单独跑、单独替换 —— 例如把 `writer` 换成 LLM 版本，或把 `retriever` 换成别的数据源，其它模块不用改。

**editor 与 writer 不内置模型调用。** 它们把需要判断的部分打包成任务文件（`editor-task.json` / `writer-task.json`），由宿主 agent 读取、推理、写回，脚本只做取数与校验。任务契约见 [`contracts/agent-tasks.md`](contracts/agent-tasks.md)。`editor rank` / `writer write` 保留为确定性 fallback，供离线 demo 与测试使用。

## 安装（由你的 agent 执行）

要求：已安装一个 agent（opencode / Claude Code / Codex / Cursor…）、已安装并**登录** `lark-cli`、Python 3.11+ + PyYAML。

安装方式不是运行安装脚本，而是把 [`INSTALL.md`](INSTALL.md) 开头的任务说明发给你的 agent。agent 会：

1. 检查 `lark-cli` 是否存在、user/bot 身份是否已登录（未登录会引导你完成授权）；
2. 从 GitHub 克隆 `https://github.com/Moke110/frontier`（默认 `~/frontier`）；
3. 把仓库软链到你所用 agent 的 skills 目录（opencode / Claude Code / Codex / Cursor / `~/.agents/skills`）；
4. 初始化数据根并跑测试与 `frontier validate`；
5. 汇报安装路径，提示你重启 agent。

技能说明在 [`SKILL.md`](SKILL.md)，安装后 agent 会直接读到。

```
frontier.yaml ──> frontier ──> plan.json ──> retriever ──> candidates.jsonl
                     ▲                                          │
                     │                                          ▼
              ratings.jsonl <── publisher <── push <── writer <── editor
                     │                            ▲                │
                     └── editor.fit ──────────────┘                │
                                                                  ▼
                                                    archive (raw / pushes / kg / props)
                                                       ▲          │
                                                       └─ apply ──┘  (审批通过后)
```

## 快速开始

```bash
# 安装：把 INSTALL.md 开头的任务说明发给你的 agent
# （agent 检查 lark-cli 登录 → git clone → 软链到 skills → 验证）

# 离线端到端 demo（临时目录，不联网、不污染仓库）
python scripts/demo.py

# 测试
python -m pytest -q
```

Demo 会依次打印每一步的命令与产物，并在结尾展示：命题多了一条证据、知识卡多了一个别名、知识图多了一个节点、评分权重从 6 升到 7、排序分数变化。Demo 走的是确定性 fallback；正式流程是 agent 读取 `editor-task.json` / `writer-task.json` 后亲自排序与写作。

依赖：Python 3.11+、PyYAML；`publisher` 的**真实发送**额外需要 `lark-cli`（dry-run / offline 模式不需要）。

## 数据根

所有模块读同一个 `$KL_HOME`（默认 `~/knowledge-loop`，与代码仓库分离）：

```bash
export KL_HOME="$HOME/knowledge-loop"
```

目录结构、每层字段、去重键、退出码约定见 [`contracts/README.md`](contracts/README.md)。`fixtures/home/` 是一份可直接复制的最小数据根。

## 各模块单独使用

```bash
# archive：建目录 / 重建索引 / 查上下文
python -m archive.cli init
python -m archive.cli reindex
python -m archive.cli stats
python -m archive.cli context --node kg_hmbs --checkpoint hmbs

# frontier：检查 checkpoint 链接 + 产出检索式
python -m frontier.cli validate
python -m frontier.cli plan --date 2026-10-20 --days 7 --out plan.json
python -m frontier.cli record --checkpoint hmbs --verdict great --pushed

# retriever：offline 用 fixtures；live 走 arXiv + Europe PMC
python -m retriever.cli fetch --plan plan.json --out candidates.jsonl --source fixture
python -m retriever.cli fetch --plan plan.json --out candidates.jsonl --source live

# editor：学偏好；agent 排序（task → 你写 selection → check）
python -m editor.cli fit
python -m editor.cli task --candidates candidates.jsonl --limit 5 --out editor-task.json
#   ……agent 读任务、写 selection.json……
python -m editor.cli check --task editor-task.json --selection selection.json
# 离线 fallback：python -m editor.cli rank --candidates candidates.jsonl --out selection.json

# writer：agent 写作（task → 你写 push → check）；fallback 是 write
python -m writer.cli task --selection selection.json --out writer-task.json
#   ……agent 读任务、写 outbox/pushes/<push_id>.json……
python -m writer.cli check --task writer-task.json --outbox outbox
# 离线 fallback：python -m writer.cli write --selection selection.json --out outbox

# archive：推送入库
python -m archive.cli add-push --file outbox/pushes/2026-10-20_hmbs_01.json

# publisher：预览 / 发送 / 收评分
python -m publisher.cli preview --push outbox/pushes/2026-10-20_hmbs_01.json
python -m publisher.cli send --push outbox/pushes/2026-10-20_hmbs_01.json --to ou_xxx --dry-run
python -m publisher.cli send --push outbox/pushes/2026-10-20_hmbs_01.json --to ou_xxx
python -m publisher.cli listen --max-events 1 --timeout 10m
```

真实推送需要飞书应用已订阅 `card.action.trigger` 回调（走 WebSocket 长连接，无需公网 URL）。卡片是 Card 2.0，需要客户端 ≥ 7.20。

## 设计要点（原型版）

- **评分卡**：正文 + 可选评语 + 三按钮（不相关 / 一般 / 很好）。评分与评语在同一次 `form` 提交里返回；按钮 `name` 决定 verdict。
- **审批卡**：只有当评分不是「不相关」且推送带有 `proposals` 时才发；逐条列出 diff，同意后由 `archive` 写入。
- **更新提议**：`add_evidence` / `add_alias` / `add_proposition` / `update_summary`。正式流程由 agent 生成，全部标 `draft`，agent 永不直接改知识库；`writer write` 的术语共现启发式只作为离线 fallback。
- **反哺**：`frontier` 维护 `ema` 与 `weight`（1–10）；`editor.fit` 维护 checkpoint / 来源偏好（Beta 平滑），`rank` 用四项加权：相关性 0.40、时效 0.15、偏好 0.30、权重 0.15。
- **确定性**：同一输入重复运行结果一致（`stable_id` 用 FNV-1a），便于测试与复现。

## 原型边界（有意不做）

- writer 的 fallback 是抽取式模板，不调模型；正式写作由宿主 agent 完成。retriever 的 live 模式只取摘要，不抓全文 PDF。
- 无并发写锁、无迁移、无鉴权、无重试队列；飞书 token 的 30 分钟 / 2 次限制未做兜底。
- `archive` 的"事务"是单文件原子写，跨文件更新失败时可能部分生效。
- 评分只做单用户三档；没有冷启动以外的反作弊与去偏。

这些都在 `.scratch/frontier-prototypes/map.md` 的「Not yet specified」里，等原型验证后再决定。
