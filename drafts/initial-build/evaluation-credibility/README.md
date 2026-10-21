# 初始构建样张：扰动预测的评测、基线与可信度

- 票：[初始主题清单与单主题样张 #12](https://github.com/Moke110/frontier/issues/12)、[初始构建：首批主题写入知识库 #15](https://github.com/Moke110/frontier/issues/15)
- 状态：**首批已入库**（2026-10-21，`initial_build` CLI）：5 卡 / 4 命题写入 `~/knowledge-loop/archive`
- 门槛 hold：`prop_systematic_variation_inflates_scores` 的 2 条证据均来自 Systema（page 5/6），不满足「≥2 篇独立论文」，首批暂不入库，留作候选
- 用户确认：**2026-10-21，用户确认样张与质量门槛可用，按此进入首批构建（#15）**
- 产物：`cards.jsonl`（5 张卡）、`propositions.jsonl`（5 条命题）、`sources.jsonl`（8 篇来源）
- 生成：`python scripts/build_initial_theme_sample.py`
- 来源主题：`evaluation-credibility`（11 篇论文，见 `fixtures/theme-inventory.jsonl`）

## 1. 卡片

| id | label | 作用 |
|---|---|---|
| `card_perturbation_benchmark` | 扰动预测基准 | 统一任务/切分/指标的基准 |
| `card_ood_generalization` | 分布外泛化 | unseen perturbation / cell type |
| `card_simple_baseline` | 简单基线 | mean / no-change / additive / linear |
| `card_foundation_model_eval` | 基础模型评测 | scGPT / scFoundation / State 等 |
| `card_systematic_variation` | 系统性变异 | 共享偏移与指标虚高 |

卡片粒度：一个可独立检索/排除的**概念**一张卡；“简单基线”单独成卡，因为它既是方法也是评测门槛，且多篇论文围绕它立论。

## 2. 命题

| id | 命题 | 关联卡片 | 证据篇数 |
|---|---|---|---:|
| `prop_dl_not_better_than_simple_baselines` | 深度扰动预测尚未稳定超过简单基线 | benchmark / baseline / foundation | 4 |
| `prop_benchmark_protocol_changes_ranking` | 评测协议与指标会改变模型排名 | benchmark / OOD / systematic | 4 |
| `prop_foundation_models_underperform_mean` | 基础模型常不如训练集均值 | foundation / baseline / benchmark | 2 |
| `prop_systematic_variation_inflates_scores` | 系统性变异会抬高预测分数 | systematic / benchmark / OOD | 2 |
| `prop_combinatorial_prediction_weak` | 组合扰动（尤其协同）预测仍弱 | baseline / OOD / benchmark | 2 |

每条命题的 `history[0].evidence` 都包含 `paper_id / page / quote`，并额外记录 `pdf_path` 便于回溯。8 条引文已用 PyMuPDF 按页逐条核对，均为页面文本的精确子串。

## 3. “可用”质量门槛

一个主题进入初始构建（写 archive）前必须满足：

**卡片**
- 四个字段齐全；`id` 为 `card_<slug>`；
- `ontology` ≥3 个词，包含至少一个中文/英文同义词；
- `annotation` 含定义 + ⛔ 排除项 + ⚠️ 易混项；
- 卡片之间不重叠到无法区分（同一概念只建一张）。

**命题**
- 跨论文综合，不是单篇摘要；`content` 能独立成立；
- `related_knowledge` ≥2 张**本主题或已确认主题**的卡；
- 至少 2 篇独立论文作证据（弱主题允许 1 篇但标 `weak`，不进入首批）；
- 每条证据有页码 + 可核对引文；引文必须是原文精确子串；
- `history` 有 `created` 条目与 rationale。

**主题**
- `paper_count ≥4` 且 `evidence_strength ∈ {medium, strong}` 才进入首批；
- 至少 2 张卡 + 3 条命题；否则留作候选，不硬凑；
- 同一主题内命题不重复（合并同义命题）。

当前样张：**5 卡 / 5 命题 / 8 篇来源**，满足门槛；`aip-hmbs`（1 篇）标 `weak`，不进入首批。

## 4. 待确认

1. 卡片粒度：5 张是否过细？是否把“简单基线”并入“评测基准”？
2. 命题合并：`prop_dl_not_better_than_simple_baselines` 与 `prop_foundation_models_underperform_mean` 是否应合并成一条“复杂模型无稳定增益”？
3. 证据强度：是否要求每条命题至少 3 篇，还是 2 篇即可进入首批？
4. 主题清单：`evaluation-credibility` 作为第一个完整样张是否合适，还是先做 `perturbation-prediction`（45 篇）？
