---
name: frontier
description: "Run the personal knowledge loop: turn knowledge cards into retrieval queries, rank papers, write long-form illustrated PDF pushes, send them to Lark, and collect ratings. This phase stops at rating collection; feedback-driven ranking and knowledge-base approval are not enabled. Use when the user wants to run or advance their frontier/knowledge-loop daily workflow."
metadata:
  requires:
    bins: ["python3", "lark-cli"]
---

# frontier

个人知识循环的 agent 技能。agent 负责**排序（editor）与写作（writer）**，脚本负责取数、校验与落盘；所有知识库写入都经过 `archive` CLI。

## 前置条件

1. 已安装一个 agent（opencode / Claude Code / Codex / Cursor，或任意支持 skills 的 agent）。
2. 已安装并登录 `lark-cli`（飞书自建应用、已订阅 `card.action.trigger` 回调）。
3. 本仓库已接入所选 agent 的 skills 目录（如果你是作为技能读到这段，说明已接入）。

安装不是运行脚本，而是让 agent 执行 [`INSTALL.md`](INSTALL.md) 里的任务说明。接入方式是把仓库软链到 agent 的 skills 目录，例如：

- opencode → `~/.config/opencode/skills/frontier`
- Claude Code → `~/.claude/skills/frontier`
- Codex → `~/.codex/skills/frontier`
- Cursor → `~/.cursor/skills/frontier`
- 其他 → `~/.agents/skills/frontier`

自检：

```bash
command -v lark-cli && lark-cli auth status --json
python3 -c "import yaml, weasyprint"
python3 -m pytest -q
```

## 工作目录与数据根

所有命令在**本技能目录（仓库根，含 SKILL.md）**执行：

```bash
export KL_HOME="${KL_HOME:-$HOME/knowledge-loop}"
```

- `archive/cards/`（archive 写）：知识卡片，字段 `id / label / ontology / annotation`；`frontier.yaml` 已退役。
- `state/checkpoints.yaml`（机器写）：按卡片 id 存权重/命中率。
- `archive/`：四层存储 —— 原文、推送、知识卡片、命题。
- 数据格式见 `contracts/README.md`；agent 任务格式见 `contracts/agent-tasks.md`。

## 主循环

### 1. 产出检索式

```bash
python -m frontier.cli validate
python -m frontier.cli plan --date "$(date +%F)" --days 7 --out plan.json
```

`validate` 必须通过：每张知识卡片都要有 `id / label / ontology / annotation`。

### 2. 取原文并入档

```bash
python -m retriever.cli fetch --plan plan.json --out candidates.jsonl --source live
# 离线演练：--source fixture --fixtures fixtures/papers
```

逐条入 archive（`add-paper` 自动按 `source:source_id` 去重）：

```bash
python - <<'PY'
import json, subprocess, tempfile, os
for line in open("candidates.jsonl"):
    row = json.loads(line)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(row, fh, ensure_ascii=False); path = fh.name
    subprocess.run(["python", "-m", "archive.cli", "add-paper", "--file", path], check=True)
    os.unlink(path)
PY
```

### 3. 排序（agent 亲自做）

```bash
python -m editor.cli fit
python -m editor.cli task --candidates candidates.jsonl --date "$(date +%F)" \
  --limit 5 --per-checkpoint 2 --out editor-task.json
```

**你的任务**：读取 `editor-task.json`，按其中 `instructions` 排序，写 `selection.json`。
必须遵守：只用 candidates 里有的论文；每条给 `checkpoint_id` / `paper.paper_id` / `score`(0–1) / `rationale`；不超过 `limits`。

```bash
python -m editor.cli check --task editor-task.json --selection selection.json
```

`check` 不通过就修正后重跑，**不要绕过**。

### 4. 写作（agent 亲自写）

```bash
python -m writer.cli task --selection selection.json --out writer-task.json
python -m writer.cli figures --selection selection.json --out outbox
```

**你的任务**：读取 `writer-task.json`，为每个 item 写 `outbox/pushes/<push_id>.json`：

- 七段：`takeaway / background / methods / results / why / limits / sources`；
- `body_html` 是正文 HTML 片段，不是整页；图片用 `<figure data-asset="fig-1"></figure>` 占位；
- `assets` 用 `figures.json` 的结果；原文图标 `paper`，生成图标 `generated`；
- `why` 必须引用 `context`（知识卡摘要、命题、归档篇数至少其一）；
- 需要时提出 `proposals`（`add_evidence` / `add_alias` / `add_proposition` / `update_summary`），全部 `status: draft`；
- **绝不直接编辑** `$KL_HOME/archive/**`。

```bash
python -m writer.cli check --task writer-task.json --outbox outbox
python -m writer.cli render --push outbox/pushes/<push_id>.json --out outbox/<push_id>.pdf
python -m archive.cli add-push --file outbox/pushes/<push_id>.json
```

### 5. 推送与评分

```bash
python -m publisher.cli send --push outbox/pushes/<push_id>.json --pdf outbox/<push_id>.pdf --to ou_xxx
python -m publisher.cli listen --max-events 1 --timeout 10m
```

- `send` 是**对外可见**操作：先向用户确认收件人、PDF 与条数。
- 没有后台监听能力时，改用 `ingest` 回放导出的 NDJSON 事件。
- 无飞书环境演练：`--dry-run`（send）与 `--offline`（ingest）。

### 5.5 手动补推（飞书关键词）

常驻 listener 订阅 `im.message.receive_v1`，只接受 owner 私聊的固定关键词：

- `再推一篇` / `下一篇` / `next` / `more`；
- 可跟知识卡片 id 或 label，如 `再推一篇 card_hmbs`；不带时按默认规则选一个。

```bash
python -m trigger.cli listen                 # 前台常驻（调试）
systemctl --user status frontier-listener         # 关键词监听
systemctl --user status frontier-rating-listener  # 评分卡回调
journalctl --user -u frontier-listener -f         # 看触发日志
```

listener 只做关键词识别、owner 校验、串行排队，然后调用
`opencode run --auto` 执行一次正向补推；它不排序、不写作、不改知识库。

### 6. 评分之后（本阶段不启用）

评分只写入 `ratings.jsonl`，**不**运行 `frontier record` / `editor fit`，**不**发知识更新审批卡，**不**写知识图或命题。下游的反馈调整与知识库审批留到下一阶段。

## 硬规则

- **agent 是 editor 与 writer**：不要调用外部 LLM API 来替代自己；排序和写作就是你在做。
- **不编造**：论文必须来自 candidates；证据、别名、命题必须能追溯到任务里的 context 或你刚读到的 archive 数据。
- **知识库只写提议**：`proposals` 一律 `draft`，等用户评分 + 同意后才应用。
- **先 check 再入库**：`editor check`、`writer check` 失败就修，不得手改校验器或跳过。
- **推送前确认**：收件人、条数、内容都要让用户点头；测试优先 `--dry-run`。

## 故障排查

| 现象 | 处理 |
|---|---|
| `event consume` 报 `failed_precondition` | 飞书开发者后台订阅 `card.action.trigger`（WebSocket，无需公网 URL） |
| 发卡报 `missing scope` | 按返回的 `missing_scope` 重新授权 |
| 卡片只显示 header | 客户端 < 7.20，升级飞书 |
| `lark-cli --file` 报 `unsafe file path` | 只传当前工作目录下的相对路径 |
| 排序任务很大 | 缩小 `--limit` 或按 checkpoint 分批 `editor task` |

## 参考

- `contracts/README.md`：六模块文件契约。
- `contracts/agent-tasks.md`：editor / writer 任务包与校验规则。
- `README.md`：安装、目录结构、原型边界。
- `fixtures/`：可直接复制的数据根与离线论文。
