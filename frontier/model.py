"""frontier: checkpoints -> retrieval queries, plus rating-driven state."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from common import now, read_yaml, write_yaml

VERDICT_VALUE = {"irrelevant": 0.0, "ok": 0.5, "great": 1.0}
SOURCES = ("arxiv", "europepmc")


class FrontierError(RuntimeError):
    pass


def load(home: Path) -> tuple[dict, dict]:
    vocab = read_yaml(Path(home) / "frontier.yaml")
    if not vocab:
        raise FrontierError(f"missing {(Path(home) / 'frontier.yaml')}")
    state = read_yaml(Path(home) / "state" / "checkpoints.yaml") or {
        "schema_version": 1,
        "checkpoints": {},
    }
    state.setdefault("checkpoints", {})
    return vocab, state


def save_state(home: Path, state: dict) -> None:
    write_yaml(Path(home) / "state" / "checkpoints.yaml", state)


def checkpoints(vocab: dict) -> list[dict]:
    return list(vocab.get("checkpoints") or [])


def _quote(term: str) -> str:
    return '"' + term.replace('"', '\\"') + '"'


def _arxiv_query(terms: list[str], start: str, end: str) -> str:
    body = " OR ".join(f"abs:{_quote(t)}" for t in terms)
    s = start.replace("-", "")
    e = end.replace("-", "")
    return f"({body}) AND submittedDate:[{s}0000 TO {e}2359]"


def _epmc_query(terms: list[str], start: str, end: str) -> str:
    body = " OR ".join(f"TITLE_ABS:{_quote(t)}" for t in terms)
    return f"({body}) AND (FIRST_PDATE:[{start} TO {end}])"


def plan(
    home: Path,
    day: str | None = None,
    days: int = 7,
    limit: int = 20,
    sources: tuple[str, ...] = SOURCES,
) -> dict:
    vocab, state = load(home)
    end = date.fromisoformat(day) if day else date.today()
    start = end - timedelta(days=max(days - 1, 0))
    queries = []
    for cp in checkpoints(vocab):
        st = state["checkpoints"].get(cp["id"], {})
        if not cp.get("enabled", True) or st.get("enabled") is False:
            continue
        terms = [t for t in cp.get("ontology", []) if t]
        if not terms:
            continue
        for source in sources:
            query_id = f"q_{cp['id']}_{source}"
            query = (
                _arxiv_query(terms, start.isoformat(), end.isoformat())
                if source == "arxiv"
                else _epmc_query(terms, start.isoformat(), end.isoformat())
            )
            queries.append(
                {
                    "query_id": query_id,
                    "checkpoint_id": cp["id"],
                    "kg_node_id": cp.get("kg_node_id"),
                    "source": source,
                    "query": query,
                    "terms": terms,
                    "annotation": cp.get("annotation", ""),
                    "limit": limit,
                }
            )
    return {
        "schema_version": 1,
        "date": end.isoformat(),
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "generated_at": now(),
        "queries": queries,
    }


def validate(home: Path) -> dict:
    vocab, _ = load(home)
    problems, rows = [], []
    for cp in checkpoints(vocab):
        node_id = cp.get("kg_node_id")
        exists = bool(node_id) and (
            Path(home) / "archive" / "kg" / "nodes" / f"{node_id}.json"
        ).exists()
        rows.append(
            {
                "checkpoint_id": cp.get("id"),
                "label": cp.get("label", ""),
                "kg_node_id": node_id,
                "kg_node_exists": exists,
                "terms": len(cp.get("ontology", [])),
                "enabled": bool(cp.get("enabled", True)),
            }
        )
        if not exists:
            problems.append(f"{cp.get('id')}: missing kg node {node_id!r}")
    return {"ok": not problems, "checkpoints": rows, "problems": problems}


def record(home: Path, checkpoint_id: str, verdict: str, pushed: bool = False) -> dict:
    if verdict not in VERDICT_VALUE:
        raise FrontierError(f"verdict must be one of {sorted(VERDICT_VALUE)}")
    vocab, state = load(home)
    if checkpoint_id not in {c["id"] for c in checkpoints(vocab)}:
        raise FrontierError(f"unknown checkpoint: {checkpoint_id}")
    st = state["checkpoints"].setdefault(
        checkpoint_id,
        {
            "weight": 5,
            "ema": 0.5,
            "enabled": True,
            "last_checked": None,
            "hit_rate": {
                "checked": 0,
                "pushed": 0,
                "scored_total": 0,
                "scored_positive": 0,
            },
            "proposals": [],
        },
    )
    st.setdefault("hit_rate", {})
    hr = st["hit_rate"]
    for key in ("checked", "pushed", "scored_total", "scored_positive"):
        hr.setdefault(key, 0)
    hr["scored_total"] += 1
    if verdict == "great":
        hr["scored_positive"] += 1
    if pushed:
        hr["pushed"] += 1
    ema = float(st.get("ema", 0.5))
    st["ema"] = round(0.7 * ema + 0.3 * VERDICT_VALUE[verdict], 4)
    st["weight"] = max(1, min(10, round(1 + 9 * st["ema"])))
    st["last_checked"] = date.today().isoformat()
    save_state(home, state)
    return {
        "checkpoint_id": checkpoint_id,
        "verdict": verdict,
        "ema": st["ema"],
        "weight": st["weight"],
        "hit_rate": hr,
    }


def show(home: Path, checkpoint_id: str | None = None) -> dict:
    vocab, state = load(home)
    rows = []
    for cp in checkpoints(vocab):
        if checkpoint_id and cp["id"] != checkpoint_id:
            continue
        st = state["checkpoints"].get(cp["id"], {})
        rows.append(
            {
                "id": cp["id"],
                "label": cp.get("label", ""),
                "kg_node_id": cp.get("kg_node_id"),
                "enabled": bool(cp.get("enabled", True)),
                "weight": st.get("weight", 5),
                "ema": st.get("ema", 0.5),
                "last_checked": st.get("last_checked"),
                "hit_rate": st.get("hit_rate", {}),
            }
        )
    return {"schema_version": 1, "checkpoints": rows}
