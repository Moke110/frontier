"""Lark cards for the unified question queue: one card = one entity update.

The rating card asks for a verdict; these cards ask for one decision about one
knowledge card or one proposition: agree with every proposed change, or reject
them all. Evidence and page anchors stay on the card so the reader does not
have to open the PDF again.
"""

from __future__ import annotations

from typing import Any

from common import clip

TEMPLATE = {"card": "blue", "proposition": "violet", "proposition_review": "violet"}
MAX_CHANGES = 3
MAX_EVIDENCE = 2
DIFF_LIMIT = 260


def _short(value: Any, limit: int = DIFF_LIMIT) -> str:
    return clip(str(value or ""), limit)


def _lines(value: Any) -> list[str]:
    return [line.strip() for line in str(value or "").splitlines() if line.strip()]


def _text_diff(before: Any, after: Any) -> str:
    """Line-level diff for long annotation/content fields.

    Falls back to before/new when the text was rewritten rather than appended.
    """
    old_lines, new_lines = _lines(before), _lines(after)
    added = [line for line in new_lines if line not in old_lines]
    removed = [line for line in old_lines if line not in new_lines]
    if added or removed:
        parts = []
        for line in removed[:4]:
            parts.append(f"<font color='red'>- {_short(line, 160)}</font>")
        for line in added[:4]:
            parts.append(f"<font color='green'>+ {_short(line, 160)}</font>")
        if len(removed) + len(added) > 8:
            parts.append("<font color='grey'>…</font>")
        return "\n".join(parts)
    return f"<font color='grey'>原</font> {_short(before)}\n**新** {_short(after)}"


def _inline(value: Any) -> str:
    text = _short(value, 80).replace("`", "'")
    return f"`{text}`" if text else "—"


def _op_label(op: str) -> str:
    return {
        "add_card_ontology": "补充 ontology",
        "update_card_annotation": "改写 annotation",
        "create_card": "新建知识卡片",
        "create_proposition": "新建命题",
        "update_proposition_title": "改写命题标题",
        "update_proposition_review": "改写命题综述",
        "add_proposition_evidence": "新增证据",
        "merge_proposition_evidence": "并入已有证据",
        "update_proposition_related_knowledge": "调整关联卡片",
    }.get(op, op)


def _change_block(proposal: dict) -> str:
    op = proposal.get("op") or proposal.get("kind", "")
    value = (proposal.get("diff") or {}).get("value")
    before = proposal.get("before")
    after = proposal.get("after")
    lines = [f"**{_op_label(op)}**"]

    if op == "add_card_ontology":
        terms = value if isinstance(value, list) else [value]
        lines.append("新增：" + "、".join(_inline(t) for t in terms if t))
        lines.append(f"<font color='grey'>现有：{'、'.join(_inline(t) for t in (before or [])) or '—'}</font>")
    elif op == "update_card_annotation":
        lines.append(_text_diff(before, after or value))
    elif op == "create_card":
        card = value if isinstance(value, dict) else {}
        lines.append(f"**{_short(card.get('label'), 60)}**")
        lines.append("ontology：" + "、".join(_inline(t) for t in card.get("ontology") or []))
        lines.append(f"<font color='grey'>{_short(card.get('annotation'))}</font>")
    elif op == "create_proposition":
        prop = value if isinstance(value, dict) else {}
        lines.append(f"**{_short(prop.get('title'), 80)}**")
        lines.append(_short(prop.get("content")))
        related = prop.get("related_knowledge") or []
        lines.append("关联：" + "、".join(_inline(c) for c in related))
    elif op == "update_proposition_title":
        lines.append(f"<font color='grey'>原</font> {_short(before, 80)}")
        lines.append(f"**新** {_short(after or value, 80)}")
    elif op == "update_proposition_content":
        lines.append(_text_diff(before, after or value))
    elif op == "add_proposition_evidence":
        evidence = value if isinstance(value, dict) else {}
        stance = "支持" if evidence.get("stance") == "supports" else "反证"
        lines.append(f"<font color='grey'>立场：{stance}</font>")
        lines.append(_short(evidence.get("conclusion"), 200))
        papers = evidence.get("papers") or []
        if papers:
            paper = papers[0]
            lines.append(f"> {_short(paper.get('quote'), 300)}")
            where = f"第 {paper.get('page')} 页" if paper.get("page") else "摘要"
            lines.append(
                f"<font color='grey'>《{_short(paper.get('paper_id'), 60)}》 · {where}</font>"
            )
    elif op == "merge_proposition_evidence":
        evidence = value if isinstance(value, dict) else {}
        target = evidence.get("target_evidence_id") or "—"
        lines.append(f"并入 `{target}`")
        if evidence.get("conclusion"):
            lines.append(_short(evidence.get("conclusion"), 200))
        for paper in evidence.get("papers") or []:
            where = f"第 {paper.get('page')} 页" if paper.get("page") else "摘要"
            lines.append(
                f"> {_short(paper.get('quote'), 300)}\n"
                f"<font color='grey'>《{_short(paper.get('paper_id'), 60)}》 · {where}</font>"
            )
    elif op == "update_proposition_review":
        lines.append(_text_diff(before, after or value))
    elif op == "update_proposition_related_knowledge":
        lines.append(
            "<font color='grey'>原</font> "
            + ("、".join(_inline(c) for c in (before or [])) or "—")
        )
        lines.append("**新** " + "、".join(_inline(c) for c in (after or value or [])))
    else:  # v1 historical proposals should never reach a card
        lines.append(_short(value or before or after))
    return "\n".join(lines)


def _paper_line(push: dict) -> str:
    paper = push.get("paper") or {}
    title = paper.get("title") or ", ".join(push.get("paper_ids") or [])
    meta = []
    if paper.get("journal"):
        meta.append(clip(paper["journal"], 40))
    if paper.get("published"):
        meta.append(str(paper["published"]))
    suffix = f" · {' · '.join(meta)}" if meta else ""
    return f"来源：**{_short(title, 90)}**{suffix}"


def _evidence_lines(push: dict, proposals: list[dict]) -> list[str]:
    paper = push.get("paper") or {}
    paper_title = paper.get("title") or ", ".join(push.get("paper_ids") or [])
    rows, seen = [], set()
    shown = {
        (p.get("evidence") or {}).get("quote")
        for p in proposals
        if (p.get("op") or p.get("kind")) == "add_proposition_evidence"
    }
    for proposal in proposals:
        op = proposal.get("op") or proposal.get("kind")
        if op in ("add_proposition_evidence", "merge_proposition_evidence"):
            # The change block already shows these quotes and pages.
            continue
        evidence = proposal.get("evidence") or {}
        quote = _short(evidence.get("quote"), 300)
        if not quote or quote in shown:
            continue
        page = evidence.get("page")
        key = (page, quote)
        if key in seen:
            continue
        seen.add(key)
        where = f"第 {page} 页" if page else "摘要"
        rows.append(f"> {quote}\n<font color='grey'>《{_short(paper_title, 70)}》 · {where}</font>")
        if len(rows) >= MAX_EVIDENCE:
            break
    return rows


def _target_line(item: dict) -> str:
    target_type = item.get("target_type")
    target_id = item.get("target_id") or ""
    label = item.get("target_label") or ""
    if target_type == "card":
        if not target_id:
            return "**新建知识卡片**" + (f" · {label}" if label else "")
        return f"**`{target_id}`**" + (f" · {label}" if label and label != target_id else "")
    if target_type in ("proposition", "proposition_review"):
        if not target_id:
            return "**新建命题**" + (f" · {label}" if label and label != "新建命题" else "")
        return f"**`{target_id}`**" + (f" · {label}" if label and label != target_id else "")
    return item.get("summary") or "知识库更新"


def _header_title(kind: str, target_type: str, index: int, total: int) -> str:
    if kind == "proposition_review":
        label = "命题综述更新"
    elif target_type == "card":
        label = "知识卡片更新"
    else:
        label = "命题证据更新"
    return f"{label} · 第 {index} / {total} 题"


def _buttons(item: dict, proposal_ids: list[str]) -> dict:
    item_id = item.get("id") or item.get("queue_item_id") or ""
    review = item.get("kind") == "proposition_review" or item.get("target_type") == "proposition_review"
    base = {
        "queue_item_id": item_id,
        "proposal_ids": proposal_ids,
    }

    def button(name: str, text: str, kind: str, decision: str) -> dict:
        return {
            "tag": "button",
            "name": name,
            "text": {"tag": "plain_text", "content": text},
            "type": kind,
            "width": "fill",
            "behaviors": [
                {
                    "type": "callback",
                    "value": {**base, "decision": decision},
                }
            ],
        }

    return {
        "tag": "column_set",
        "flex_mode": "none",
        "horizontal_spacing": "8px",
        "columns": [
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "elements": [
                    button(
                        "adopt" if review else "agree_all",
                        "采纳此版" if review else "同意全部",
                        "primary_filled",
                        "adopt" if review else "agree_all",
                    )
                ],
            },
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "elements": [
                    button(
                        "keep_previous" if review else "reject_all",
                        "保持上一版" if review else "拒绝全部",
                        "danger",
                        "keep_previous" if review else "reject_all",
                    )
                ],
            },
        ],
    }


def build_update_card(push: dict, item: dict, index: int, total: int) -> dict:
    """Build one update-question card.

    ``item`` follows the queue item shape: ``kind`` is ``card_update`` or
    ``proposition_update``; ``payload`` contains ``target_type``, ``target_id``,
    ``proposal_ids`` and ``proposals``. A flat item (payload fields on top) is
    also accepted so sample fixtures stay readable.
    """
    payload = item.get("payload") or item
    proposals = payload.get("proposals") or []
    if not proposals:
        raise ValueError("update card needs at least one proposal")
    proposal_ids = payload.get("proposal_ids") or [
        p.get("proposal_id") for p in proposals if p.get("proposal_id")
    ]
    target_type = payload.get("target_type") or (
        "card"
        if item.get("kind") == "card_update"
        else "proposition_review"
        if item.get("kind") == "proposition_review"
        else "proposition"
    )
    merged = {
        **payload,
        "id": item.get("id") or item.get("queue_item_id"),
        "kind": item.get("kind"),
        "target_type": target_type,
    }
    shown = proposals[:MAX_CHANGES]
    blocks = [_change_block(p) for p in shown]
    if len(proposals) > MAX_CHANGES:
        blocks.append(f"<font color='grey'>还有 {len(proposals) - MAX_CHANGES} 条变更</font>")

    top = max(proposals, key=lambda p: float(p.get("confidence") or 0))
    rationale = top.get("rationale") or ""
    confidence = float(top.get("confidence") or 0)
    elements: list[dict] = [
        {"tag": "markdown", "content": _target_line(merged)},
    ]
    if item.get("kind") == "proposition_review":
        payload = item.get("payload") or {}
        stats = payload.get("stats") or {}
        if stats:
            elements.append(
                {
                    "tag": "markdown",
                    "content": (
                        f"基于 {stats.get('evidence_count', 0)} 条证据"
                        f"（支持 {stats.get('supports', 0)} / 反证 {stats.get('contradicts', 0)}）"
                        + (
                            f"；本次改动 +{stats.get('added', 0)} / -{stats.get('removed', 0)} 行"
                            if stats.get("added") or stats.get("removed")
                            else ""
                        )
                    ),
                }
            )
        if payload.get("base_url"):
            elements.append(
                {
                    "tag": "markdown",
                    "content": f"[在知识库中查看]({payload['base_url']})",
                }
            )
    else:
        elements.append({"tag": "markdown", "content": _paper_line(push)})
    elements.append({"tag": "markdown", "content": "\n\n".join(blocks)})
    evidence = _evidence_lines(push, proposals)
    if evidence:
        elements.append(
            {"tag": "markdown", "content": "**依据**\n" + "\n\n".join(evidence)}
        )
    if rationale:
        elements.append(
            {
                "tag": "markdown",
                "content": f"<font color='grey'>理由：{_short(rationale, 180)} · 置信度 {confidence:.1f}</font>",
            }
        )
    elements.append(_buttons(merged, proposal_ids))
    elements.append(
        {
            "tag": "markdown",
            "content": (
                (
                    "<font color='grey'>只处理这一项。采纳后立即写入知识库；"
                    "保持上一版则综述不变。答完这一题才会发下一题。</font>"
                    if item.get("kind") == "proposition_review"
                    else "<font color='grey'>只处理这一项。同意后立即写入知识库；"
                    "拒绝则保持原样。答完这一题才会发下一题。</font>"
                )
            ),
        }
    )

    return {
        "schema": "2.0",
        "config": {
            "update_multi": True,
            "width_mode": "default",
            "summary": {
                "content": clip(
                    f"知识更新 {index}/{total}：{_target_line(merged).replace('**', '').replace('`', '')}",
                    80,
                )
            },
        },
        "header": {
            "title": {
                "tag": "plain_text",
                "content": _header_title(merged.get("kind", ""), target_type, index, total),
            },
            "template": TEMPLATE.get(target_type, "yellow"),
            "icon": {"tag": "standard_icon", "token": "wiki-bitable_colorful"},
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 20px 12px",
            "vertical_spacing": "10px",
            "elements": elements,
        },
    }
