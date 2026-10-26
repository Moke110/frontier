"""Bitable mirror for the local knowledge layer.

During the 7-day dual-run the local archive stays authoritative for reads and
writes; this module idempotently mirrors cards / propositions / evidence /
papers / changelog into the production Base. `compare` reports drift so the
cutover can be decided on evidence rather than hope.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from archive.store import Archive
from common import now, read_json

CONFIG_REL = Path("knowledge") / "base.json"


class BitableError(RuntimeError):
    pass


def load_config(home: Path) -> dict:
    path = Path(home) / CONFIG_REL
    cfg = read_json(path)
    if not cfg or not cfg.get("base_token") or not cfg.get("tables"):
        raise BitableError(f"missing Bitable config: {path}")
    return cfg


class LarkBitableClient:
    """Thin lark-cli wrapper: list / create / update records."""

    def __init__(self, config: dict, *, identity: str = "user"):
        self.config = config
        self.identity = identity
        self.base = config["base_token"]

    def _run(self, *args: str) -> dict:
        proc = subprocess.run(
            ["lark-cli", *args, "--as", self.identity, "--base-token", self.base,
             "--format", "json"],
            capture_output=True,
            text=True,
        )
        payload = json.loads(proc.stdout or "{}")
        if not payload.get("ok"):
            raise BitableError(
                f"lark-cli {' '.join(args)} failed: {payload.get('error') or proc.stderr}"
            )
        return payload

    def list(self, table: str) -> list[dict]:
        out: list[dict] = []
        offset = 0
        while True:
            payload = self._run(
                "base", "+record-list", "--table-id", table,
                "--limit", "200", "--offset", str(offset),
            )
            data = payload.get("data") or {}
            names = data.get("fields") or []
            rows = data.get("data") or []
            ids = data.get("record_id_list") or []
            out.extend(
                {"record_id": rid, "fields": dict(zip(names, row))}
                for rid, row in zip(ids, rows)
            )
            if not data.get("has_more") or not ids:
                return out
            offset += len(ids)

    def create(self, table: str, rows: list[dict]) -> list[str]:
        if not rows:
            return []
        payload = self._run(
            "base", "+record-batch-create", "--table-id", table,
            "--json", json.dumps({"create_records": rows}, ensure_ascii=False),
        )
        return payload["data"].get("record_id_list") or []

    def update(self, table: str, updates: dict[str, dict]) -> None:
        if not updates:
            return
        self._run(
            "base", "+record-batch-update", "--table-id", table,
            "--json", json.dumps({"update_records": updates}, ensure_ascii=False),
        )

    def field_names(self, table: str) -> list[str]:
        payload = self._run("base", "+field-list", "--table-id", table)
        return [f.get("name") for f in payload["data"].get("fields") or []]

    def ensure_options(self, table: str, field: str, values: list[str]) -> None:
        """Add any missing multi-select options before writing values."""
        fields = self._run("base", "+field-list", "--table-id", table)["data"]["fields"]
        target = next((f for f in fields if f.get("name") == field), None)
        if not target or target.get("type") != "select":
            return
        existing = [o.get("name") for o in target.get("options") or []]
        missing = [v for v in values if v and v not in existing]
        if not missing:
            return
        options = [{"name": name, "hue": "Blue"} for name in existing + missing]
        self._run(
            "base", "+field-update", "--table-id", table,
            "--field-id", target["id"],
            "--json", json.dumps(
                {"name": field, "type": "select", "multiple": True, "options": options},
                ensure_ascii=False,
            ),
            "--yes",
        )


# ------------------------------------------------------------------ mapping
def _dt(value) -> str:
    return str(value or "2026-10-20T09:00:00+08:00")


def _date_eq(left, right) -> bool:
    return str(left or "")[:19] == str(right or "")[:19]


def _select(value) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)] if value not in (None, "") else []


def _links(record_ids: list[str]) -> list[dict]:
    return [{"id": rid} for rid in record_ids if rid]


def _link_ids(value) -> list[str]:
    return [row.get("id") for row in value or [] if isinstance(row, dict) and row.get("id")]


def _paper_key(paper: dict) -> tuple:
    return (
        paper.get("paper_id"),
        paper.get("push_id") or "",
        paper.get("page"),
        paper.get("quote"),
    )


def card_row(card: dict) -> dict:
    return {
        "卡片 ID": card["id"],
        "label": card.get("label", ""),
        "ontology": card.get("ontology", []),
        "annotation": card.get("annotation", ""),
        "created_at": _dt(card.get("created_at")),
        "updated_at": _dt(card.get("updated_at")),
    }


def log_rows(prop: dict) -> list[dict]:
    rows = []
    for index, log in enumerate(prop.get("changelog", []), start=1):
        rows.append(
            {
                "变更 ID": f"cl_{prop['id']}_{index:02d}",
                "at": _dt(log.get("at")),
                "action": [log.get("action") or "created"],
                "field": [log.get("field") or "review"],
                "before": json.dumps(log.get("before"), ensure_ascii=False),
                "after": json.dumps(log.get("after"), ensure_ascii=False),
                "rationale": log.get("rationale", ""),
                "source_kind": (log.get("source") or {}).get("kind", ""),
                "source_id": str((log.get("source") or {}).get("id", "")),
            }
        )
    return rows


# -------------------------------------------------------------------- sync
def _index(rows: list[dict], key: str) -> dict[str, dict]:
    return {
        str(row["fields"].get(key)): row
        for row in rows
        if row["fields"].get(key) not in (None, "")
    }


def _plan_cards(local: list[dict], remote: list[dict]) -> tuple[list[dict], dict[str, dict]]:
    by_id = _index(remote, "卡片 ID")
    creates, updates = [], {}
    for card in local:
        row = card_row(card)
        current = by_id.get(card["id"])
        if not current:
            creates.append(row)
            continue
        diff = {}
        for field, value in row.items():
            if field.endswith("_at"):
                if not _date_eq(value, current["fields"].get(field)):
                    diff[field] = value
            elif current["fields"].get(field) != value:
                diff[field] = value
        if diff:
            updates[current["record_id"]] = diff
    return creates, updates


def _plan_papers(
    local: list[dict], remote: list[dict], source_ids: dict[str, str] | None = None
) -> tuple[list[dict], list[str]]:
    by_key = {_paper_key(row["fields"]): row for row in remote}
    creates, ids = [], []
    for prop in local:
        for ev in prop.get("evidence", []):
            for paper in ev.get("papers", []):
                key = _paper_key(paper)
                if key in by_key:
                    ids.append(by_key[key]["record_id"])
                    continue
                row = {
                    "paper_id": paper.get("paper_id"),
                    "push_id": paper.get("push_id") or "",
                    "page": paper.get("page"),
                    "quote": paper.get("quote", ""),
                    "added_at": _dt(paper.get("added_at")),
                }
                if source_ids is not None:
                    row["原文"] = _links([source_ids.get(paper.get("paper_id"))])
                creates.append(row)
    return creates, ids


def sync(home: Path, client=None, *, dry_run: bool = False) -> dict:
    home = Path(home)
    config = load_config(home)
    client = client or LarkBitableClient(config)
    tables = config["tables"]
    store = Archive(home)
    cards = store.list_cards()
    props = store.list_props()

    remote_cards = client.list(tables["cards"])
    remote_props = client.list(tables["propositions"])
    remote_evidence = client.list(tables["evidence"])
    remote_papers = client.list(tables["papers"])
    remote_logs = client.list(tables["logs"])

    report = {
        "ok": True,
        "dry_run": dry_run,
        "created": {},
        "updated": {},
    }

    card_creates, card_updates = _plan_cards(cards, remote_cards)
    report["created"]["cards"] = len(card_creates)
    report["updated"]["cards"] = len(card_updates)
    if not dry_run and card_creates:
        client.ensure_options(
            tables["cards"], "ontology",
            sorted({t for c in cards for t in c.get("ontology", [])}),
        )
        client.create(tables["cards"], card_creates)
        remote_cards = client.list(tables["cards"])
    if not dry_run and card_updates:
        client.update(tables["cards"], card_updates)

    source_ids = None
    if tables.get("sources"):
        field_names = getattr(client, "field_names", lambda table: [])(tables["papers"])
        if "原文" in field_names:
            source_ids = {
                str(row["fields"].get("原文 ID")): row["record_id"]
                for row in client.list(tables["sources"])
                if row["fields"].get("原文 ID")
            }
    paper_creates, _ = _plan_papers(props, remote_papers, source_ids)
    report["created"]["papers"] = len(paper_creates)
    if not dry_run and paper_creates:
        client.create(tables["papers"], paper_creates)
        remote_papers = client.list(tables["papers"])
    paper_ids = {_paper_key(row["fields"]): row["record_id"] for row in remote_papers}
    paper_updates = {}
    if source_ids is not None:
        for row in remote_papers:
            link = _links([source_ids.get(row["fields"].get("paper_id"))])
            if set(_link_ids(row["fields"].get("原文"))) != {item["id"] for item in link}:
                paper_updates[row["record_id"]] = {"原文": link}
        report["updated"]["papers"] = len(paper_updates)
        if not dry_run and paper_updates:
            client.update(tables["papers"], paper_updates)

    card_ids = {row["fields"].get("卡片 ID"): row["record_id"] for row in remote_cards}
    evidence_by_id = _index(remote_evidence, "证据 ID")
    evidence_creates, evidence_updates = [], {}
    for prop in props:
        for ev in prop.get("evidence", []):
            links = _links([paper_ids.get(_paper_key(p)) for p in ev.get("papers", [])])
            row = {
                "证据 ID": ev["id"],
                "stance": [ev.get("stance") or "supports"],
                "conclusion": ev.get("conclusion", ""),
                "migrated_from_v2": bool(ev.get("migrated_from_v2")),
                "created_at": _dt(ev.get("created_at")),
                "updated_at": _dt(ev.get("updated_at")),
                "报道": links,
            }
            current = evidence_by_id.get(ev["id"])
            if not current:
                evidence_creates.append(row)
                continue
            diff = {}
            if current["fields"].get("conclusion") != row["conclusion"]:
                diff["conclusion"] = row["conclusion"]
            if _select(current["fields"].get("stance")) != row["stance"]:
                diff["stance"] = row["stance"]
            if set(_link_ids(current["fields"].get("报道"))) != {
                link["id"] for link in links
            }:
                diff["报道"] = links
            if diff:
                evidence_updates[current["record_id"]] = diff
    report["created"]["evidence"] = len(evidence_creates)
    report["updated"]["evidence"] = len(evidence_updates)
    if not dry_run and evidence_creates:
        client.create(tables["evidence"], evidence_creates)
        remote_evidence = client.list(tables["evidence"])
    if not dry_run and evidence_updates:
        client.update(tables["evidence"], evidence_updates)
    evidence_ids = {
        row["fields"].get("证据 ID"): row["record_id"] for row in remote_evidence
    }

    log_by_id = _index(remote_logs, "变更 ID")
    log_creates, log_updates = [], {}
    for prop in props:
        for row in log_rows(prop):
            current = log_by_id.get(row["变更 ID"])
            if not current:
                log_creates.append(row)
                continue
            diff = {
                key: value for key, value in row.items()
                if key not in ("at",)
                and current["fields"].get(key) != value
            }
            if diff:
                log_updates[current["record_id"]] = diff
    report["created"]["logs"] = len(log_creates)
    report["updated"]["logs"] = len(log_updates)
    if not dry_run and log_creates:
        client.create(tables["logs"], log_creates)
        remote_logs = client.list(tables["logs"])
    if not dry_run and log_updates:
        client.update(tables["logs"], log_updates)
    log_ids = {row["fields"].get("变更 ID"): row["record_id"] for row in remote_logs}

    prop_by_id = _index(remote_props, "命题 ID")
    prop_creates, prop_updates = [], {}
    for prop in props:
        links = _links([evidence_ids.get(e["id"]) for e in prop.get("evidence", [])])
        card_links = _links([card_ids.get(c) for c in prop.get("related_knowledge", [])])
        log_links = _links(
            [log_ids.get(f"cl_{prop['id']}_{n:02d}")
             for n in range(1, len(prop.get("changelog", [])) + 1)]
        )
        row = {
            "命题 ID": prop["id"],
            "title": prop.get("title", ""),
            "review": prop.get("review", ""),
            "证据更新计数": int(prop.get("evidence_updates_since_review") or 0),
            "created_at": _dt(prop.get("created_at")),
            "updated_at": _dt(prop.get("updated_at")),
            "关联卡片": card_links,
            "证据": links,
            "变更日志": log_links,
        }
        current = prop_by_id.get(prop["id"])
        if not current:
            prop_creates.append(row)
            continue
        diff = {}
        for field in ("title", "review", "证据更新计数"):
            if current["fields"].get(field) != row[field]:
                diff[field] = row[field]
        for field in ("关联卡片", "证据", "变更日志"):
            if set(_link_ids(current["fields"].get(field))) != {
                link["id"] for link in row[field]
            }:
                diff[field] = row[field]
        if diff:
            prop_updates[current["record_id"]] = diff
    report["created"]["propositions"] = len(prop_creates)
    report["updated"]["propositions"] = len(prop_updates)
    if not dry_run:
        if prop_creates:
            client.create(tables["propositions"], prop_creates)
        if prop_updates:
            client.update(tables["propositions"], prop_updates)
        write_ledger(home)

    return report


# ----------------------------------------------------------------- compare
def compare(home: Path, client=None) -> dict:
    home = Path(home)
    config = load_config(home)
    client = client or LarkBitableClient(config)
    tables = config["tables"]
    store = Archive(home)
    local_cards = {c["id"]: c for c in store.list_cards()}
    local_props = {p["id"]: p for p in store.list_props()}
    remote_cards = {r["fields"].get("卡片 ID"): r for r in client.list(tables["cards"])}
    remote_props = {r["fields"].get("命题 ID"): r for r in client.list(tables["propositions"])}

    diffs = []
    for card_id, card in local_cards.items():
        remote = remote_cards.get(card_id)
        if not remote:
            diffs.append({"kind": "card", "id": card_id, "field": "*", "local": "exists", "remote": None})
            continue
        if remote["fields"].get("label") != card.get("label"):
            diffs.append({"kind": "card", "id": card_id, "field": "label",
                          "local": card.get("label"), "remote": remote["fields"].get("label")})
        if set(_select(remote["fields"].get("ontology"))) != set(card.get("ontology", [])):
            diffs.append({"kind": "card", "id": card_id, "field": "ontology",
                          "local": card.get("ontology"), "remote": remote["fields"].get("ontology")})
        if remote["fields"].get("annotation") != card.get("annotation"):
            diffs.append({"kind": "card", "id": card_id, "field": "annotation",
                          "local": card.get("annotation"), "remote": remote["fields"].get("annotation")})
    for prop_id, prop in local_props.items():
        remote = remote_props.get(prop_id)
        if not remote:
            diffs.append({"kind": "proposition", "id": prop_id, "field": "*", "local": "exists", "remote": None})
            continue
        for field, local_value in (
            ("title", prop.get("title")),
            ("review", prop.get("review")),
            ("证据更新计数", int(prop.get("evidence_updates_since_review") or 0)),
        ):
            if remote["fields"].get(field) != local_value:
                diffs.append({"kind": "proposition", "id": prop_id, "field": field,
                              "local": local_value, "remote": remote["fields"].get(field)})
    return {
        "ok": not diffs,
        "counts": {"cards": len(local_cards), "propositions": len(local_props)},
        "diffs": diffs,
    }


LEDGER_REL = Path("knowledge") / "state.json"


def ledger_path(home: Path) -> Path:
    return Path(home) / LEDGER_REL


def current_ledger(home: Path) -> dict:
    store = Archive(Path(home))
    return {
        "schema_version": 1,
        "updated_at": now(),
        "cards": {
            c["id"]: {"annotation": c.get("annotation", "")}
            for c in store.list_cards()
        },
        "propositions": {
            p["id"]: {"title": p.get("title", ""), "review": p.get("review", "")}
            for p in store.list_props()
        },
        "evidence": {
            e["id"]: {"conclusion": e.get("conclusion", "")}
            for p in store.list_props()
            for e in p.get("evidence", [])
        },
    }


def write_ledger(home: Path) -> dict:
    from common import write_json

    state = current_ledger(home)
    write_json(ledger_path(home), state)
    return state


def pull(home: Path, client=None) -> dict:
    """Apply text-only manual edits from Bitable back into the local archive.

    Only title / review / annotation / conclusion are accepted. Invalid edits
    are left in Bitable with a 待修正 note; structural columns are never pulled.
    """
    home = Path(home)
    config = load_config(home)
    client = client or LarkBitableClient(config)
    tables = config["tables"]
    store = Archive(home)
    ledger = read_json(ledger_path(home))
    if not ledger:
        write_ledger(home)
        return {"ok": True, "initialized": True}

    applied, notes = [], []

    remote_cards = client.list(tables["cards"])
    for row in remote_cards:
        card_id = row["fields"].get("卡片 ID")
        if not card_id:
            continue
        try:
            local = store.get_card(card_id)
        except Exception:
            continue
        old = (ledger.get("cards", {}).get(card_id) or {}).get("annotation")
        new = row["fields"].get("annotation")
        if new is None or new == old or new == local.get("annotation"):
            continue
        if not str(new).strip():
            notes.append({"kind": "card", "id": card_id, "field": "annotation",
                          "reason": "annotation must not be empty"})
            continue
        local["annotation"] = new
        store.put_card(local)
        applied.append({"kind": "card", "id": card_id, "field": "annotation"})

    remote_props = client.list(tables["propositions"])
    for row in remote_props:
        prop_id = row["fields"].get("命题 ID")
        if not prop_id:
            continue
        try:
            local = store.get_prop(prop_id)
        except Exception:
            continue
        for field, action, limit in (
            ("title", "title_changed", None),
            ("review", "review_changed", 2000),
        ):
            old = (ledger.get("propositions", {}).get(prop_id) or {}).get(field)
            new = row["fields"].get(field)
            if new is None or new == old or new == local.get(field):
                continue
            valid = bool(str(new).strip()) and (
                limit is None or len(str(new)) <= limit
            )
            if not valid:
                notes.append({"kind": "proposition", "id": prop_id, "field": field,
                              "reason": f"invalid {field} (empty or >{limit})"})
                continue
            store.update_prop(
                prop_id,
                {field: new},
                action=action,
                source={"kind": "bitable", "id": row["record_id"]},
                rationale="用户在 Bitable 直接编辑",
            )
            applied.append({"kind": "proposition", "id": prop_id, "field": field})

    remote_evidence = client.list(tables["evidence"])
    props_by_ev = {
        e["id"]: p["id"]
        for p in store.list_props()
        for e in p.get("evidence", [])
    }
    for row in remote_evidence:
        ev_id = row["fields"].get("证据 ID")
        new = row["fields"].get("conclusion")
        old = (ledger.get("evidence", {}).get(ev_id) or {}).get("conclusion")
        if not ev_id or new is None or new == old:
            continue
        prop_id = props_by_ev.get(ev_id)
        if not prop_id:
            continue
        prop = store.get_prop(prop_id)
        entry = next((e for e in prop.get("evidence", []) if e.get("id") == ev_id), None)
        if not entry or new == entry.get("conclusion"):
            continue
        if not (1 <= len(str(new).strip()) <= 200):
            notes.append({"kind": "evidence", "id": ev_id, "field": "conclusion",
                          "reason": "conclusion must be 1..200 chars"})
            continue
        entry["conclusion"] = str(new).strip()
        entry["updated_at"] = now()
        store.put_prop(prop)
        applied.append({"kind": "evidence", "id": ev_id, "field": "conclusion"})

    # Translate notes into the Base 待修正 column; clear fixed rows.
    for note in notes:
        table = {
            "card": tables["cards"],
            "proposition": tables["propositions"],
            "evidence": tables["evidence"],
        }[note["kind"]]
        row = next(
            (
                r for r in (
                    remote_cards if note["kind"] == "card"
                    else remote_props if note["kind"] == "proposition"
                    else remote_evidence
                )
                if r["fields"].get("卡片 ID" if note["kind"] == "card"
                                   else "命题 ID" if note["kind"] == "proposition"
                                   else "证据 ID") == note["id"]
            ),
            None,
        )
        if row:
            client.update(table, {row["record_id"]: {
                "待修正": f"{note['field']}: {note['reason']}"
            }})

    write_ledger(home)
    return {"ok": True, "applied": applied, "notes": notes}
