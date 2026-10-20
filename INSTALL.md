# 安装 frontier（由你的 agent 执行）

把下面这段发给你的 agent（opencode / Claude Code / Codex / Cursor / 其他）：

> 请安装 frontier。先从 https://github.com/Moke110/frontier 获取代码，克隆到 `~/frontier`，然后严格按仓库里的 `INSTALL.md` 执行：检查 `lark-cli` 是否已安装并登录，把仓库接入当前 agent 的 skills 目录，初始化数据，最后做一次验证。任何一步失败就停下来告诉我原因，不要跳过检查。

---

## 给 agent 的执行步骤

### 0. 原则

- **先检查，后写入。** 任一前置条件不满足就停止，不要“先装再说”。
- **不覆盖用户数据。** 目标目录、`data/`、skills 目录里已有内容时，先询问。
- **不打印密钥。** `lark-cli auth status --json` 的输出里可能带 token，只汇报身份与状态。

### 1. 确认 Lark CLI 已安装并登录

```bash
command -v lark-cli
lark-cli auth status --json
```

判断标准：

- `command -v lark-cli` 有输出（不在 PATH 就停止，让用户先安装）；
- JSON 中 `identities.user.available == true`，且 `identities.user.tokenStatus == "valid"`；
- `identities.bot.available == true`（卡片推送走 bot 身份）。

如果已安装但未登录：运行 `lark-cli auth login`，让用户在飞书里完成授权，**等状态变为 ready 再继续**。不要伪造成功。

可选诊断（不阻塞安装）：卡片回调是否已订阅。

```bash
lark-cli event consume card.action.trigger --as bot --timeout 3s
```

看到 `ready event_key=card.action.trigger` 即已订阅；看到 `failed_precondition` 就提醒用户去开发者后台订阅回调（WebSocket，无需公网 URL）。

### 2. 检查运行环境

```bash
git --version
python3 --version          # 需要 >= 3.11
python3 -c "import yaml"   # 需要 PyYAML
```

缺 PyYAML 时先问用户是否允许安装（`pip install pyyaml`），不要擅自改系统环境。

### 3. 从 GitHub 获取代码与技能文档

默认目录 `~/frontier`：

```bash
# 不存在
git clone https://github.com/Moke110/frontier.git ~/frontier

# 已存在且是 frontier 仓库
git -C ~/frontier pull --ff-only
```

如果 `~/frontier` 已存在但不是这个仓库，停止并询问用户换目录。

确认这些文件存在：

```bash
ls ~/frontier/SKILL.md ~/frontier/contracts/README.md ~/frontier/archive/cli.py
```

`SKILL.md` 是接入后 agent 使用的技能说明；`contracts/` 是模块间文件契约。

### 4. 接入当前 agent

先确认你自己是哪种 agent，再选对应目录：

| 当前 agent | skills 目录 |
|---|---|
| opencode | `~/.config/opencode/skills` |
| Claude Code | `~/.claude/skills` |
| Codex | `~/.codex/skills` |
| Cursor | `~/.cursor/skills` |
| 其他 / 不确定 | `~/.agents/skills` |

创建软链（推荐，`git pull` 后自动更新）：

```bash
SKILLS_DIR="$HOME/.config/opencode/skills"   # 按上表替换
mkdir -p "$SKILLS_DIR"

if [ -L "$SKILLS_DIR/frontier" ]; then
  echo "already linked: $(readlink "$SKILLS_DIR/frontier")"
elif [ -e "$SKILLS_DIR/frontier" ]; then
  echo "STOP: $SKILLS_DIR/frontier 已存在且不是软链，请询问用户"
else
  ln -s "$HOME/frontier" "$SKILLS_DIR/frontier"
fi
```

若所选 agent 不支持软链，改为复制（并告诉用户以后更新要重新复制）：

```bash
cp -R "$HOME/frontier" "$SKILLS_DIR/frontier"
```

### 5. 初始化数据（可选，但推荐）

数据根默认 `~/knowledge-loop`（与代码仓库分离）。如果目录为空，复制 fixtures 作为起点：

```bash
export KL_HOME="${KL_HOME:-$HOME/knowledge-loop}"
mkdir -p "$KL_HOME"
if [ -z "$(ls -A "$KL_HOME" 2>/dev/null)" ]; then
  cp -R "$HOME/frontier/fixtures/home/." "$KL_HOME/"
fi
```

**已有数据时不要覆盖**；先问用户用哪个数据根。之后 agent 执行技能时都需要设置 `KL_HOME`。

### 6. 验证

```bash
cd "$HOME/frontier"
python3 -m pytest -q                          # 应全部通过（当前 18 个）
KL_HOME="$HOME/knowledge-loop" python3 -m frontier.cli validate
KL_HOME="$HOME/knowledge-loop" python3 -m frontier.cli plan --out /tmp/frontier-plan.json
```

`validate` 应返回 `ok: true`；`plan` 应生成包含 arXiv 与 Europe PMC 查询的 JSON（不联网）。

### 7. 汇报给用户

输出并让用户确认：

- 仓库路径：`~/frontier`
- 技能目录：例如 `~/.config/opencode/skills/frontier`
- 数据根：`KL_HOME=...`
- Lark 登录身份：user / bot 是否 ready
- 验证结果：测试通过数、`validate` 是否 ok
- 下一步：**重启 agent**，然后说「跑一下 frontier 的今日循环」

### 8. 卸载（用户要求时）

```bash
rm "$HOME/.config/opencode/skills/frontier"   # 只删软链
# 数据在 ~/knowledge-loop，默认保留；删除前必须再确认
```

## 故障

| 现象 | 处理 |
|---|---|
| `lark-cli: command not found` | 停止，让用户先安装 Lark CLI |
| `auth status` 里 user 不可用 | 运行 `lark-cli auth login`，等用户完成 |
| `event consume` 报 `failed_precondition` | 飞书开发者后台订阅 `card.action.trigger` |
| skills 目录已有同名文件 | 停止并询问，不要覆盖 |
| `python3 -c "import yaml"` 失败 | 询问后安装 PyYAML |
| `pytest` 失败 | 停止，把失败输出贴给用户，不要继续接入 |
