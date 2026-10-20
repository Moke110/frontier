---
name: frontier
description: "Run the personal knowledge loop: turn checkpoints into retrieval queries, rank papers, write four-section Lark pushes, collect ratings, propose/approve knowledge-graph and proposition updates, and feed ratings back into ranking. Use when the user wants to run or advance their frontier/knowledge-loop daily workflow."
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
python3 -c "import yaml"
python3 -m pytest -q
```

## 工作目录与数据根

所有命令在**本技能目录（仓库根，含 SKILL.md）**执行：

```bash
export KL_HOME="${KL_HOME:-$HOME/knowledge-loop}"
```

- `frontier.yaml`（人写）：checkpoint 词汇表；可从 `fixtures/home/frontier.yaml` 复制起步。
- `state/checkpoints.yaml`（机器写）：权重/命中率。
- `archive/`：四层存储 —— 原文、推送、知识图、命题。
- 数据格式见 `contracts/README.md`；agent 任务格式见 `contracts/agent-tasks.md`。

## 主循环

### 1. 产出检索式

```bash
python -m frontier.cli validate
python -m frontier.cli plan --date "$(date +%F)" --days 7 --out plan.json
```

`validate` 必须通过：每个 checkpoint 的 `kg_node_id` 都要指向 `archive/kg/nodes/` 里真实存在的知识卡。

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
```

**你的任务**：读取 `writer-task.json`，为每个 item 写 `outbox/pushes/<push_id>.json`：

- 四段：`did / found / why / keep`；
- `why` 必须引用 `context`（知识卡摘要、命题、归档篇数至少其一）；
- 需要时提出 `proposals`（`add_evidence` / `add_alias` / `add_proposition` / `update_summary`），全部 `status: draft`；
- **绝不直接编辑** `$KL_HOME/archive/**`。

```bash
python -m writer.cli check --task writer-task.json --outbox outbox
python -m archive.cli add-push --file outbox/pushes/<push_id>.json
```

### 5. 推送与评分

```bash
python -m publisher.cli send --push outbox/pushes/<push_id>.json --to ou_xxx
python -m publisher.cli listen --max-events 1 --timeout 10m
```

- `send` 是**对外可见**操作：先向用户确认收件人与条数。
- 没有后台监听能力时，改用 `ingest` 回放导出的 NDJSON 事件。
- 无飞书环境演练：`--dry-run`（send）与 `--offline`（ingest）。

### 6. 反哺

```bash
python -m frontier.cli record --checkpoint hmbs --verdict great --pushed
python -m editor.cli fit
```

`record` 更新 `ema` / `weight`；`fit` 更新 checkpoint 与来源偏好；下一轮 `editor task` 自动带上。

### 7. 知识库更新（审批后）

评分非「不相关」且 push 带 proposals 时，publisher 会发审批卡。用户同意后：

```bash
python -m archive.cli apply-decisions \
  --pending-dir "$KL_HOME/publisher/pending" \
  --decisions "$KL_HOME/publisher/decisions.jsonl"
```

只有这一步会真正修改知识图 / 命题。

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
