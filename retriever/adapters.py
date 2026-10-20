"""Source adapters for the retriever prototype.

Every adapter returns the same dict shape: source, source_id, title, abstract,
authors, journal, published, url, is_preprint.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from common import read_json

BLACKLIST = ("poster", "abstracts", "proceedings", "erratum", "correction", "retraction")


class RetrieverError(RuntimeError):
    pass


def _matches(terms: list[str], text: str) -> bool:
    low = (text or "").lower()
    return any(t.lower() in low for t in terms)


def _blocked(title: str) -> bool:
    low = (title or "").lower()
    return any(word in low for word in BLACKLIST)


def fetch_fixture(query: dict, fixtures: Path) -> list[dict]:
    out = []
    for path in sorted(Path(fixtures).glob("*.json")):
        rec = read_json(path) or {}
        if _blocked(rec.get("title", "")):
            continue
        if not _matches(query["terms"], f"{rec.get('title','')} {rec.get('abstract','')}"):
            continue
        rec = {k: v for k, v in rec.items() if k != "schema_version"}
        rec.setdefault("source", "fixture")
        rec.setdefault("source_id", path.stem)
        out.append(rec)
    return out


def fetch_arxiv(query: dict, limit: int, timeout: int = 30) -> list[dict]:
    params = urllib.parse.urlencode(
        {
            "search_query": query["query"],
            "start": 0,
            "max_results": limit,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
    )
    url = f"https://export.arxiv.org/api/query?{params}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read()
    except Exception as exc:  # noqa: BLE001 - prototype: surface as source failure
        raise RetrieverError(f"arxiv request failed: {exc}") from exc
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(body)
    out = []
    for entry in root.findall("a:entry", ns):
        ident = (entry.findtext("a:id", default="", namespaces=ns) or "").rsplit("/", 1)[-1]
        out.append(
            {
                "source": "arxiv",
                "source_id": ident,
                "title": " ".join((entry.findtext("a:title", default="", namespaces=ns) or "").split()),
                "abstract": " ".join((entry.findtext("a:summary", default="", namespaces=ns) or "").split()),
                "authors": [a.findtext("a:name", default="", namespaces=ns) for a in entry.findall("a:author", ns)],
                "journal": "arXiv",
                "published": (entry.findtext("a:published", default="", namespaces=ns) or "")[:10],
                "url": f"https://arxiv.org/abs/{ident}",
                "is_preprint": True,
            }
        )
    return out


def fetch_europepmc(query: dict, limit: int, timeout: int = 30) -> list[dict]:
    params = urllib.parse.urlencode(
        {"query": query["query"], "format": "json", "pageSize": limit, "resultType": "core"}
    )
    url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?{params}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            payload = json.loads(resp.read())
    except Exception as exc:  # noqa: BLE001
        raise RetrieverError(f"europepmc request failed: {exc}") from exc
    out = []
    for item in (payload.get("resultList") or {}).get("result", []):
        title = item.get("title") or ""
        if _blocked(title):
            continue
        src = item.get("source") or "MED"
        ident = item.get("pmid") or item.get("id")
        out.append(
            {
                "source": "europepmc",
                "source_id": str(ident),
                "title": title,
                "abstract": item.get("abstractText") or "",
                "authors": [a.strip() for a in (item.get("authorString") or "").split(",") if a.strip()],
                "journal": item.get("journalTitle") or src,
                "published": item.get("firstPublicationDate") or "",
                "url": f"https://europepmc.org/article/{src}/{item.get('id')}",
                "is_preprint": src == "PPR",
                "pmcid": item.get("pmcid") or "",
                "doi": item.get("doi") or "",
            }
        )
    return out


def fetch(query: dict, mode: str, fixtures: Path) -> list[dict]:
    if mode == "fixture":
        return fetch_fixture(query, fixtures)
    if query["source"] == "arxiv":
        return fetch_arxiv(query, int(query.get("limit", 20)))
    if query["source"] == "europepmc":
        return fetch_europepmc(query, int(query.get("limit", 20)))
    raise RetrieverError(f"unknown source: {query['source']}")
