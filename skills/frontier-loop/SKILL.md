---
name: frontier-loop
description: "Run the personal knowledge loop end to end: turn knowledge cards into retrieval queries, rank papers, write long-form HTML pushes, send them to Lark, collect ratings, and update knowledge cards / proposition evidence / proposition reviews through one serial question queue. Use when the user wants to run or advance their frontier daily workflow, or asks to add/update evidence for a proposition."
metadata:
  requires:
    bins: ["python3", "lark-cli"]
---

# frontier-loop

个人知识循环的主 skill。agent 负责**排序（editor）与写作（writer）**；脚本负责取数、校验、入队、落盘。所有知识库写入都经过 archive / `KnowledgeStore`，agent 不直接改存储。

> **实施阶段**（同一份契约分三步落地）：
>
> | 能力 | 状态 |
> |---|---|
> | 每篇推送 2 个实体名额；三类卡片顶栏/正文 | 已生效（Phase 1） |
> | 命题 v3（evidence / review / changelog）、证据 add/merge、迁移 | 已生效（Phase 2a） |
> | 综述题、HTML 推送 | 已生效（Phase 2b） |
> | Bitable 镜像、手工编辑回拉、10 分钟同步 | 已生效（Phase 3a，双读期） |
> | Bitable 权威读、WAL 落盘、下线文件写入 | Phase 3b（双读 7 天后） |
>
> Phase 2/3 的命令在文中标注；未标注的均为当前可用命令。

## 1. 前置条件与数据根

1. 已安装支持 skills 的 agent（opencode / Claude Code / Codex / Cursor）。
2. `lark-cli` 已登录，飞书应用已订阅 `card.action.trigger`。
3. 仓库已软链到 agent 的 skills 目录（读到这段即已接入）。

所有命令在**本仓库根**执行：

```bash
export KL_HOME="${KL_HOME:-$HOME/knowledge-loop}"
```

```bash
command -v lark-cli && lark-cli auth status --json
python3 -c "import yaml, weasyprint"
python3 -m pytest -q
```

## 2. 领域模型

### 知识卡片

`id / label / ontology / annotation`。卡片不存任何链接；连接只存在于命题的 `related_knowledge`。

- `ontology` 驱动召回；`annotation` 驱动精确性（定义、排除项、易混项）。
- id 形如 `card_hmbs`；语义 slug，冲突追加 `_2`。

### 命题

`id / title / review / related_knowledge / evidence / changelog / evidence_updates_since_review`。

- `related_knowledge` 至少 2 张已存在卡片。
- **新建命题必须带 ≥2 条 evidence**；没有证据的命题不入库。
- `review` 是综述；`evidence` 是证据条目；`changelog` 只记 title / review / related_knowledge 的变更。
- 旧 `history[].evidence` 在迁移时拆成 evidence 条目，标 `migrated_from_v2`。

### 证据条目

```json
{
  "id": "ev_virtual_cell_perturbation_01",
  "stance": "supports | contradicts",
  "conclusion": "≤200 字，只概括方向一致的报道结论",
  "papers": [
    {
      "paper_id": "arxiv_2610.25021v1",
      "push_id": "2026-10-20_card_virtual_cell_02",
      "page": 4,
      "quote": "原文引文，8–500 字",
      "added_at": "2026-10-20T09:00:00+08:00"
    }
  ],
  "created_at": "…",
  "updated_at": "…"
}
```

- 一条 evidence 内**只放方向一致的报道**；同一命题下可以存在互相矛盾的 evidence。
- `stance` 相对命题标题：`supports` = 支持，`contradicts` = 反证。
- 新报道与某条 evidence 同立场且结论同向 → 并入该条（追加 `papers[]`、可改写 `conclusion`、更新 `updated_at`）；异向 → 新建一条。

### 综述 review

- ≤2000 字，固定四节：**结论 / 支持证据 / 反证与边界 / 待验证**；每节 1–3 段。
- 基于当前全部 evidence，不引入 evidence 之外的新事实。
- 每采纳 10 条证据更新自动重写一次；被拒后保留计数，下一条证据被采纳时重试。

### 变更日志 changelog

只记非证据变更：`at / action / field / before / after / rationale / source`。review 的上一版从 changelog 取，用于生成 diff。

## 3. 主循环

### 3.1 检索计划

```bash
python -m frontier.cli validate
python -m frontier.cli plan --date "$(date +%F)" --days 7 --out plan.json
```

每张卡片必须有 `id / label / ontology / annotation`。

### 3.2 取原文并入档

```bash
python -m retriever.cli fetch --plan plan.json --out candidates.jsonl --source live
# 离线：--source fixture --fixtures fixtures/papers
```

逐条 `python -m archive.cli add-paper --file <json>`；`add-paper` 按 `source:source_id` 去重。

### 3.3 排序（agent 亲自做）

```bash
python -m editor.cli fit
python -m editor.cli task --candidates candidates.jsonl --date "$(date +%F)" \
  --limit 5 --per-checkpoint 2 --out editor-task.json
```

读 `editor-task.json`，按 `instructions` 写 `selection.json`：

- 只用 candidates 里有的论文；
- 每条给 `checkpoint_id` / `paper.paper_id` / `score`(0–1) / `rationale`；
- 不超过 `limits`。

```bash
python -m editor.cli check --task editor-task.json --selection selection.json
```

不通过就修正，**不要绕过**。

### 3.4 写作与推送（agent 亲自写）

```bash
python -m writer.cli task --selection selection.json --out writer-task.json
python -m writer.cli figures --selection selection.json --out outbox
```

为每个 item 写 `outbox/pushes/<push_id>.json`：

- 七段：`takeaway / background / methods / results / why / limits / sources`；
- `body_html` 是正文片段，图片用 `<figure data-asset="fig-1"></figure>` 占位；
- `assets` 用 `figures.json` 的结果；原文图标 `paper`，生成图标 `generated`；
- `why` 必须引用 `context`（卡片摘要、命题、归档篇数至少其一）；
- proposals 一律 `status: draft`，绝不直接写知识库。

Phase 3 起渲染为**自包含 HTML**（不再是 PDF）：

```bash
python -m writer.cli check --task writer-task.json --outbox outbox
python -m writer.cli render --push outbox/pushes/<push_id>.json --out outbox/<push_id>.html
python -m archive.cli add-push --file outbox/pushes/<push_id>.json
python -m library.cli ensure-source --paper <push 里的 paper_id>
```

`ensure-source` 把原文 PDF 传进云盘「原文」库并在 Base 登记；付费墙拿不到 PDF 时记 `无原件`，不阻断推送。推送件在 `publisher send` 成功后自动入库。

### 3.5 入队与发送

```bash
python -m publisher.cli send --push outbox/pushes/<push_id>.json --html outbox/<push_id>.html --to ou_xxx
python -m publisher.cli listen --max-events 1 --timeout 10m
```

- `send` 是**对外可见**操作：先向用户确认收件人、文件与条数。
- 只发送当前 active 题；一题答完才发下一题。
- 无飞书环境：`--dry-run`（send）与 `--offline`（ingest）。
- 查看队列：`python -m question_queue.cli status`。

### 3.6 评分

- `irrelevant / ok / great`；本阶段评分只用于闸门，不反哺排序。
- `irrelevant` → 该 push 的更新题全部 `dropped`。

### 3.7 更新题（卡片 / 证据）

- 同意 → 立即写入（Phase 3：WAL + Bitable）；拒绝 → 只写 `publisher/decisions.jsonl`。
- 同一目标的多个 proposals 合并成一题；每篇推送最多 **2 个实体目标**。
- 证据题只处理一个命题；卡片题只处理一个卡片。

### 3.8 综述题

- 第 10 条证据被采纳 → 队列追加 `proposition_review` 题（`ready=false`），占住闸门。
- 监听器拉起 `trigger.cli review-request --item <id>`，agent 执行：
  `writer.cli review-task` → 写 review JSON → `review-check` → `review-render` →
  `question_queue.cli review-ready` → `publisher.cli deliver`。
- 综述 HTML + 确认卡推送；`采纳此版` 写入并清零计数，`保持上一版` 保留计数。
- 综述题不占每篇推送的 2 个实体名额。

### 3.9 队列清空后

- 队列清空且无 failed → 执行待推请求（手动「再推一篇」或每日 08:00）。
- 有 failed 时队列闸住，用 `question_queue.cli retry/abandon` 处理。

## 4. 更新契约

### 4.1 名额

- 每篇推送最多 **2 个实体目标**，知识卡片 + 命题合计，**新建也占名额**。
- 同一目标的多个操作合并成一题，不重复占名额。
- 超额时按 `proposals` 数组顺序全局取前 2；`writer check` 直接拒绝 >2。
- 综述题独立，不占名额。

### 4.2 操作表

| `op` | 目标 | `diff.path` / `value` |
|---|---|---|
| `add_card_ontology` | 已有卡片 | `ontology` / 新词或词列表 |
| `update_card_annotation` | 已有卡片 | `annotation` / 新文本 |
| `create_card` | 无 | `card` / `{id?, label, ontology, annotation}` |
| `create_proposition` | 无 | `proposition` / `{id?, title, review, related_knowledge, evidence[≥2]}` |
| `update_proposition_title` | 已有命题 | `title` / 新标题 |
| `update_proposition_related_knowledge` | 已有命题 | `related_knowledge` / ≥2 卡 id |
| `add_proposition_evidence` | 已有命题 | `evidence` / 新条目 `{conclusion, stance, papers[]}` |
| `merge_proposition_evidence` | 已有命题 | `evidence` / `{target_evidence_id, papers[], conclusion?}` |
| `update_proposition_review` | 已有命题 | `review` / 新综述（仅综述题使用） |

硬规则：

1. `before` 必须等于写入时的当前值（防陈旧 diff）；`after` 必须等于 `diff.value` 或按操作表推导。
2. `evidence.paper_id` 必须是本次 `push.paper_ids` 之一；`page` 为 ≥1 整数或 `null`（摘要）；`quote` 8–500 字且可在原文定位。
3. `create_proposition.related_knowledge` ≥2 张已存在卡片；本次新建的卡片不能立刻被新命题引用。
4. `create_proposition` 必须带 ≥2 条 evidence；每条 evidence 的 `conclusion` ≤200 字。
5. `proposal_id` 形如 `p_<push_id>_<NN>`；`status` 只能 `draft`。
6. writer 永不直接写 archive / Bitable。

### 4.3 证据规则

- 每条 evidence 只放**方向一致**的报道；反证单独成条。
- 同立场且结论同向 → `merge_proposition_evidence`；否则 `add_proposition_evidence`。
- 一条 evidence 至少对应一篇报道；同一结论可以归并多篇。
- 计数：每采纳一条 add/merge 提议 +1（不是按报道篇数）；满 10 触发综述。

### 4.4 综述规则

- 四节固定，≤2000 字；只基于 evidence。
- diff 按段落/句子对齐，内联红/绿，颜色降饱和（背景 `#fdecec` / `#e8f5e9`，文字保持正文色）。
- 证据按 `supports` / `contradicts` 分组；引文放在 `<details>` 里折叠。
- 被拒后保留计数，下一条证据被采纳时重新生成，不立即连问。

## 5. 三类飞书卡

顶栏标题 = 类型 + 进度，**无副标题**：

- `知识卡片更新 · 第 N / M 题`
- `命题证据更新 · 第 N / M 题`
- `命题综述更新 · 第 N / M 题`

正文第一行必须是实体 id/title：

- 卡片：`**`card_hmbs`** · HMBS`；
- 命题：`**`prop_xxx`** · 标题`；
- 新建：`**新建知识卡片** · label` / `**新建命题** · title`。

卡片更新正文：来源论文 → 变更项（ontology / annotation 行级 diff）→ 依据 → 理由 + 置信度。
证据更新正文：来源论文 → 立场徽标 → 新结论 → 报道/页码/引文 → 归并目标。
综述更新正文：证据计数（支持 X / 反证 Y）→ diff 行数 → Base 记录链接。

按钮：

- 卡片/证据：`同意全部`（左，蓝）/ `拒绝全部`（右，红）；
- 综述：`采纳此版`（左，蓝）/ `保持上一版`（右，红）。

页脚统一说明：同意后立即写入；拒绝保持原样；答完才发下一题。

## 6. 落盘

**Phase 3a（当前，双读期）**：

- 本地 `archive/` 仍是读与写的权威；Bitable 是镜像。
- 每次同意更新后，spawn `python -m knowledge.cli sync`：按业务 id 幂等 upsert 卡片 / 命题 / 证据 / 报道 / 变更日志，并重建关联。
- `frontier-sync.timer` 每 10 分钟：`knowledge.cli pull`（把 Bitable 文本列的手工编辑拉回本地并补 changelog）→ `sync` → `compare`（只记差异，不让 timer 失败）。
- 首次 `pull` 只建立 `knowledge/state.json` 基线；之后只接受 title / review / annotation / conclusion 的文本改动。
- 非法编辑不落本地：在 Base 的「待修正」列写原因。

**Phase 3b（双读 7 天后）**：

- Bitable 成为知识层唯一真相；本地 JSON 转为只读快照。
- 读：`KnowledgeStore` 实时读 Bitable；测试与 `--offline` 用 `FixtureStore`。
- 写：本地 WAL（pending + proposals + before 快照）→ 逐条写 Bitable；按 `group_id` 幂等，失败断点续跑。
- 写前校验：id 唯一、≥2 关联卡、conclusion ≤200、review ≤2000、quote 可定位、paper_id ∈ push、before 不陈旧。

## 7. 手工编辑与同步（Phase 3）

- 只动文本列：`title / review / conclusion / annotation`；结构列（id、关联、日期、计数）只读。
- 编辑视图隐藏结构列；这是约定，不是强制权限。
- 每 10 分钟扫描 Bitable 与本地「上次已见」台账：文本变化补一条 changelog；校验失败写「待修正」，不静默接受。

## 8. 用户偏好与硬规则

- 中文、克制、具体；不写空话套话。
- **不编造**：论文只来自 candidates；证据、别名、命题必须可追溯。
- 知识库只写提议；同意后才落盘。
- 先 `check` 再入库；校验失败就修，不改校验器。
- 推送前确认收件人、文件、条数；测试优先 `--dry-run`。
- 结论 ≤200 字、综述 ≤2000 字是硬上限。
- HTML 排版：正文 `clamp(16px, 1.1vw + 12px, 20px)`、行高 1.85、最大宽 40em、系统字体、跟随深色模式；图片 100% 宽；表格可横向滚动。

## 9. 故障排查

| 现象 | 处理 |
|---|---|
| `event consume` 报 `failed_precondition` | 飞书后台订阅 `card.action.trigger`（WebSocket） |
| 发卡报 `missing scope` | 按 `missing_scope` 重新授权 |
| 卡片只显示 header | 客户端 < 7.20，升级飞书 |
| `lark-cli --file` 报 `unsafe file path` | 只传当前工作目录下的相对路径 |
| 队列闸住 | `question_queue.cli status`，再 `retry` / `abandon` |
| Bitable 写入部分成功（Phase 3） | 查 group journal，`retry` 从断点继续，不重复写 |

## 10. 参考

- `contracts/README.md`：模块文件契约。
- `contracts/agent-tasks.md`：editor / writer 任务包与校验规则。
- `docs/specs/unified-question-queue.md`：队列状态机与闸门。
- `docs/adr/`：知识卡片、命题 v3、Bitable 权威等决策记录。
- `fixtures/`：离线数据根与论文。
