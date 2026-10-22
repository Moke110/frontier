#!/usr/bin/env python3
"""Regenerate the update-question card samples under fixtures/update-cards/."""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from publisher.update_cards import build_update_card  # noqa: E402

SAMPLES = ROOT / "fixtures" / "update-cards"
FONT_RE = re.compile(r"</?font[^>]*>")


def _preview(card: dict) -> str:
    lines = [
        f"## {card['header']['title']['content']}",
        "",
    ]
    for element in card["body"]["elements"]:
        if element["tag"] == "markdown":
            lines.append(FONT_RE.sub("", element["content"]))
            lines.append("")
        elif element["tag"] == "column_set":
            labels = [
                column["elements"][0]["text"]["content"]
                for column in element["columns"]
            ]
            lines.append("`[ " + " ]  [ ".join(labels) + " ]`")
            lines.append("")
    return "\n".join(lines)


def _html(card: dict) -> str:
    def inline(text: str) -> str:
        text = text.replace("<font color='grey'>", "\x00grey\x00")
        text = text.replace("<font color='green'>", "\x00green\x00")
        text = text.replace("<font color='red'>", "\x00red\x00")
        text = text.replace("</font>", "\x00end\x00")
        text = html.escape(text)
        text = text.replace("\x00grey\x00", '<span class="muted">')
        text = text.replace("\x00green\x00", '<span class="added">')
        text = text.replace("\x00red\x00", '<span class="removed">')
        text = text.replace("\x00end\x00", "</span>")
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
        lines = []
        for line in text.splitlines():
            if line.startswith("&gt; "):
                lines.append(f"<blockquote>{line[5:]}</blockquote>")
            else:
                lines.append(line)
        return "<br>".join(lines)

    template = card["header"]["template"]
    body = []
    for element in card["body"]["elements"]:
        if element["tag"] == "markdown":
            body.append(f'<div class="md">{inline(element["content"])}</div>')
        elif element["tag"] == "column_set":
            buttons = []
            for column in element["columns"]:
                button = column["elements"][0]
                kind = "agree" if button["name"] == "agree_all" else "reject"
                buttons.append(
                    f'<div class="btn {kind}">{html.escape(button["text"]["content"])}</div>'
                )
            body.append('<div class="buttons">' + "".join(buttons) + "</div>")
    return (
        f'<section class="card {template}">'
        f'<header><div class="no">{html.escape(card["header"]["title"]["content"])}</div></header>'
        f'<div class="content">{"".join(body)}</div></section>'
    )


def _page(cards: list[tuple[int, dict]]) -> str:
    style = """
body{font-family:-apple-system,'PingFang SC','Noto Sans CJK SC',sans-serif;background:#f4f5f7;margin:0;padding:24px;color:#1f2329}
h1{font-size:20px;max-width:640px;margin:0 auto 8px}
.note{max-width:640px;margin:0 auto 20px;color:#646a73;font-size:13px}
.card{max-width:640px;margin:0 auto 20px;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08)}
header{padding:14px 18px;color:#fff}
.card.blue header{background:#3370ff}.card.violet header{background:#7f4bff}
.no{font-size:16px;font-weight:600}
.content{padding:14px 18px 18px;font-size:14px;line-height:1.65}
.md{margin-bottom:10px}.muted{color:#8f959e}.added{color:#2ea121}.removed{color:#d83931}
code{background:#f2f3f5;border-radius:4px;padding:1px 4px;font-size:12px}
blockquote{margin:6px 0;padding:6px 10px;border-left:3px solid #dee0e3;color:#4e5969;background:#fafbfc}
.buttons{display:flex;gap:10px;margin:14px 0 8px}
.btn{flex:1;text-align:center;border-radius:6px;padding:8px 0;font-weight:600}
.agree{background:#3370ff;color:#fff}.reject{background:#f54a45;color:#fff}
"""
    sections = "".join(_html(card) for _, card in sorted(cards, key=lambda row: row[0]))
    return (
        "<!doctype html><html lang='zh'><meta charset='utf-8'>"
        f"<title>更新题卡片样张</title><style>{style}</style><body>"
        "<h1>更新题卡片样张</h1>"
        "<div class='note'>非飞书真实渲染，仅用于确认信息密度、文案与证据展示。</div>"
        f"{sections}</body></html>"
    )


def main() -> int:
    push = json.loads((SAMPLES / "sample-push.json").read_text(encoding="utf-8"))
    previews = [
        "# 更新题卡片样张（由 `scripts/build_update_card_samples.py` 生成）",
        "",
        "每张卡只含一个实体；顶栏标题 = 类型 + 第 N / M 题；正文第一行是该实体的 id/title；按钮只有「同意全部 / 拒绝全部」。",
        "",
    ]
    cards = []
    for path in sorted(SAMPLES.glob("*.item.json")):
        item = json.loads(path.read_text(encoding="utf-8"))
        index, total = item.pop("_index"), item.pop("_total")
        card = build_update_card(push, item, index, total)
        target = path.with_name(path.name.replace(".item.json", ".card.json"))
        target.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        cards.append((index, card))
        print(f"wrote {target.relative_to(ROOT)}")
    for _, card in sorted(cards, key=lambda row: row[0]):
        previews.append(_preview(card))
    (SAMPLES / "preview.md").write_text("\n".join(previews), encoding="utf-8")
    print(f"wrote {(SAMPLES / 'preview.md').relative_to(ROOT)}")
    (SAMPLES / "preview.html").write_text(_page(cards), encoding="utf-8")
    print(f"wrote {(SAMPLES / 'preview.html').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
