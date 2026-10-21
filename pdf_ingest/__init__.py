"""PDF ingestion: manifest -> archive raw metadata + text + page anchors.

Parsing lives here; only ``archive`` writes ``$KL_HOME/archive``.
"""

from pdf_ingest.ingest import (  # noqa: F401
    PAGE_SEP,
    paper_id_for,
    source_id_for,
    build_text_and_anchors,
    run,
)
from pdf_ingest.anchors import locate_quote, normalize  # noqa: F401
