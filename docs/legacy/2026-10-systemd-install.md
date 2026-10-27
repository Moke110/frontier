# 【已归档】systemd / WSL 时代的安装说明

> **不要再按本文件安装。** 现行入口是仓库根目录的 [`README.md`](../../README.md)：由宿主 agent（WorkBuddy / ChatGPT 桌面端）在本机执行安装、调度与恢复，不装 systemd、不装常驻监听、不写持久环境变量。
>
> 保留本文件只为两件事：查历史决策，以及**识别并清理**你机器上仍然存在的旧单元（见文末「清理」）。文中的 `deploy/*.service.in` 与 `deploy/*.timer.in` 现已标注为 legacy，不再被任何现行流程引用。

# 安装 frontier（由你的 agent 执行）

把下面这段发给你的 agent（opencode / Claude Code / Codex / Cursor / 其他）：

> 请安装 frontier。先从 https://github.com/Moke110/frontier 获取代码，克隆到 `~/frontier`，然后严格按仓库里的 `INSTALL.md` 执行：检查 `lark-cli` 是否已安装并登录，把仓库接入当前 agent 的 skills 目录，初始化数据，最后做一次验证。任何一步失败就停下来告诉我原因，不要跳过检查。

> **Windows 原生环境（非 WSL）不要照本文件走**，见 [Windows 转移历史](https://github.com/Moke110/frontier/blob/18a687d/WINDOWS-TRANSFER.md)：systemd 单元、`fc-list`、WeasyPrint 依赖都不适用。

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

检查两个事件订阅（缺一个都会让对应功能失效）：

```bash
# 评分卡按钮回调
lark-cli event consume card.action.trigger --as bot --timeout 3s

# 手动补推关键词（「再推一篇」）
lark-cli event consume im.message.receive_v1 --as bot --timeout 3s
```

看到 `ready event_key=...` 即已订阅；看到 `failed_precondition` 就提醒用户去开发者后台订阅对应事件（WebSocket，无需公网 URL）。

### 2. 检查运行环境

```bash
git --version
python3 --version              # 需要 >= 3.11
python3 -c "import yaml"       # 需要 PyYAML
python3 -c "import weasyprint" # 可选：仅 legacy PDF 推送需要（默认 HTML 不需要）
fc-list :lang=zh | head -1     # 至少一种中文字体（仅 PDF 渲染需要）
```

缺 PyYAML 时先问用户是否允许安装（`pip install pyyaml`），不要擅自改系统环境。WeasyPrint 与中文字体只服务 `writer render --format pdf`；默认推送是自包含 HTML，不装也能跑完整流程。

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

for name in frontier frontier-loop; do
  target="$HOME/frontier"
  [ "$name" = "frontier-loop" ] && target="$HOME/frontier/skills/frontier-loop"
  if [ -L "$SKILLS_DIR/$name" ]; then
    echo "already linked: $name -> $(readlink "$SKILLS_DIR/$name")"
  elif [ -e "$SKILLS_DIR/$name" ]; then
    echo "STOP: $SKILLS_DIR/$name 已存在且不是软链，请询问用户"
  else
    ln -s "$target" "$SKILLS_DIR/$name"
  fi
done
```

`frontier` 是入口（转发到 `skills/frontier-loop/SKILL.md`）；`frontier-loop` 是完整流程 skill，两者都需要接入。

若所选 agent 不支持软链，改为复制（并告诉用户以后更新要重新复制）：

```bash
cp -R "$HOME/frontier" "$SKILLS_DIR/frontier"
cp -R "$HOME/frontier/skills/frontier-loop" "$SKILLS_DIR/frontier-loop"
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

### 5.5 常驻手动补推（可选，但推荐）

需要 systemd user 会话（WSL 默认已开启）。先拿到用户在飞书的 open_id：

```bash
OWNER=$(lark-cli auth list --json | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['userOpenId'])")
mkdir -p "$HOME/.config/frontier" "$HOME/.config/systemd/user"
printf 'FRONTIER_OWNER_ID=%s\n' "$OWNER" > "$HOME/.config/frontier/env"

sed "s|__PYTHON__|$(command -v python3)|" \
  "$HOME/frontier/deploy/frontier-listener.service.in" \
  > "$HOME/.config/systemd/user/frontier-listener.service"
sed "s|__PYTHON__|$(command -v python3)|" \
  "$HOME/frontier/deploy/frontier-rating-listener.service.in" \
  > "$HOME/.config/systemd/user/frontier-rating-listener.service"
sed "s|__PYTHON__|$(command -v python3)|" \
  "$HOME/frontier/deploy/frontier-daily.service.in" \
  > "$HOME/.config/systemd/user/frontier-daily.service"
cp "$HOME/frontier/deploy/frontier-daily.timer.in" \
  "$HOME/.config/systemd/user/frontier-daily.timer"
sed "s|__PYTHON__|$(command -v python3)|" \
  "$HOME/frontier/deploy/frontier-retry.service.in" \
  > "$HOME/.config/systemd/user/frontier-retry.service"
cp "$HOME/frontier/deploy/frontier-retry.timer.in" \
  "$HOME/.config/systemd/user/frontier-retry.timer"
sed "s|__PYTHON__|$(command -v python3)|" \
  "$HOME/frontier/deploy/frontier-sync.service.in" \
  > "$HOME/.config/systemd/user/frontier-sync.service"
cp "$HOME/frontier/deploy/frontier-sync.timer.in" \
  "$HOME/.config/systemd/user/frontier-sync.timer"
sed "s|__PYTHON__|$(command -v python3)|" \
  "$HOME/frontier/deploy/frontier-library.service.in" \
  > "$HOME/.config/systemd/user/frontier-library.service"
cp "$HOME/frontier/deploy/frontier-library.timer.in" \
  "$HOME/.config/systemd/user/frontier-library.timer"

systemctl --user daemon-reload
systemctl --user enable --now frontier-listener frontier-rating-listener
systemctl --user enable --now frontier-daily.timer frontier-retry.timer frontier-sync.timer frontier-library.timer
systemctl --user is-active frontier-listener frontier-rating-listener   # 都应输出 active
systemctl --user list-timers frontier-daily.timer                       # 下一次 08:00
```

三个服务/定时器缺一不可：

- `frontier-listener`：收 `im.message.receive_v1`（手动补推关键词）；
- `frontier-rating-listener`：收 `card.action.trigger`（评分/更新题按钮）。没有它，点击不会推进队列；
- `frontier-daily.timer`：每天 08:00 Asia/Shanghai 调 `trigger.cli scheduled`。队列非空时只合并待推请求；队列清空后由评分回调自动拉起 `run-request`。
- `frontier-sync.timer`：每 10 分钟 `knowledge.cli pull → sync → compare`；没有 `knowledge/base.json` 时跳过镜像。
- `frontier-library.timer`：每天 03:30 对账云盘与 Base、检查配额，并把提醒发成 owner 私聊文本。
- `frontier-retry.timer`：每 2 分钟调一次 `trigger.cli run-request --quiet`，作为 lease 过期后的兜底；没有待推请求、队列未清空、租约仍有效或 job lock 被占时立即退出（不写日志、不告警）。

没有 systemd 时，用 tmux 常驻：

```bash
tmux new -d -s frontier \
  "cd $HOME/frontier && KL_HOME=$HOME/knowledge-loop FRONTIER_OWNER_ID=$OWNER python3 -m trigger.cli listen"
```

手动补推只接受 owner 的私聊关键词：`再推一篇` / `下一篇` / `next` / `more`，可跟知识卡片 id（如 `再推一篇 card_hmbs`）。

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
- 手动补推监听：`frontier-listener` 是否 active
- 评分/更新题监听：`frontier-rating-listener` 是否 active
- 每日定时：`frontier-daily.timer` 是否 active，下一次 08:00
- 验证结果：测试通过数、`validate` 是否 ok
- 下一步：**重启 agent**，然后说「跑一下 frontier 的今日循环」；或在飞书私聊发「再推一篇」

### 8. 卸载（用户要求时）

```bash
systemctl --user disable --now frontier-listener frontier-rating-listener frontier-daily.timer 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/frontier-listener.service" \
      "$HOME/.config/systemd/user/frontier-rating-listener.service" \
      "$HOME/.config/systemd/user/frontier-daily.service" \
      "$HOME/.config/systemd/user/frontier-daily.timer"
systemctl --user daemon-reload
rm "$HOME/.config/opencode/skills/frontier"   # 只删软链
# 数据在 ~/knowledge-loop，默认保留；删除前必须再确认
```

## 故障

| 现象 | 处理 |
|---|---|
| `lark-cli: command not found` | 停止，让用户先安装 Lark CLI |
| `auth status` 里 user 不可用 | 运行 `lark-cli auth login`，等用户完成 |
| `event consume` 报 `failed_precondition` | 飞书开发者后台订阅对应事件（`card.action.trigger` / `im.message.receive_v1`） |
| `frontier-listener` 反复重启 | 看 `journalctl --user -u frontier-listener`；常见原因是 `lark-cli` 不在 PATH 或 owner 未配置 |
| 点了评分但 `ratings.jsonl` 为空 | 确认 `frontier-rating-listener` 是 active；没有它，`card.action.trigger` 不会被消费 |
| skills 目录已有同名文件 | 停止并询问，不要覆盖 |
| `python3 -c "import yaml"` 失败 | 询问后安装 PyYAML |
| `python3 -c "import weasyprint"` 失败 | 询问后安装 WeasyPrint |
| PDF 中文缺字 | 安装 Noto CJK 字体（`fonts-noto-cjk`） |
| `pytest` 失败 | 停止，把失败输出贴给用户，不要继续接入 |
