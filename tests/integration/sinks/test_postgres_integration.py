"""Integration round-trip for PostgresSink against a real Postgres container.

Requires Docker. Skips cleanly when Docker (or the testcontainers/psycopg deps)
are unavailable, so it never breaks a laptop or container-less CI run.
"""

from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip('psycopg', reason='psycopg not installed — run: uv add yosoi[psycopg]')
testcontainers_postgres = pytest.importorskip('testcontainers.postgres', reason='testcontainers not installed')

from yosoi.sinks import ContentRecord, PostgresSink

BASE = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(scope='module')
def conninfo():
    try:
        with testcontainers_postgres.PostgresContainer('postgres:16-alpine') as pg:
            yield pg.get_connection_url(driver=None)
    except Exception as exc:  # noqa: BLE001 - Docker not available / pull failed
        pytest.skip(f'Postgres container unavailable: {exc}')


async def test_postgres_roundtrip_by_url_and_time(conninfo):
    async with PostgresSink(conninfo) as sink:
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
