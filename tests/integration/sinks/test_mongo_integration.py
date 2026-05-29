"""Integration round-trip for MongoSink against a real MongoDB container.

Requires Docker. Skips cleanly when Docker (or the testcontainers/pymongo deps)
are unavailable, so it never breaks a laptop or container-less CI run.
"""

from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip('pymongo', reason='pymongo not installed — run: uv add yosoi[pymongo]')
testcontainers_mongodb = pytest.importorskip('testcontainers.mongodb', reason='testcontainers not installed')

from yosoi.sinks import ContentRecord, MongoSink

BASE = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(scope='module')
def mongo_uri():
    try:
        with testcontainers_mongodb.MongoDbContainer('mongo:7') as mongo:
            yield mongo.get_connection_url()
    except Exception as exc:  # noqa: BLE001 - Docker not available / pull failed
        pytest.skip(f'MongoDB container unavailable: {exc}')


async def test_mongo_roundtrip_by_url_and_time(mongo_uri):
    async with MongoSink(mongo_uri, database='yosoi_it', collection='content') as sink:
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
