"""Fetch figures for a selected paper, with a deterministic generated fallback.

Europe PMC OA figures come from the full-text XML; arXiv figures come from the
HTML rendering. Every asset is stored locally next to the push so the PDF
renderer never fetches anything at render time. If no source figure can be
retrieved, a generated SVG "visual abstract" is produced instead; captions always
state which kind it is.
"""

from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from common import clip

USER_AGENT = "frontier/0.1 (personal research assistant)"
MAX_BYTES = 20 * 1024 * 1024
XLINK = "{http://www.w3.org/1999/xlink}href"


class FigureError(RuntimeError):
    pass


def _get(url: str, timeout: int = 30) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise FigureError(f"figure too large: {url}")
        return data, response.headers.get("Content-Type", "")


def _extension(content_type: str, url: str) -> str:
    low = (content_type or "").lower()
    if "svg" in low:
        return ".svg"
    if "png" in low:
        return ".png"
    if "jpeg" in low or "jpg" in low:
        return ".jpg"
    if "gif" in low:
        return ".gif"
    if "webp" in low:
        return ".webp"
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    return suffix if suffix in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg") else ".png"


def _save(data: bytes, content_type: str, url: str, dest_stem: Path) -> Path:
    dest = dest_stem.with_suffix(_extension(content_type, url))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return " ".join(html.unescape(text).split())


def _europepmc(paper: dict, limit: int) -> list[dict]:
    pmcid = paper.get("pmcid")
    if not pmcid:
        return []
    url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
    data, _ = _get(url)
    root = ET.fromstring(data)
    out = []
    for fig in root.iter("fig"):
        graphic = fig.find(".//graphic")
        if graphic is None:
            continue
        href = graphic.get(XLINK) or graphic.get("href")
        if not href:
            continue
        caption_node = fig.find("caption")
        caption = _clean("".join(caption_node.itertext())) if caption_node is not None else ""
        label = _clean(fig.findtext("label") or "")
        caption = f"{label}. {caption}".strip(". ") if label else caption
        image_url = f"https://europepmc.org/articles/{pmcid}/bin/{href}"
        out.append(
            {
                "url": image_url,
                "caption": clip(caption or f"{pmcid} figure", 400),
                "origin": "paper",
            }
        )
        if len(out) >= limit:
            break
    return out


def _arxiv_pdf(paper: dict, limit: int) -> list[dict]:
    """Crop figure regions from the PDF when the HTML rendering is unavailable."""
    ident = str(paper.get("source_id") or "").strip()
    if not ident:
        return []
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return []
    data, _ = _get(f"https://arxiv.org/pdf/{ident}", timeout=60)
    doc = fitz.open(stream=data, filetype="pdf")
    out: list[dict] = []
    for page in doc:
        blocks = page.get_text("blocks")
        captions = [
            block
            for block in blocks
            if re.match(r"^\s*(?:Fig\.?|Figure)\s*\d+", block[4] or "", re.IGNORECASE)
        ]
        for cap in captions:
            if len(out) >= limit:
                return out
            x0, y0, x1, y1 = [float(v) for v in cap[:4]]
            caption = _clean(cap[4])
            wide = (x1 - x0) > page.rect.width * 0.55
            left = page.rect.width * 0.5
            if wide:
                clip_x0, clip_x1 = 36.0, page.rect.width - 36.0
            elif x0 < left:
                clip_x0, clip_x1 = 36.0, left - 12.0
            else:
                clip_x0, clip_x1 = left + 12.0, page.rect.width - 36.0

            # Prefer the vector-drawing bbox (charts); otherwise use the space
            # above the caption (full-width figures).
            drawings = [
                d["rect"]
                for d in page.get_drawings()
                if d["rect"].x0 >= clip_x0 - 4
                and d["rect"].x1 <= clip_x1 + 4
                and d["rect"].y1 < y0
            ]
            if drawings:
                box = fitz.Rect(drawings[0])
                for rect in drawings[1:]:
                    box |= rect
                top = max(36.0, box.y0 - 10)
                bottom = min(y0 - 2, box.y1 + 10)
            else:
                top = max(36.0, y0 - 300)
                bottom = y0 - 2
            if bottom - top < 40:
                continue
            clip = fitz.Rect(clip_x0, top, clip_x1, bottom)
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=clip, alpha=False)
            out.append(
                {
                    "data": pix.tobytes("png"),
                    "content_type": "image/png",
                    "caption": caption if len(caption) > 20 else f"原文图（PDF 第 {page.number + 1} 页）",
                    "origin": "paper",
                    "origin_url": f"https://arxiv.org/pdf/{ident}#page={page.number + 1}",
                }
            )
    return out


def _arxiv(paper: dict, limit: int) -> list[dict]:
    ident = str(paper.get("source_id") or "").strip()
    if not ident:
        return []
    html_text = ""
    for base in (f"https://arxiv.org/html/{ident}", f"https://ar5iv.labs.arxiv.org/html/{ident}"):
        try:
            data, content_type = _get(base)
            if "html" in (content_type or "").lower() or b"<html" in data[:2000].lower():
                html_text = data.decode("utf-8", errors="replace")
                break
        except Exception:  # noqa: BLE001 - try the next mirror
            continue
    if not html_text:
        return []

    out = []
    for block in re.findall(r"<figure\b.*?</figure>", html_text, flags=re.S | re.I):
        img = re.search(r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"']", block, flags=re.I)
        if not img:
            continue
        src = img.group(1)
        low = src.lower()
        if any(bad in low for bad in ("logo", "icon", "badge", "data:image")):
            continue
        if not re.search(r"\.(png|jpe?g|gif|webp)(\?|$)", low):
            continue
        caption_match = re.search(r"<figcaption\b[^>]*>(.*?)</figcaption>", block, flags=re.S | re.I)
        caption = _clean(caption_match.group(1)) if caption_match else ""
        out.append(
            {
                "url": urllib.parse.urljoin(base + "/", src),
                "caption": clip(caption or f"arXiv {ident} figure", 400),
                "origin": "paper",
            }
        )
        if len(out) >= limit:
            break
    return out


def _wrap(text: str, width: int = 24, max_lines: int = 4) -> list[str]:
    text = " ".join((text or "").split())
    lines, current, score = [], "", 0
    for char in text:
        weight = 2 if ord(char) > 127 else 1
        if score + weight > width * 2:
            lines.append(current)
            current, score = "", 0
            if len(lines) >= max_lines:
                break
        current += char
        score += weight
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and len("".join(lines)) < len(text):
        lines[-1] = lines[-1][: max(0, len(lines[-1]) - 1)] + "…"
    return lines or ["前沿论文"]


def _fallback_svg(paper: dict, push_id: str) -> str:
    title = paper.get("title") or paper.get("paper_id") or "未命名论文"
    lines = _wrap(title)
    tspans = "\n".join(
        f'    <tspan x="72" dy="{0 if i == 0 else 64}">{html.escape(line)}</tspan>'
        for i, line in enumerate(lines)
    )
    source = paper.get("journal") or paper.get("source") or ""
    date = paper.get("published") or ""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="675" viewBox="0 0 1200 675">
  <rect width="1200" height="675" fill="#0f4c5c"/>
  <rect x="0" y="0" width="14" height="675" fill="#e36414"/>
  <text x="72" y="98" fill="#e36414" font-family="Noto Sans CJK SC, sans-serif" font-size="26" font-weight="700" letter-spacing="4">FRONTIER · VISUAL ABSTRACT</text>
  <text x="72" y="220" fill="#ffffff" font-family="Noto Serif CJK SC, serif" font-size="54" font-weight="700">
{tspans}
  </text>
  <text x="72" y="560" fill="#cfe3e7" font-family="Noto Sans CJK SC, sans-serif" font-size="26">{html.escape(clip(source, 60))} · {html.escape(date)}</text>
  <text x="72" y="612" fill="#9fc3ca" font-family="Noto Sans CJK SC, sans-serif" font-size="22">生成示意图：用于版式与定位，不是论文原图</text>
</svg>
"""


def fetch_for_paper(
    paper: dict,
    push_id: str,
    out_dir: Path,
    limit: int = 3,
) -> list[dict]:
    """Return local assets for one paper. Never raises on network failure."""
    out_dir = Path(out_dir)
    asset_dir = out_dir / "assets" / push_id
    asset_dir.mkdir(parents=True, exist_ok=True)

    candidates: list[dict] = []
    try:
        source = paper.get("source")
        if source == "europepmc":
            candidates = _europepmc(paper, limit)
        elif source == "arxiv":
            candidates = _arxiv(paper, limit)
            if not candidates:
                candidates = _arxiv_pdf(paper, limit)
    except Exception:  # noqa: BLE001 - fall back to a generated visual
        candidates = []

    assets: list[dict] = []
    for index, candidate in enumerate(candidates[:limit], start=1):
        try:
            if candidate.get("data"):
                data, content_type = candidate["data"], candidate["content_type"]
            else:
                data, content_type = _get(candidate["url"])
            path = _save(
                data,
                content_type,
                candidate.get("origin_url") or candidate.get("url", ""),
                asset_dir / f"fig-{index}",
            )
        except Exception:  # noqa: BLE001 - skip a broken figure, try the next
            continue
        assets.append(
            {
                "id": f"fig-{index}",
                "path": str(path.relative_to(out_dir)),
                "caption": candidate["caption"],
                "source": "paper",
                "origin_url": candidate.get("origin_url") or candidate.get("url", ""),
            }
        )

    if not assets:
        svg = _fallback_svg(paper, push_id)
        path = asset_dir / "fig-1.svg"
        path.write_text(svg, encoding="utf-8")
        assets.append(
            {
                "id": "fig-1",
                "path": str(path.relative_to(out_dir)),
                "caption": f"研究定位示意：{clip(paper.get('title') or '', 120)}",
                "source": "generated",
                "origin_url": "",
            }
        )

    for index, asset in enumerate(assets, start=1):
        asset["id"] = f"fig-{index}"
    return assets
