# 宿主接入与本地定时验收（#37 / #38）

- 日期：2026-10-27
- 结论：**未通过（阻塞）**。安装自检、知识库接入、反馈闭环、租约与有界运行的**代码与离线链路**已验证；两款宿主的**真实定时触发、无人值守权限、飞书登录**在本机无法完成，未取得实测证据，因此不标记通过。

## 本机实测环境

| 项 | 实测值 |
|---|---|
| 系统 | Windows 10.0.19045（`Windows-10-10.0.19045-SP0`），AMD64，原生非 WSL |
| 解释器 | Python 3.13.14（`E:\Desktop\frontier\.venv\Scripts\python.exe`，由 3.13.12 建 venv） |
| 仓库 | `E:\Desktop\frontier`（含空格/盘符路径已覆盖到测试） |
| 数据根 | 验收用临时目录 `/tmp/kl-evidence`，未写入 `~/knowledge-loop` |
| 依赖 | PyYAML 可用；`pymupdf` 已装 |
| 测试 | `python -m pytest -q` → **184 passed, 3 skipped** |

## 安装自检的真实输出

```bash
python -m hostrun.cli --home /tmp/kl-evidence install check \
  --repo . --host-product WorkBuddy --host-local-execution --permissions "shell,file_write"
```

```json
{
  "ok": false,
  "partial": false,
  "steps": {
    "host": "untested",
    "dependencies": "ok",
    "lark_cli": "blocked",
    "identity": "blocked",
    "knowledge_base": "pending",
    "schedules": "pending",
    "first_run": "pending"
  },
  "working": [{ "step": "dependencies", "note": "解释器与仓库可用" }],
  "blocked": [
    { "step": "lark_cli", "note": "飞书 CLI 未找到：把它装到私有目录并在 install/config.json 的 paths.lark_cli 指向它" },
    { "step": "identity", "note": "缺少 lark-cli 路径" }
  ],
  "untested": [
    { "step": "host", "note": "未确认宿主能力：version、schedules" }
  ]
}
```

这份输出本身就是验收结论：**只有 `dependencies` 是 working**。`host` 因为没声明版本与内置调度而留在 `untested`，`lark_cli` / `identity` 因本机没有可用的 `lark-cli` 而 `blocked`——没有把任何一项写成通过。

## 逐条对照

### #38 WorkBuddy

| 要求 | 结果 | 证据 / 原因 |
|---|---|---|
| 技能发现、项目目录接入、本地 CLI 执行 | **通过（部分）** | 本会话即在 `E:\Desktop\frontier` 内执行 `python -m hostrun.cli`、`pytest`、`git`、`gh`；技能以 `C:\Users\Chang\.workbuddy\skills\implement\SKILL.md` 形式被发现 |
| 新库 / 已有库两条安装路径，可重复执行 | **通过（离线）** | `kb create` / `kb attach` / `create-tables` / `verify` 有测试覆盖：重复执行不重复建表、不覆盖已有数据、非空库在 `--expect-empty` 下判失败（`tests/test_hostrun_kb.py`） |
| 时区 + 启用确认后配置三个任务 | **未实测** | 只产出 `schedules plan`（可读计划）与 `confirm`（需 `--yes` + 宿主真正创建）；本会话未在宿主自动化里创建并触发任务 |
| 权限实际作用域与无人值守行为 | **未实测** | 能确认的是「本会话内可执行本地命令」；后台无人值守时的权限边界没有证据 |
| 实测一次本地定时执行 + 持久反馈续接 | **未实测** | 依赖 `lark-cli` 登录与宿主调度，本机缺 `lark-cli` |
| 在线要求、暂停与切换说明 | **通过（文档）** | [README 使用与恢复说明](../../README.md)；`executor handover --force`、`feedback rebuild` 有测试覆盖 |

### #37 ChatGPT

| 要求 | 结果 | 证据 / 原因 |
|---|---|---|
| 版本、命令、技能、工作目录、网络、内置调度核实 | **未实测** | 本机没有可用的 ChatGPT 桌面端本地会话，无法核实；**不把网页云端任务当本地模式** |
| prompt 引导建库/连库、授权、中断续接 | **通过（可离线验证的部分）** | 续接靠 `install/state.json`；`record` 对 `ok` 幂等、复检不会把已验证项降级（`test_ok_is_terminal_and_rechecks_do_not_erase_it`） |
| 三个任务写到宿主调度 | **未实测** | 同上 |
| 权限范围 | **未实测** | 同上 |
| 真实定时 + 离线反馈 + 稳定续接 | **未实测** | 同上 |
| 开机/在线条件、暂停切换 | **通过（文档）** | [README 使用与恢复说明](../../README.md) |

## 为什么没有硬凑通过

- 本机 `lark-cli` 未安装：`command -v` 与 `resolve_executable` 均找不到，因此 `identity` 步骤只能 `blocked`。没有真实 Base 就无法完成建库、`feedback sync`、`audit`。
- 宿主调度的真实触发需要宿主侧创建任务并等它到点执行；在本会话里无法自证，写成「通过」就是伪造证据。
- 云端（网页版）任务**不能**代替本机依赖验收，这一点按 ticket 要求执行。

## 解除阻塞需要什么

1. 把 `lark-cli` 装到私有目录，并在 `install/config.json` 写 `paths.lark_cli`；由用户完成 user/bot 登录授权。
2. 在 WorkBuddy 自动化里创建三个任务，分别调用 `run --intent daily|feedback|maintenance`，等待至少一次真实到点触发，保存运行日志与 `hostrun/runs.jsonl`。
3. 取得触发证据后，重跑 `install check` 并附带 `--host-version`、`--host-schedules`，把 `host` 从 `untested` 变为 `ok`。
4. ChatGPT 桌面端同理；在拿到真实版本与本机执行证据前，保持「未实测」。
