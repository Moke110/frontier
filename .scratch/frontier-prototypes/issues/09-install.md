# 09 安装器与 agent 接入

Type: prototype ｜ Status: resolved ｜ Blocked by: —

## Question

提供与 mattpocock/skills 同类的安装体验：用户已装好 agent 与 Lark CLI，运行安装器后选择 agent 类型；安装器检查两者是否存在，全部通过才把项目接入所选 agent，任一缺失则中止并给出修复提示。

要求：幂等、`--dry-run`、`--uninstall`、支持 opencode / Claude Code / Codex / Cursor / 其他（`~/.agents/skills`）；安装后 agent 能从技能列表发现 `frontier` 并按 `SKILL.md` 跑完整循环。

## Answer

已实现 `install.py` + `install.sh`：

- 顺序检查：agent 可执行文件 → `lark-cli` → Python 3.11+/PyYAML/仓库含 `SKILL.md`；任一失败即 `InstallError`，不写任何文件。
- 通过后把仓库软链到 `~/.config/opencode/skills/frontier`、`~/.claude/skills/frontier`、`~/.codex/skills/frontier`、`~/.cursor/skills/frontier` 或 `~/.agents/skills/frontier`（`--copy` 可改为复制）。
- 写 `~/.config/frontier/install.json`（agent / repo / target / lark / auth / 时间）；`--check` 输出环境矩阵；`--uninstall` 只删本项目链接与状态。
- 已用真实环境验证 `--check`：opencode、Claude Code、Lark CLI、auth 均 ready；codex/cursor 不在 PATH 时正确标 ✗。
- 测试 `tests/test_installer.py` 覆盖安装、幂等、dry-run、缺失 agent、缺失 lark、generic、卸载、拒绝覆盖他人目录。

> **2026-10-20 后续（见票 11）**：用户要求安装改为 agent 任务说明，`install.py` / `install.sh` 与对应测试已删除，由 `INSTALL.md` 取代。
