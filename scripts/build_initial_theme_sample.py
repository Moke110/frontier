#!/usr/bin/env python3
"""Build the draft initial-build sample for the evaluation-credibility theme.

Draft only: writes under drafts/initial-build/, never touches archive/.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "drafts" / "initial-build" / "evaluation-credibility"
AT = "2026-10-21T11:00:00+08:00"
SOURCE = {"kind": "initial-build-draft", "id": "theme:evaluation-credibility"}

SOURCES = [
    {
        "paper_id": "pdf_2025_anders_bench_linbaseline",
        "title": "Deep-learning-based gene perturbation effect prediction does not yet outperform simple linear baselines",
        "doi": "10.1038/s41592-025-02772-6",
        "pdf_path": "~/arc/reference/PDFs/2025_Anders_Bench-LinBaseline.pdf",
    },
    {
        "paper_id": "pdf_2025_szalai_bench_fcm",
        "title": "Benchmarking foundation cell models for post-perturbation RNA-seq prediction",
        "doi": "10.1186/s12864-025-11600-2",
        "pdf_path": "~/arc/reference/PDFs/2025_Szalai_Bench-FCM.pdf",
    },
    {
        "paper_id": "pdf_2025_moccia_simplecontrols",
        "title": "Simple controls exceed best deep learning algorithms and reveal foundation model effectiveness for predicting genetic perturbations",
        "doi": "10.1093/bioinformatics/btaf317",
        "pdf_path": "~/arc/reference/PDFs/2025_Moccia_SimpleControls.pdf",
    },
    {
        "paper_id": "pdf_2025_liu_benchgenpert",
        "title": "Benchmarking algorithms for generalizable single-cell perturbation response prediction",
        "doi": "10.1038/s41592-025-02980-0",
        "pdf_path": "~/arc/reference/PDFs/2025_Liu_BenchGenPert.pdf",
    },
    {
        "paper_id": "pdf_2026_brbic_systema",
        "title": "Systema: a framework for evaluating genetic perturbation response prediction beyond systematic variation",
        "doi": "10.1038/s41587-025-02777-8",
        "pdf_path": "~/arc/reference/PDFs/2026_Brbic_Systema.pdf",
    },
    {
        "paper_id": "pdf_2026_herrmann_scarchon",
        "title": "scArchon: a scalable benchmarking framework for assessing single-cell perturbation models",
        "doi": "10.1186/s13059-026-04104-z",
        "pdf_path": "~/arc/reference/PDFs/2026_Herrmann_scArchon.pdf",
    },
    {
        "paper_id": "pdf_2025_graepel_perturbench",
        "title": "PerturBench: Benchmarking Machine Learning Models for Cellular Perturbation Analysis",
        "pdf_path": "~/arc/reference/PDFs/2025_Graepel_PerturBench.pdf",
    },
    {
        "paper_id": "pdf_2026_tian_syscomppert",
        "title": "A systematic comparison of single-cell perturbation response prediction models",
        "doi": "10.1126/sciadv.aed3414",
        "pdf_path": "~/arc/reference/PDFs/2026_Tian_SysCompPert.pdf",
    },
]

CARDS = [
    {
        "schema_version": 2,
        "id": "card_perturbation_benchmark",
        "label": "扰动预测基准",
        "ontology": [
            "perturbation benchmark",
            "PerturBench",
            "scArchon",
            "Systema",
            "benchmark",
            "评测基准",
        ],
        "annotation": (
            "用统一的数据集、任务切分和指标比较单细胞扰动响应预测模型。"
            "关注 seen/unseen 扰动、单基因/组合扰动、跨细胞类型三类任务。\n"
            "⛔ 不含：单个模型论文的自我报告指标，或没有基线的模型比较。\n"
            "⚠️ 易混：benchmark 数据集 ≠ benchmark 协议；同一数据集换切分就能换排名。"
        ),
    },
    {
        "schema_version": 2,
        "id": "card_ood_generalization",
        "label": "分布外泛化",
        "ontology": [
            "out-of-distribution",
            "OOD",
            "unseen perturbation",
            "unseen cell type",
            "leave-one-out",
            "泛化",
        ],
        "annotation": (
            "模型在训练时未见过的扰动、细胞类型或组合上的预测能力。"
            "评测必须明确是哪一种 unseen：unseen perturbation、unseen cell type，还是两者都有。\n"
            "⛔ 不含：随机拆分的同分布测试集。\n"
            "⚠️ 易混：zero-shot 与 fine-tune 后的跨上下文迁移不是同一件事。"
        ),
    },
    {
        "schema_version": 2,
        "id": "card_simple_baseline",
        "label": "简单基线",
        "ontology": [
            "train mean",
            "perturbed mean",
            "no-change baseline",
            "additive baseline",
            "linear baseline",
            "简单基线",
        ],
        "annotation": (
            "用训练集均值、no-change、加性或线性模型作为对照。"
            "它不是“弱方法”，而是判断复杂模型是否真的带来增益的必要门槛。\n"
            "⛔ 不含：只报告复杂模型之间互比、没有均值/线性对照的评测。\n"
            "⚠️ 易混：不同论文的 mean baseline 计算方式（per-perturbation mean vs global mean）不同。"
        ),
    },
    {
        "schema_version": 2,
        "id": "card_foundation_model_eval",
        "label": "基础模型评测",
        "ontology": [
            "scGPT",
            "scFoundation",
            "Geneformer",
            "State",
            "foundation model evaluation",
            "基础模型",
        ],
        "annotation": (
            "单细胞基础模型在扰动响应任务上的评测：预训练表征是否带来可迁移增益，"
            "而不是只看 fine-tune 后的拟合分数。\n"
            "⛔ 不含：细胞类型注释、聚类等非扰动任务的成绩。\n"
            "⚠️ 易混：模型在 cell annotation 上强，不等于在 perturbation prediction 上强。"
        ),
    },
    {
        "schema_version": 2,
        "id": "card_systematic_variation",
        "label": "系统性变异",
        "ontology": [
            "systematic variation",
            "batch effect",
            "covariate shift",
            "confounding",
            "评测泄漏",
        ],
        "annotation": (
            "扰动数据中所有扰动共享的表达偏移（可能来自生物效应、实验设计或混杂因素）。"
            "以 control 为参考的 PearsonΔ 类指标会随系统性变异升高，造成性能虚高。\n"
            "⛔ 不含：真实的扰动特异性效应。\n"
            "⚠️ 易混：系统性变异不等于普通 batch effect；它可以在同一批次内存在。"
        ),
    },
]

EVIDENCE = {
    "anders_p4": {
        "paper_id": "pdf_2025_anders_bench_linbaseline",
        "page": 4,
        "quote": "As our deliberately simple baselines are incapable of representing realistic biological complexity, yet were not outperformed by the foundation models, we conclude that the latter’s goal of providing a generalizable representation of cellular states and predicting the outcome of not-yet-performed experiments is still elusive.",
    },
    "anders_p3": {
        "paper_id": "pdf_2025_anders_bench_linbaseline",
        "page": 3,
        "quote": "The ‘no change’ baseline cannot, by definition, find synergistic interactions, but also the deep learning models rarely predicted synergistic interactions, and it was even rarer that those predictions were correct (Fig. 1f).",
    },
    "szalai_p2": {
        "paper_id": "pdf_2025_szalai_bench_fcm",
        "page": 2,
        "quote": "Surprisingly, we found that foundation models generally underperformed compared to a simple baseline model that uses the mean of the training samples.",
    },
    "moccia_p1": {
        "paper_id": "pdf_2025_moccia_simplecontrols",
        "page": 1,
        "quote": "Results: Here, we present a simple baseline method that outperforms both state of the art (SOTA) in DL and other proposed simpler neural architectures, setting a necessary benchmark to evaluate in the field of post-perturbation prediction.",
    },
    "liu_p1": {
        "paper_id": "pdf_2025_liu_benchgenpert",
        "page": 1,
        "quote": "Here, we present a comprehensive benchmark of 27 methods for single-cell perturbation response prediction, evaluated across 29 datasets using 6 complementary performance metrics.",
    },
    "tian_p1": {
        "paper_id": "pdf_2026_tian_syscomppert",
        "page": 1,
        "quote": "Recent studies have provided initial benchmarks comparing foundation models, other deep learning architectures, and simple baselines for perturbation effect prediction and reported that complex models do not consistently outperform the simpler alternatives (22–26).",
    },
    "tian_p2": {
        "paper_id": "pdf_2026_tian_syscomppert",
        "page": 2,
        "quote": "models were expected to predict how previously unseen combinations of gene perturbations would influence gene expression in the same cell type or cell line.",
    },
    "herrmann_p2": {
        "paper_id": "pdf_2026_herrmann_scarchon",
        "page": 2,
        "quote": "Moreover, inconsistent use of performance metrics complicates overarching evaluations.",
    },
    "graepel_p1": {
        "paper_id": "pdf_2025_graepel_perturbench",
        "page": 1,
        "quote": "Through extensive evaluation of both published and baseline models across diverse datasets, we highlight the limitations of widely used models, such as mode collapse.",
    },
    "brbic_p5": {
        "paper_id": "pdf_2026_brbic_systema",
        "page": 5,
        "quote": "Standard reference-based metrics are susceptible to systematic variation",
    },
    "brbic_p6": {
        "paper_id": "pdf_2026_brbic_systema",
        "page": 6,
        "quote": "Applying Systema resulted in substantially lower evaluation scores",
    },
}


def _evidence(keys: list[str]) -> list[dict]:
    return [EVIDENCE[key] for key in keys]


def _prop(
    prop_id: str,
    title: str,
    content: str,
    related: list[str],
    evidence_keys: list[str],
    rationale: str,
) -> dict:
    return {
        "schema_version": 2,
        "id": prop_id,
        "title": title,
        "content": content,
        "related_knowledge": related,
        "history": [
            {
                "at": AT,
                "action": "created",
                "source": SOURCE,
                "before": None,
                "after": {
                    "title": title,
                    "content": content,
                    "related_knowledge": related,
                },
                "rationale": rationale,
                "evidence": _evidence(evidence_keys),
            }
        ],
        "created_at": AT,
        "updated_at": AT,
    }


PROPOSITIONS = [
    _prop(
        "prop_dl_not_better_than_simple_baselines",
        "深度扰动预测尚未稳定超过简单基线",
        "在多种 Perturb-seq 数据集与评测协议下，深度生成模型和单细胞基础模型的扰动响应预测并不稳定优于 train mean、加性/线性等简单基线；部分评测中简单基线反而更好。",
        ["card_perturbation_benchmark", "card_simple_baseline", "card_foundation_model_eval"],
        ["anders_p4", "szalai_p2", "moccia_p1", "tian_p1"],
        "多篇独立基准指向同一结论；作为初始命题，后续可用新论文继续补证据或限定条件。",
    ),
    _prop(
        "prop_benchmark_protocol_changes_ranking",
        "评测协议与指标会改变模型排名",
        "数据集切分（seen/unseen、跨细胞类型）、指标（RMSE 与 PearsonΔ/rank）和预处理差异会显著改变模型排名；跨论文只比单一指标不足以下结论。",
        ["card_perturbation_benchmark", "card_ood_generalization", "card_systematic_variation"],
        ["liu_p1", "tian_p1", "herrmann_p2", "graepel_p1"],
        "多个基准各自覆盖不同任务/指标，且明确批评指标不一致；需要统一协议才能比较。",
    ),
    _prop(
        "prop_foundation_models_underperform_mean",
        "基础模型在扰动预测上常不如训练集均值",
        "scGPT、scFoundation 等基础模型在多个 Perturb-seq 数据集上 fine-tune 后，仍经常低于 train mean；预训练表征的优势没有稳定转化为扰动预测增益。",
        ["card_foundation_model_eval", "card_simple_baseline", "card_perturbation_benchmark"],
        ["szalai_p2", "anders_p4"],
        "两篇独立评测直接比较基础模型与均值基线，结论方向一致。",
    ),
    _prop(
        "prop_systematic_variation_inflates_scores",
        "系统性变异会抬高扰动预测分数",
        "常用单细胞扰动数据存在不同程度的系统性变异；以 control 为参考的 PearsonΔ 类指标会随系统性变异升高，导致模型性能虚高。改用去参考/扰动特异性评测后分数显著下降。",
        ["card_systematic_variation", "card_perturbation_benchmark", "card_ood_generalization"],
        ["brbic_p5", "brbic_p6"],
        "Systema 同时给出机制解释与重新评测结果；是“可信度”主题的核心命题。",
    ),
    _prop(
        "prop_combinatorial_prediction_weak",
        "组合扰动（尤其协同效应）预测仍很弱",
        "现有模型在组合扰动上多预测 buffering/加性效应，很少正确预测协同效应；no-change/加性基线往往不差，组合扰动是比单基因更难的泛化任务。",
        ["card_simple_baseline", "card_ood_generalization", "card_perturbation_benchmark"],
        ["anders_p3", "tian_p2"],
        "一篇直接报告协同效应预测失败，另一篇把组合扰动列为独立任务；先立为待补强命题。",
    ),
]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "cards.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in CARDS) + "\n",
        encoding="utf-8",
    )
    (OUT / "propositions.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in PROPOSITIONS) + "\n",
        encoding="utf-8",
    )
    (OUT / "sources.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in SOURCES) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT.relative_to(ROOT)}: {len(CARDS)} cards, {len(PROPOSITIONS)} propositions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
