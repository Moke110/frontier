# 03 前沿画像的表示

Type: grilling ｜ Status: resolved ｜ Blocked by: —
Claimed by: Hermes (session 2026-10-16)

## Question

「前沿：我对什么感兴趣」这块**用什么形式表示**，才能同时做到：可被 agent 消费（驱动检索与排序）· 可被我手改（引导方向）· 能被评分反馈更新？

## 侦察事实（提问前先查的，供后人参考）

用户**已在维护前沿文档**，但**不纳入本系统**（用户选择新造独立文件）：
- `~/arc/CONTEXT.md` —— roadmap 里直接用了 "current frontier"；Stage 1 完成 / Stage 2 v1、v2 进行中
- `~/_research/HMBS-MIRI/hypothesis_and_todos.md` —— 假说陈述（4 条）+ 逐条评估 + 待做实验清单 + 引用分级（★/☆/⚠）

反面证据（Hermes 曾据此建议「指向前沿文档」，被用户否决）：旧系统的 `fields.tsv` 主题词库**直到最后只有一行 `demo_ai4bio`** —— 手写声明有退化前科。

## Answer

**决策：前沿 = 一份独立 YAML「词汇表」，由若干 checkpoint 组成；每个 checkpoint 是一个概念（术语 + 同义词 + 判据式 annotation），概念之间用 `related` 边连接来表达命题。状态另存一份机器写的文件。**

### 七个子决定（全部由用户拍板）

| # | 问题 | 决定 |
|---|---|---|
| ① | 表示形态 | **新造一份独立的前沿文件**；既有项目文档**不参与** |
| ② | 格式 | **YAML**（不是 markdown） |
| ③ | 数据模型 | frontier = **checkpoint 列表**；checkpoint = **1× ontology（一个术语及其同义词）+ ontology annotation** |
| ④ | 概念 vs 命题 | **概念级**。命题与假说**不进 ontology** —— 理由（原话）：*「我不希望我的假说影响到检索的客观性」* |
| ⑤ | annotation 构造 | **判据式**：定义 + ⛔ **明确不含什么** + ⚠️ **易混淆项** |
| ⑥ | 状态放哪 | **拆两份**：客观词汇表（人写、低频）+ 状态文件（机器写、高频：命中率 / 上次查过 / 启用停用 / 权重） |
| ⑦ | 写权 | **只有用户写词汇表**；agent 只能**提议**（建议新增/停用，附理由与证据），用户点头才落盘 |

### 检索语义（用户给出）

- **召回**：只搜 ontology，**同义词之间 OR** —— 机械、可复现、不含主观
- **精度**：**annotation 用于检查检索结果、避免歧义错位**（LLM 判断）—— annotation 不是给人读的介绍，是**判定标准**
- **命题检索**：`related` 边把同属一个命题的 checkpoint 连成**连通子图**；检索该命题 = **组间 AND**

→ 这个**两段式设计**（机械召回 + annotation 判精）**消解了「词与词如何组合」的问题**：不再需要独立的 cross 规则表，命题就是图上的一条路径；精度由 annotation 承担，不由查询表达式承担。命题因此**不占独立记录**，只是图上的连通性。

### 已定 schema（草案，spec 阶段细化）

```yaml
# frontier.yaml —— 客观词汇表（你手写、低频编辑）
schema_version: 1
checkpoints:
  - id: hmbs
    ontology: [HMBS, PBGD, hydroxymethylbilane synthase, 羟甲基胆素合酶]
    annotation: |
      血红素合成第三步的胞质酶（EC 4.3.1.8）。缺失 → 急性间歇性卟啉症(AIP)。
      ⛔ 不含：卟啉症的一般性综述（除非涉及 HMBS 分子本身）；ALAD / UROS 的论文
      ⚠️ 易混：PBG 单独出现时是底物、不是酶（PBGD 才是酶）
    related: [mito-import, aip-liver]
```

```yaml
# state/checkpoints.yaml —— 状态（机器写、高频；永不回写词汇表）
schema_version: 1
hmbs:
  weight: 9
  enabled: true
  last_checked: 2026-10-16
  hit_rate: { checked: 12, pushed: 4, scored_positive: 3 }
  proposals: []        # agent 的提议落在这里，等你确认（决定 ⑦）
```

### 设计约束（必须写进 spec）

1. **维护不变式**：*annotation 里提到的概念名，必须能在某个 checkpoint 的 ontology 里找到* —— 否则那部分是你检索不到的东西（annotation 说了、检索却漏了）。
2. **假说隔离**：命题只体现在 `related` 的**连边方式**上，**不进入 ontology** —— 这是「召回客观性」的保证，也是防止**确认偏误**的结构性措施。
3. **两份真相的边界**：词汇表（低频、人写）与状态（高频、机器写）严格分文件；**机器永不改词汇表**，只写状态与提议。
4. **状态字段至少包含**：`hit_rate`（按 checkpoint）、`last_checked`、`enabled`、`weight`（后两者供票 08/09 消费）。

### 连带后果

1. **票 04 被本票吃掉大半** → 已缩窄并改名「**04 信息源边界与覆盖策略**」：原问题里的「主题域来源」与「每域一问」由本票回答；剩下的**信息源边界**（是否纳入非论文源）与**覆盖/轮换策略**才是 04 的真问题。04 已解除阻塞。
2. **票 05（知识库载体与粒度）解除阻塞** —— 且必须与本票粒度对齐：知识库是按 **checkpoint** 组织，还是按域/项目。
3. **「评分反哺」的落点由本票给出**：**状态文件**（`hit_rate` / `weight` / `enabled`）。政策层面（权重怎么变、怎么参与排序）仍待票 08 —— 那片雾现在只差 08。
4. **新增待观察点（进 map 雾）**：**提议机制的具体形态** —— 提议写在哪（状态文件 vs 推送末尾）、多久汇总一次、怎么一键确认。
