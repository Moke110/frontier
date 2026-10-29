"""Retriever: one source failure must not hide the others."""

from retriever import adapters, cli


def _plan():
    return {
        "window": {"start": "2026-10-23", "end": "2026-10-29"},
        "queries": [
            {
                "query_id": "q1",
                "checkpoint_id": "card_x",
                "source": "arxiv",
                "query": "x",
                "terms": ["x"],
            },
            {
                "query_id": "q2",
                "checkpoint_id": "card_x",
                "source": "europepmc",
                "query": "x",
                "terms": ["x"],
            },
        ],
    }


def test_one_failed_source_does_not_hide_the_other(monkeypatch, tmp_path):
    def fake_fetch(query, mode, fixtures):
        if query["source"] == "arxiv":
            raise adapters.RetrieverError("arxiv request failed: HTTP Error 429")
        return [
            {
                "source": "europepmc",
                "source_id": "42",
                "title": "A paper",
                "abstract": "about x",
                "published": "2026-10-28",
            }
        ]

    monkeypatch.setattr(cli, "fetch", fake_fetch)
    errors = []

    rows = cli.run(_plan(), "live", tmp_path, errors=errors)

    assert len(rows) == 1
    assert rows[0]["source"] == "europepmc"
    assert rows[0]["retrieval"]["query_id"] == "q2"
    assert errors == [
        {
            "query_id": "q1",
            "source": "arxiv",
            "error": "arxiv request failed: HTTP Error 429",
        }
    ]
