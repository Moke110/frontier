# frontier

个人知识循环：知识卡片 → 检索 → 排序 → 长文推送 → 飞书评分 → 卡片/命题更新。完整操作契约、格式与用户偏好见 [`skills/frontier-loop/SKILL.md`](skills/frontier-loop/SKILL.md)；评分仍不反哺排序。

本仓库当前只有原型，不是生产系统。设计语义来自 `.scratch/knowledge-loop/`（spec + 决策票），实现进度见 `.scratch/frontier-prototypes/map.md`。

## 模块（互不 import）

| 模块 | 职责 | 输入 → 输出 |
|---|---|---|
| `archive` | 四层存储：**原文 / 推送 / 知识图 / 命题列表** | 任意 → `$KL_HOME/archive/**` |
| `frontier` | checkpoint 词汇表 → 检索式；评分反馈到权重（本阶段不启用） | `frontier.yaml` → `plan.json` |
| `retriever` | 按计划取原文（fixture / arXiv / Europe PMC） | `plan.json` → `candidates.jsonl` |
| `editor` | 排序候选；agent 做语义排序，脚本学偏好与校验 | candidates + ratings → `editor-task.json` → `selection.json` |
| `writer` | agent 写长文推送（HTML 片段 + 图片）；脚本提供上下文、校验与渲染 | selection + archive 上下文 → `writer-task.json` → push JSON → HTML（Phase 3） |
| `publisher` | 飞书推送、评分/更新卡与回调 | push + 文件 → 消息 / 卡片 / `ratings.jsonl` / `decisions.jsonl` |
| `knowledge` | 知识层 ↔ Bitable 镜像、手工编辑回拉、漂移比对 | `KnowledgeStore` → Base 五表 / `knowledge/state.json` |
| `library` | 云盘原文/推送件 + 「原文」「推送日志」「决定」「配置」四表；配额、对账、离线清理 | PDF/HTML + Base → 云盘文件 / `library/reports` |

`library` 落地后 `archive` 只管本地缓存与物化视图：原文与推送件的唯一真相在飞书（ADR 0003）。见 `docs/specs/lark-storage.md`。

模块之间**零 Python import**，只通过 `contracts/README.md` 定义的文件交换数据。唯一共享代码是根目录 `common.py`（纯 IO 工具，无领域逻辑）。因此每个模块都能单独跑、单独替换 —— 例如把 `writer` 换成 LLM 版本，或把 `retriever` 换成别的数据源，其它模块不用改。

**editor 与 writer 不内置模型调用。** 它们把需要判断的部分打包成任务文件（`editor-task.json` / `writer-task.json`），由宿主 agent 读取、推理、写回，脚本只做取数与校验。任务契约见 [`contracts/agent-tasks.md`](contracts/agent-tasks.md)。`editor rank` / `writer write` 保留为确定性 fallback，供离线 demo 与测试使用。

## 安装（由你的 agent 执行）

要求：已安装一个 agent（opencode / Claude Code / Codex / Cursor…）、已安装并**登录** `lark-cli`、Python 3.11+ + PyYAML + WeasyPrint，以及至少一种中文字体（Noto CJK）。

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

# library：建表建目录 / 入库 / 取回 / 配额 / 对账 / 清理
python -m library.cli setup --dry-run
python -m library.cli put-source --paper pdf_2025_x --file ~/arc/x.pdf
python -m library.cli put-push --push 2026-10-26_hmbs_01 --html outbox/pushes/2026-10-26_hmbs_01.html
python -m library.cli resolve --paper pdf_2025_x
python -m library.cli quota
python -m library.cli reconcile
python -m library.cli evict --candidates

# publisher：预览 / 发送 / 收评分
python -m publisher.cli preview --push outbox/pushes/2026-10-20_hmbs_01.json
python -m publisher.cli send --push outbox/pushes/2026-10-20_hmbs_01.json --to ou_xxx --dry-run
python -m publisher.cli send --push outbox/pushes/2026-10-20_hmbs_01.json --to ou_xxx
python -m publisher.cli listen --max-events 1 --timeout 10m
```

真实推送需要飞书应用已订阅 `card.action.trigger` 回调（走 WebSocket 长连接，无需公网 URL）。卡片是 Card 2.0，需要客户端 ≥ 7.20。

## 手动补推（飞书关键词）

常驻 listener 订阅 `im.message.receive_v1`；在飞书私聊发 `再推一篇` / `下一篇` / `next` / `more`（可跟 checkpoint id）即可触发一次完整的正向补推。

```bash
python -m trigger.cli listen                 # 前台调试
systemctl --user status frontier-listener         # 关键词监听
systemctl --user status frontier-rating-listener  # 评分卡回调
```

listener 只负责关键词、owner 校验与串行排队，实际排序/写作由 `opencode run --auto` 里的 agent 完成；它不会修改知识库，也不会发审批卡。安装见 `INSTALL.md` §5.5。

## 设计要点（原型版）

- **长文推送**：agent 写七段 HTML 片段与图片资产；Phase 3 起渲染为自包含 HTML（不再用 WeasyPrint 出 PDF）。原文图优先，取不到时用生成图并在图注标源。
- **评分卡**：PDF 后紧跟一张小卡（质量差/不在关注领域 / 质量一般 / 质量优秀，每行一个按钮 + 可选评语）。评分与评语在同一次 `form` 提交里返回；按钮 `name` 决定 verdict。
- **知识更新**：writer 生成 `proposals`（全部 `draft`），经统一队列逐题发飞书卡；同意后由 archive 落盘，拒绝只记决定。每篇推送最多 2 个实体目标（卡片 + 命题合计）。
- **更新提议**：`add_card_ontology` / `update_card_annotation` / `create_card` / `create_proposition` / `update_proposition_title` / `update_proposition_related_knowledge` / `add_proposition_evidence` / `merge_proposition_evidence` / `update_proposition_review`。正式流程由 agent 生成，全部标 `draft`，agent 永不直接改知识库；`writer write` 的术语共现启发式只作为离线 fallback。
- **反哺（本阶段不运行）**：`frontier` 维护 `ema` 与 `weight`（1–10）；`editor.fit` 维护 checkpoint / 来源偏好（Beta 平滑），`rank` 用四项加权：相关性 0.40、时效 0.15、偏好 0.30、权重 0.15。评分目前只落库。
- **确定性**：同一输入重复运行结果一致（`stable_id` 用 FNV-1a），便于测试与复现。

## 原型边界（有意不做）

- writer 的 fallback 仍是四段抽取式模板，不调模型；正式写作由宿主 agent 完成，输出七段 HTML + 图片。retriever 的 live 模式只取摘要；图片由 `writer figures` 单独抓取。
- 无并发写锁、无迁移、无鉴权、无重试队列；飞书 token 的 30 分钟 / 2 次限制未做兜底。
- `archive` 的"事务"是单文件原子写，跨文件更新失败时可能部分生效。
- 评分只做单用户三档；没有冷启动以外的反作弊与去偏。

这些都在 `.scratch/frontier-prototypes/map.md` 的「Not yet specified」里，等原型验证后再决定。
