# 08 editor / writer 改为 agent 任务

Type: prototype ｜ Status: resolved ｜ Blocked by: —

## Question

editor 与 writer 不再内置模型调用，而是把需要判断的部分打包成任务文件，由宿主 agent 读取、推理、写回；脚本负责上下文组装与校验：

- `editor task` 输出候选 + checkpoint 的 ontology / annotation / 知识卡 / 命题 / 偏好 / 限制；agent 写 `selection.json`；`editor check` 校验（候选白名单、去重、上限、score/rationale）。
- `writer task` 输出每篇的 archive 上下文 + 四段写作要求 + proposal 协议；agent 写 `outbox/pushes/<push_id>.json`；`writer check` 校验（文件名=push_id、四段非空、引用上下文、proposal 目标存在、status=draft）。
- 保留 `editor rank` / `writer write` 作为确定性 fallback，供离线 demo 与测试。

## Answer

已实现 `editor/tasks.py`、`writer/tasks.py`，CLI 增加 `editor task|check`、`writer task|check`。契约写入 `contracts/agent-tasks.md`，明确 agent 只读知识库、写知识库只能走 archive 的 proposal/审批链。测试 `tests/test_agent_tasks.py` 覆盖任务构建、合法/非法 selection、写作 roundtrip、未知 proposal 目标。
