"""editor: rank candidates; learn ranking preference from ratings."""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path

from archive.store import Archive
from common import now, read_json, read_jsonl, read_yaml, write_yaml

VERDICT_VALUE = {"irrelevant": 0.0, "ok": 0.5, "great": 1.0}
PRIOR_N = 2.0
PRIOR_MEAN = 0.5


def _mean(sum_value: float, n: int) -> float:
    return (sum_value + PRIOR_MEAN * PRIOR_N) / (n + PRIOR_N)


def fit(
    home: Path,
    ratings_path: Path | None = None,
    pushes_dir: Path | None = None,
    raw_dir: Path | None = None,
) -> dict:
    home = Path(home)
    ratings_path = Path(ratings_path or home / "ratings.jsonl")
    store = Archive(home)
    pushes_dir = Path(pushes_dir or store.pushes)
    raw_dir = Path(raw_dir or store.raw)

    sums: dict[str, list[float]] = {}
    source_sums: dict[str, list[float]] = {}

    def add(bucket: dict[str, list[float]], key: str, value: float) -> None:
        row = bucket.setdefault(key, [0.0, 0])
        row[0] += value
        row[1] += 1

    for rating in read_jsonl(ratings_path):
        value = VERDICT_VALUE.get(rating.get("verdict"))
        if value is None:
            continue
        push = read_json(pushes_dir / f"{rating.get('push_id')}.json") or {}
        checkpoint = push.get("checkpoint_id")
        if checkpoint:
            add(sums, checkpoint, value)
        for paper_id in push.get("paper_ids", [])[:1]:
            paper = read_json(raw_dir / f"{paper_id}.json") or {}
            if paper.get("source"):
                add(source_sums, paper["source"], value)

    model = {
        "schema_version": 1,
        "updated_at": now(),
        "prior": {"n": PRIOR_N, "mean": PRIOR_MEAN},
        "checkpoints": {
            cp: {"n": n, "mean": round(_mean(total, n), 4)}
            for cp, (total, n) in sorted(sums.items())
        },
        "sources": {
            src: {"n": n, "mean": round(_mean(total, n), 4)}
            for src, (total, n) in sorted(source_sums.items())
        },
    }
    return model


def _relevance(paper: dict, terms: list[str]) -> tuple[float, int]:
    text = f"{paper.get('title','')} {paper.get('abstract','')}".lower()
    matched = [t for t in terms if t and t.lower() in text]
    if not matched:
        return 0.0, 0
    coverage = len(matched) / max(len(terms), 1)
    hit_component = min(1.0, len(matched) / 3)
    return 0.7 * hit_component + 0.3 * coverage, len(matched)


def _recency(published: str | None, day: date) -> float:
    if not published:
        return 0.5
    try:
        delta = (day - date.fromisoformat(str(published)[:10])).days
    except ValueError:
        return 0.5
    return math.exp(-max(delta, 0) / 14)


def _cards(home: Path) -> dict[str, dict]:
    card_dir = Path(home) / "archive" / "cards"
    return {
        row["id"]: row
        for row in (read_json(p) or {} for p in sorted(card_dir.glob("*.json")))
        if row.get("id")
    }


def rank(
    home: Path,
    candidates: list[dict],
    day: str | None = None,
    limit: int = 5,
    per_checkpoint: int = 2,
    model_path: Path | None = None,
) -> dict:
    home = Path(home)
    checkpoints = _cards(home)
    state = read_yaml(home / "state" / "checkpoints.yaml") or {}
    model = read_yaml(Path(model_path or home / "state" / "editor.yaml")) or {}
    day_obj = date.fromisoformat(day) if day else date.today()
    states = state.get("checkpoints", {})

    ranked: list[dict] = []
    for cand in candidates:
        cp_id = cand.get("checkpoint_id") or cand.get("retrieval", {}).get("checkpoint_id")
        cp = checkpoints.get(cp_id, {})
        terms = [t for t in cp.get("ontology", []) if t]
        rel, matched = _relevance(cand, terms)
        rec = _recency(cand.get("published"), day_obj)
        cp_pref = (model.get("checkpoints", {}).get(cp_id) or {}).get("mean", PRIOR_MEAN)
        src = cand.get("source") or cand.get("retrieval", {}).get("source") or ""
        src_pref = (model.get("sources", {}).get(src) or {}).get("mean", PRIOR_MEAN)
        pref = 0.6 * cp_pref + 0.4 * src_pref
        weight = float(states.get(cp_id, {}).get("weight", 5)) / 10.0
        score = 0.40 * rel + 0.15 * rec + 0.30 * pref + 0.15 * weight
        ranked.append(
            {
                "checkpoint_id": cp_id,
                "paper": {k: v for k, v in cand.items() if k not in ("retrieval",)},
                "score": round(score, 4),
                "breakdown": {
                    "relevance": round(rel, 4),
                    "recency": round(rec, 4),
                    "preference": round(pref, 4),
                    "weight": round(weight, 4),
                },
                "rationale": (
                    f"ontology 命中 {matched} 个词；"
                    f"{cand.get('published') or '未知日期'}；"
                    f"checkpoint 偏好 {cp_pref:.2f} / 来源偏好 {src_pref:.2f}"
                ),
            }
        )

    ranked.sort(key=lambda row: (-row["score"], row["paper"].get("paper_id", "")))

    selected, counts = [], {}
    for row in ranked:
        cp_id = row["checkpoint_id"]
        if counts.get(cp_id, 0) >= per_checkpoint:
            continue
        counts[cp_id] = counts.get(cp_id, 0) + 1
        selected.append(row)
        if len(selected) >= limit:
            break

    return {
        "schema_version": 1,
        "date": day_obj.isoformat(),
        "model": {
            "checkpoints": model.get("checkpoints", {}),
            "sources": model.get("sources", {}),
        },
        "selected": selected,
    }


def write_model(model: dict, path: Path) -> None:
    write_yaml(Path(path), model)


def load_candidates(path: Path) -> list[dict]:
    return read_jsonl(Path(path))
