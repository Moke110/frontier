# ADR 0002：命题 v3（evidence / review）与 Bitable 权威存储

- 日期：2026-10-22
- 状态：已接受
- 相关决策：每篇推送 2 个实体名额；HTML 推送；更新 skill（`skills/frontier-loop`）

## 背景

v2 的命题把三样东西塞进两个字段：

1. `content` 是一句话结论（线上 6 条命题实测 19–96 字），不足以承载跨论文综述；
2. `history` 同时是变更日志和证据仓库，无法表达“多条方向一致的报道支持同一结论”或“同一命题下存在互相矛盾的证据”；
3. 证据只存在 `history[].evidence` 里，无法单独浏览、归并或计数。

同时，知识层只在本地 JSON 里，手机上无法阅读或润色；PDF 推送在不同终端上字号固定，长文阅读体验差。

## 决策

1. **命题 schema v3**：`id / title / review / related_knowledge / evidence / changelog / evidence_updates_since_review`。
   - `review` ≤2000 字，固定四节（结论 / 支持证据 / 反证与边界 / 待验证），只基于 evidence。
   - `evidence[]` 每条含 `stance`、`conclusion`（≤200 字）、`papers[]`（paper_id / push_id / page / quote / added_at）。
   - `changelog[]` 只记 title / review / related_knowledge 的变更。
   - 新建命题必须带 ≥2 条 evidence。
2. **每采纳 10 条证据更新重写 review**；综述题独立于每篇推送的 2 个实体名额，但闸住下一次检索推送。
3. **Bitable 是知识层唯一真相**（卡片 / 命题 / 证据 / 报道 / 变更日志五表）；原文、推送、队列、评分仍是本地文件。
4. **写入走本地 WAL + 幂等重放**：Bitable 无跨表事务，先写 group journal，再逐条写，按 `group_id` 断点续跑。
5. **读实时走 Bitable**；测试与 `--offline` 用 `FixtureStore`，不直连真实租户。
6. **写前仍跑本地校验器**：Bitable 不能强制 id 唯一、字数上限与引文可定位。
7. **用户可直接编辑文本列**（title / review / conclusion / annotation）；结构列只读是约定；10 分钟扫描补 changelog。
8. **迁移**：旧 `history[].evidence` 每个条目迁成一条 evidence（conclusion 取 rationale 截断，标 `migrated_from_v2`）；全量导入后双读比对 7 天再下线文件写入。
9. **推送改为自包含 HTML**（内联 CSS/图片），确认卡附 Base 记录链接；PDF 退出正式流程。

## 被否决的替代方案

- **保留文件权威、Bitable 只做视图**：无法满足手机端直接编辑与统一浏览；但保留了最完整的可回滚性。作为迁移期的过渡形态（双读比对）保留。
- **Bitable 双向同步**：冲突解决与幂等成本最高，暂不做。
- **证据压成命题上的一段 JSON 文本**：表更少，但失去按立场分组、单独归并和计数。
- **把 review 也做成飞书云文档**：云文档不能按视口自适应字号；HTML 附件才满足阅读需求。
- **在 Bitable 用公式/插件做校验**：表达不了“引文必须能在原文锚点定位”这类跨源约束。

## 后果

- `archive.store` 要拆出 `KnowledgeStore` 接口 + `BitableStore` / `FixtureStore`；
- `writer check`、`question_queue`、`publisher` 的提议契约与卡片格式随之升级；
- 迁移与双读比对需要一次性脚本与 7 天观察期；
- 离线测试必须覆盖 fake store，不能再依赖真实 Base；
- HTML 渲染替换 PDF 渲染，旧 PDF 仅保留可读。
