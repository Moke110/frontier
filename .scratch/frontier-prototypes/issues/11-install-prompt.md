# 11 安装改为 agent 任务说明

Type: task ｜ Status: resolved ｜ Blocked by: —

## Question

安装方式改为「一段任务说明 + 用户自己的 agent 执行」，不再提供独立安装脚本：

- agent 自动检查 `lark-cli` 是否安装并**登录**；
- 通过 GitHub 获取代码与 `SKILL.md`；
- 把仓库接入当前 agent 的 skills 目录；
- 失败即停，不覆盖用户数据。

## Answer

- 新增 `INSTALL.md`：开头是一段可直接发给 agent 的任务说明，正文是 agent 的执行步骤（Lark 安装/登录检查、Python/PyYAML、`git clone`、agent→skills 目录映射、软链、fixtures 初始化、pytest + `frontier validate` 验证、汇报与卸载）。
- 删除 `install.py`、`install.sh` 及对应测试；README / SKILL.md / AGENTS.md 全部改为指向 `INSTALL.md`。
- 安装仍然幂等：skills 目录已有本站链接则跳过；已有其他内容则停止并询问。
