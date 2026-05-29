"""Integration round-trip for PostgresSink against a real Postgres.

Prefers an already-running instance via ``YOSOI_TEST_POSTGRES_DSN`` (e.g. the
``docker-compose.sinks.yml`` stack); otherwise spins up an ephemeral
testcontainers instance. Skips cleanly when neither a DSN nor Docker is
available, so it never breaks a laptop or container-less CI run.

Each test uses a unique table and drops it afterwards, so runs stay isolated
and idempotent even against the persistent compose stack.
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip('psycopg', reason='psycopg not installed — run: uv add yosoi[psycopg]')

from yosoi.sinks import ContentRecord, PostgresSink

BASE = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(scope='module')
def conninfo():
    dsn = os.getenv('YOSOI_TEST_POSTGRES_DSN')
    if dsn:
        yield dsn
        return
    testcontainers_postgres = pytest.importorskip('testcontainers.postgres', reason='testcontainers not installed')
    try:
        with testcontainers_postgres.PostgresContainer('postgres:16-alpine') as pg:
            yield pg.get_connection_url(driver=None)
    except Exception as exc:  # noqa: BLE001 - Docker not available / pull failed
        pytest.skip(f'Postgres unavailable: set YOSOI_TEST_POSTGRES_DSN or start Docker ({exc})')


@pytest.fixture
async def sink(conninfo):
    table = f'content_test_{uuid.uuid4().hex}'  # uuid hex is a safe SQL identifier
    try:
        async with PostgresSink(conninfo, table=table) as sink:
            yield sink
    finally:
        import psycopg

        async with await psycopg.AsyncConnection.connect(conninfo, autocommit=True) as cleanup:
            await cleanup.execute(f'DROP TABLE IF EXISTS {table}')


async def test_postgres_roundtrip_by_url_and_time(sink):
    await sink.write(ContentRecord(url='https://x.com/a', content={'v': 1}, scraped_at=BASE, source='it'))
    await sink.write(
        ContentRecord(url='https://x.com/a', content={'v': 2}, scraped_at=BASE + timedelta(hours=1), source='it')
    )
    await sink.write(
        ContentRecord(url='https://x.com/b', content=[{'k': 1}], scraped_at=BASE + timedelta(days=3), source='it')
    )

    by_url = await sink.read_by_url('https://x.com/a')
    assert [r.content['v'] for r in by_url] == [2, 1]  # append-only, newest-first

    by_time = await sink.read_by_time(BASE + timedelta(days=1))
    assert [r.url for r in by_time] == ['https://x.com/b']
    assert by_time[0].content == [{'k': 1}]
