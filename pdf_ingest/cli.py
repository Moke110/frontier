"""CLI: ``python -m pdf_ingest.cli run --manifest <path> [--limit N] [--dry-run]``."""

from pdf_ingest.ingest import main

if __name__ == "__main__":
    raise SystemExit(main())
