"""Card payload builders for the publisher prototype (Card 2.0)."""

from __future__ import annotations

from common import clip

VERDICT_LABEL = {"irrelevant": "不相关", "ok": "一般", "great": "很好"}
ACTION_VERDICT = {"score_low": "irrelevant", "score_mid": "ok", "score_high": "great"}


def _button(name: str, text: str, submit: bool = True, kind: str = "default") -> dict:
    button = {
        "tag": "button",
        "name": name,
        "text": {"tag": "plain_text", "content": text},
        "type": kind,
        "size": "medium",
        "width": "fill",
    }
    if submit:
        button["form_action_type"] = "submit"
    return button


def build_rating_card(push: dict) -> dict:
    body_md = push.get("body_md") or ""
    return {
        "schema": "2.0",
        "config": {
            "update_multi": True,
            "width_mode": "default",
            "summary": {"content": clip(push.get("title", "推送反馈"), 80)},
        },
        "header": {
            "title": {"tag": "plain_text", "content": clip(push.get("title", "今日推送"), 60)},
            "subtitle": {
                "tag": "plain_text",
                "content": f"{push.get('date', '')} · checkpoint {push.get('checkpoint_id', '')}",
            },
            "template": "blue",
            "icon": {"tag": "standard_icon", "token": "vote_colorful"},
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 20px 12px",
            "vertical_spacing": "12px",
            "elements": [
                {"tag": "markdown", "content": clip(body_md, 2500)},
                {
                    "tag": "form",
                    "name": "feedback_form",
                    "vertical_spacing": "12px",
                    "elements": [
                        {
                            "tag": "input",
                            "name": "comment",
                            "label": {"tag": "plain_text", "content": "评语（可选）"},
                            "placeholder": {
                                "tag": "plain_text",
                                "content": "哪里有用，或者哪里不对？一句话即可",
                            },
                            "input_type": "multiline_text",
                            "rows": 2,
                            "auto_resize": True,
                            "max_length": 200,
                            "width": "fill",
                        },
                        {
                            "tag": "column_set",
                            "flex_mode": "none",
                            "horizontal_spacing": "8px",
                            "columns": [
                                {
                                    "tag": "column",
                                    "width": "weighted",
                                    "weight": 1,
                                    "elements": [_button("score_low", "不相关")],
                                },
                                {
                                    "tag": "column",
                                    "width": "weighted",
                                    "weight": 1,
                                    "elements": [_button("score_mid", "一般")],
                                },
                                {
                                    "tag": "column",
                                    "width": "weighted",
                                    "weight": 1,
                                    "elements": [_button("score_high", "很好")],
                                },
                            ],
                        },
                    ],
                },
                {
                    "tag": "markdown",
                    "content": "<font color='grey'>点一下即提交，评语空着也能提交</font>",
                },
            ],
        },
    }


def build_confirmation_card(push: dict, verdict: str, comment: str) -> dict:
    green = verdict in ("ok", "great")
    return {
        "schema": "2.0",
        "config": {
            "update_multi": True,
            "width_mode": "default",
            "summary": {"content": f"反馈已记录：{VERDICT_LABEL.get(verdict, verdict)}"},
        },
        "header": {
            "title": {"tag": "plain_text", "content": "反馈已记录"},
            "subtitle": {
                "tag": "plain_text",
                "content": f"{push.get('date', '')} · 感谢你的评价",
            },
            "template": "green" if green else "grey",
            "icon": {"tag": "standard_icon", "token": "todo_colorful"},
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 20px 12px",
            "vertical_spacing": "12px",
            "elements": [
                {
                    "tag": "column_set",
                    "flex_mode": "none",
                    "horizontal_spacing": "8px",
                    "columns": [
                        {
                            "tag": "column",
                            "width": "weighted",
                            "weight": 1,
                            "background_style": "green-50" if green else "grey-50",
                            "padding": "8px 12px",
                            "elements": [
                                {
                                    "tag": "markdown",
                                    "content": f"<font color='grey'>评价</font>\n**{VERDICT_LABEL.get(verdict, verdict)}**",
                                }
                            ],
                        },
                        {
                            "tag": "column",
                            "width": "weighted",
                            "weight": 2,
                            "background_style": "blue-50",
                            "padding": "8px 12px",
                            "elements": [
                                {
                                    "tag": "markdown",
                                    "content": f"<font color='grey'>评语</font>\n{comment or '未填写'}",
                                }
                            ],
                        },
                    ],
                },
                {
                    "tag": "markdown",
                    "content": "感谢，你的反馈会用于调整后续检索与排序。",
                },
            ],
        },
    }


def _describe(proposal: dict) -> str:
    kind = proposal.get("kind")
    target = proposal.get("target_id") or ""
    value = (proposal.get("diff") or {}).get("value") or {}
    if kind == "add_evidence":
        note = value.get("note", "") if isinstance(value, dict) else ""
        return f"给命题 `{target}` 补一条证据：{clip(str(note), 80)}"
    if kind == "add_alias":
        alias = value if isinstance(value, str) else value.get("alias", "")
        return f"给知识卡 `{target}` 增加别名：**{alias}**"
    if kind == "add_proposition":
        text = value.get("text", "") if isinstance(value, dict) else str(value)
        return f"新建命题：{clip(text, 120)}"
    if kind == "update_summary":
        return f"更新 `{target}` 的摘要"
    return f"{kind} → {target}"


def build_approval_card(push: dict, proposals: list[dict]) -> dict:
    lines = [f"推送 `{push.get('push_id')}` 提供了可更新知识库的信息：", ""]
    for index, proposal in enumerate(proposals, start=1):
        lines.append(f"**{index}.** {_describe(proposal)}")
        lines.append(f"　<font color='grey'>{proposal.get('rationale', '')} · 置信度 {proposal.get('confidence', 0)}</font>")
    ids = [p["proposal_id"] for p in proposals]
    return {
        "schema": "2.0",
        "config": {
            "update_multi": True,
            "width_mode": "default",
            "summary": {"content": "知识更新待确认"},
        },
        "header": {
            "title": {"tag": "plain_text", "content": "知识更新待确认"},
            "subtitle": {"tag": "plain_text", "content": f"来自 {push.get('push_id', '')}"},
            "template": "yellow",
            "icon": {"tag": "standard_icon", "token": "wiki-bitable_colorful"},
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 20px 12px",
            "vertical_spacing": "12px",
            "elements": [
                {"tag": "markdown", "content": "\n".join(lines)},
                {
                    "tag": "column_set",
                    "flex_mode": "none",
                    "horizontal_spacing": "8px",
                    "columns": [
                        {
                            "tag": "column",
                            "width": "weighted",
                            "weight": 1,
                            "elements": [
                                {
                                    "tag": "button",
                                    "name": "approve",
                                    "text": {"tag": "plain_text", "content": "同意"},
                                    "type": "primary_filled",
                                    "width": "fill",
                                    "behaviors": [
                                        {
                                            "type": "callback",
                                            "value": {"proposal_ids": ids, "decision": "approve"},
                                        }
                                    ],
                                }
                            ],
                        },
                        {
                            "tag": "column",
                            "width": "weighted",
                            "weight": 1,
                            "elements": [
                                {
                                    "tag": "button",
                                    "name": "reject",
                                    "text": {"tag": "plain_text", "content": "拒绝"},
                                    "type": "danger",
                                    "width": "fill",
                                    "behaviors": [
                                        {
                                            "type": "callback",
                                            "value": {"proposal_ids": ids, "decision": "reject"},
                                        }
                                    ],
                                }
                            ],
                        },
                    ],
                },
                {
                    "tag": "markdown",
                    "content": "<font color='grey'>同意后由 archive 写入知识图 / 命题列表；拒绝则丢弃本次提议。</font>",
                },
            ],
        },
    }


def build_decision_card(decision: str, count: int) -> dict:
    approved = decision == "approve"
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "width_mode": "default"},
        "header": {
            "title": {"tag": "plain_text", "content": "已采纳" if approved else "已拒绝"},
            "subtitle": {"tag": "plain_text", "content": f"{count} 条知识更新"},
            "template": "green" if approved else "grey",
            "icon": {"tag": "standard_icon", "token": "todo_colorful"},
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 20px 12px",
            "elements": [
                {
                    "tag": "markdown",
                    "content": "更新已写入知识库。" if approved else "本次更新已丢弃，知识库保持不变。",
                }
            ],
        },
    }
