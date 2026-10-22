from pathlib import Path

from archive.store import Archive
from writer import review as review_task


def _seed(kl_home: Path) -> str:
    store = Archive(kl_home)
    prop = store.get_prop("prop_hmbs_aip")
    prop["review"] = "## 结论\n旧结论。\n## 支持证据\n一条。\n## 反证与边界\n无。\n## 待验证\n无。"
    prop["evidence"] = [
        {
            "id": "ev_hmbs_aip_01",
            "stance": "supports",
            "conclusion": "HMBS 缺失升高 ALA。",
            "papers": [
                {
                    "paper_id": "p1",
                    "page": 3,
                    "quote": "HMBS loss increases delta-aminolevulinic acid.",
                }
            ],
            "created_at": "2026-10-20T09:00:00+08:00",
            "updated_at": "2026-10-20T09:00:00+08:00",
        },
        {
            "id": "ev_hmbs_aip_02",
            "stance": "contradicts",
            "conclusion": "一项队列研究未见线粒体功能变化。",
            "papers": [
                {
                    "paper_id": "p2",
                    "page": 2,
                    "quote": "Mitochondrial function was not significantly changed.",
                }
            ],
            "created_at": "2026-10-21T09:00:00+08:00",
            "updated_at": "2026-10-21T09:00:00+08:00",
        },
    ]
    prop["evidence_updates_since_review"] = 10
    store.put_prop(prop)
    return prop["id"]


def _review(task: dict, text: str) -> dict:
    return {
        "schema_version": 1,
        "kind": "proposition-review",
        "prop_id": task["prop_id"],
        "review": text,
        "body_html": "<h2>结论</h2><p>新结论。</p>",
        "proposal": {
            "schema_version": 3,
            "proposal_id": "p_review_hmbs_aip_01",
            "push_id": None,
            "op": "update_proposition_review",
            "target_type": "proposition",
            "target_id": task["prop_id"],
            "diff": {"op": "replace", "path": "review", "value": text},
            "before": task["previous_review"],
            "after": text,
            "rationale": "第 10 条证据采纳后重写综述。",
            "confidence": 0.8,
            "status": "draft",
        },
    }


def test_review_task_check_and_render(kl_home, tmp_path):
    prop_id = _seed(kl_home)
    task = review_task.build_task(kl_home, prop_id, "q_review_01")
    assert task["stats"]["supports"] == 1
    assert task["stats"]["contradicts"] == 1
    text = (
        "## 结论\n新结论。\n"
        "## 支持证据\n一条支持。\n"
        "## 反证与边界\n一条反证。\n"
        "## 待验证\n需要更多样本。"
    )
    review = _review(task, text)
    errors = review_task.validate(task, review)
    assert errors == []
    assert review["stats"]["added"] >= 1

    out = tmp_path / "review.html"
    review_task.render_html(kl_home, review, out)
    page = out.read_text(encoding="utf-8")
    assert "命题综述" in page
    assert "证据附录" in page
    assert "ev_hmbs_aip_02" in page
    assert '<span class="diff-add"' not in page  # no diff markup in the minimal body
    assert "clamp(16px, 1.1vw + 12px, 20px)" in page


def test_review_check_rejects_wrong_sections_and_long_text(kl_home):
    prop_id = _seed(kl_home)
    task = review_task.build_task(kl_home, prop_id)
    bad = _review(task, "## 结论\n只有一节。")
    assert any("exactly four sections" in e for e in review_task.validate(task, bad))

    long_text = (
        "## 结论\n" + "很长。" * 800 + "\n"
        "## 支持证据\n一。\n## 反证与边界\n无。\n## 待验证\n无。"
    )
    too_long = _review(task, long_text)
    assert any("exceeds 2000" in e for e in review_task.validate(task, too_long))
