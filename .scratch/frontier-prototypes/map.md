# frontier 原型（Frontier Prototypes）

Label: `wayfinder:map` ｜ Slug: `frontier-prototypes` ｜ Started: 2026-10-20

> ⚠️ **本 effort 是执行型，不是决策型**（用户 2026-10-20 明确：「不做太深入的设计，先把各部分原型各自独立解耦地制作出来」）。结票 = 产出可运行原型，不是产出决策。决策图仍是 `../knowledge-loop/map.md`。
> 🔁 接续方式：读本 map 的 Destination / Notes → 取最小票号的 open + unblocked 票 → `Status: claimed` → 动手 → 写 `## Answer` + 在 Decisions 挂一行。
> 📄 实现说明与契约见仓库根 `README.md` 与 `contracts/README.md`。

## Destination

六个可独立运行、互不 import 的原型模块 —— **archive / frontier / retriever / editor / writer / publisher** —— 只通过文件契约通信，外加一条离线端到端 demo 把闭环跑通（checkpoint → 检索 → 排序 → 写作 → 飞书推送 → 评分 → 知识图/命题更新提议 → 审批）。

## Notes

- **执行优先**：原型用 Python 3.13 + stdlib + PyYAML；不引数据库、不引 Web 框架；每个模块一个 CLI，`python -m <module>.cli`。
- **解耦规则**：模块之间**零 import**；共享的只有根目录 `common.py`（纯 IO 工具，无领域逻辑）和 `contracts/` 里的文件格式说明。
- **数据根**：环境变量 `KL_HOME`，默认 `./data`；fixtures 在 `fixtures/`，demo 全部离线。
- **外部依赖只有两个**：`lark-cli`（publisher，可 dry-run 绕过）、`urllib` + `xml.etree`（retriever 的 live 模式，默认关闭）。
- 领域背景读 `../knowledge-loop/spec.md`：checkpoint / 知识图 / 命题 / 评分反哺的语义以它为准；本图只做原型，不改语义。
- 用户偏好：中文；产物要能单独跑、单独看；不追求生产级健壮性。

## Decisions so far

<!-- 索引：每行一条已结票 -->

- [01 archive：四层存储](issues/01-archive.md) — `raw/` + `pushes/` + `kg/` + `propositions/`，索引可重建；`context` 聚合供 writer 用；`apply-proposal(s)` 支持四类更新且幂等。
- [02 frontier：检索式产出](issues/02-frontier.md) — checkpoint（含 `kg_node_id`）→ arXiv / Europe PMC 字段限定查询；`record` 用 EMA 更新 `weight`（1–10）。
- [03 retriever：取原文](issues/03-retriever.md) — fixture / live 双适配器，统一 candidate；去重 + 窗口过滤；无候选退出码 2、取数失败 3。
- [04 editor：排序与调权](issues/04-editor.md) — `fit` 学 checkpoint / 来源偏好（Beta 平滑），`rank` 四项加权（0.40/0.15/0.30/0.15）并可解释。
- [05 writer：写作 + 更新提议](issues/05-writer.md) — 四段式推送引用 archive 知识卡与命题；三种 proposal 全为 `draft`，不直接写知识库。
- [06 publisher：飞书闭环](issues/06-publisher.md) — 三按钮评分卡（评分 + 评语一次提交）、原地确认、非「不相关」才发审批卡；决策交 archive 应用。
- [07 端到端离线 demo](issues/07-demo.md) — `scripts/demo.py` 一条命令跑通全链路，验证证据 / 别名 / 命题增长与排序变化；`pytest` 全部通过。
- [08 editor / writer 改为 agent 任务](issues/08-agent-tasks.md) — `task → agent → check` 两段式；脚本只组装上下文与校验，保留 `rank` / `write` 作为离线 fallback；契约在 `contracts/agent-tasks.md`。
- [09 安装器与 agent 接入](issues/09-install.md) — 初版 `install.sh`（检查 agent + Lark CLI + Python，再软链到 skills 目录）。**已被 11 取代**：安装改为 agent 任务说明。
- [10 远程仓库与 GitHub issue tracker](issues/10-remote-tracker.md) — `origin` 指向 `Moke110/frontier`；issue tracker 改为 GitHub Issues + sub-issues / native blocked-by；`.scratch` 转为只读历史。
- [11 安装改为 agent 任务说明](issues/11-install-prompt.md) — 删除安装脚本，改为 `INSTALL.md`：agent 检查 `lark-cli` 登录 → GitHub clone → 软链 skills → 初始化 → 验证。

## Not yet specified

- 真实全文抓取（当前只存 abstract）与 PDF 解析 —— 原型验证后再决定。
- agent 写作失败的自动重试/降级策略（当前由 agent 自行重试 `check`）—— 先用一段时间再定。
- 多用户/多租户、并发写入、迁移与备份 —— 不属于原型目的。

## Out of scope

- 生产部署、调度（cron/Hermes）、权限模型、监控告警。
- 重写 `knowledge-loop` 的 spec 或决策票。
