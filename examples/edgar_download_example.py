"""Download a SEC EDGAR CSV flat file as a ys.File() field, then hand off to an agent.

What this does to your machine and the target site
---------------------------------------------------
- Opens a headless browser (VoidCrawl) and downloads ONE file from the page below into
  a per-run quarantine dir under ``.yosoi/downloads/`` (mode 0700, gitignored).
- The download only runs because BOTH safety gates are satisfied: ``allow_downloads=True``
  (the run-level opt-in, off by default) and ``allowed_types=['csv']`` (default-deny —
  a file whose magic bytes / content-type aren't CSV is rejected and the bytes purged).
- Be a good citizen with SEC EDGAR: honour their fair-access policy (declare a real
  User-Agent, keep request volume low). This example downloads a single file.

Where Yosoi stops (the boundary)
--------------------------------
Yosoi's job ends at *surfacing the content correctly*: a list of parsed CSV rows plus a
``DownloadRecord`` (path, sha256, size, content-type) for provenance. It does NOT analyse
the data. The actual research — e.g. loading the CSVs into in-process SQL (DuckDB/SQLite)
and asking questions — is a downstream concern for a Claude Code SDK agent. See the
``# DOWNSTREAM`` block at the bottom for the hand-off shape. No docling / RAG / embeddings.

Run:
    uv run python examples/edgar_download_example.py
"""

from __future__ import annotations

import asyncio

import yosoi as ys

# Point this at an EDGAR page that exposes a CSV download link, or set EDGAR_CSV_URL to a
# direct .csv flat-file URL. Kept as a constant so the example is an editable template
# rather than a hard dependency on one (possibly-rotated) SEC path.
EDGAR_PAGE = 'https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=10-K&output=atom'
EDGAR_CSV_URL = ''  # e.g. 'https://www.sec.gov/files/<some>.csv' — enables refetch mode below


class EdgarDataset(ys.Contract):
    """One EDGAR dataset: a label scraped from the page + a downloaded CSV's rows.

    ``rows`` is a ys.File() field — an action field, not a CSS selector. Yosoi downloads
    the file and the field's **declared type** decides what you get back (annotation-directed
    output): ``list[dict]`` here means "parse it into rows". Annotate ``Path`` for the file
    path, ``bytes`` for raw bytes, ``ys.DownloadRecord`` for the provenance handle, or
    ``list[MyRow]`` to get per-row validated models. ``allowed_types`` is the per-field
    allowlist; nothing downloads unless the bytes are really CSV.
    """

    title: str = ys.Title(description='The page or dataset title')

    # Safe default: retrigger mode — click the CSV download link and capture the result.
    # `list[dict]` ⇒ Yosoi parses the CSV into rows. No parse= knob — the type is the knob.
    rows: list[dict] = ys.File(
        trigger='a[href$=".csv"]',
        allowed_types=['csv'],
    )
    # Alternative (refetch mode) — download a known CSV URL directly. Swap in when you
    # have a stable EDGAR CSV link and set EDGAR_CSV_URL:
    #   rows: list[dict] = ys.File(url=EDGAR_CSV_URL, allowed_types=['csv'])


async def main() -> None:
    rows_records = await ys.scrape(
        EDGAR_PAGE,
        EdgarDataset,
        # Downloads need a browser tier; the simple HTTP tier can't capture a file.
        fetcher_type='headless',
        # Both gates required — opt-in + (run-wide ceiling intersected with the field's allowlist).
        allow_downloads=True,
        allowed_download_types=['csv'],
        quiet=False,
    )
    for record in rows_records:
        rows = record.get('rows') or []
        print(f'{record.get("title")!r}: {len(rows)} CSV rows surfaced')
        if rows:
            print('  first row:', rows[0])

    # DOWNSTREAM (not built in Yosoi): a Claude Code SDK agent picks the surfaced rows up
    # and runs the analysis with in-process SQL — Yosoi only fetched + parsed + verified.
    #
    #   import duckdb
    #   con = duckdb.connect()
    #   con.register('filings', rows_records[0]['rows'])  # list[dict] -> a SQL table
    #   con.sql("SELECT * FROM filings WHERE revenue > 1e9 ORDER BY revenue DESC").show()


if __name__ == '__main__':
    asyncio.run(main())
