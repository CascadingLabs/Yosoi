"""Integration round-trip for MongoSink against a real MongoDB.

Prefers an already-running instance via ``YOSOI_TEST_MONGO_URI`` (e.g. the
``docker-compose.sinks.yml`` stack); otherwise spins up an ephemeral
testcontainers instance. Skips cleanly when neither a URI nor Docker is
available, so it never breaks a laptop or container-less CI run.

Each test uses a unique database and drops it afterwards, so runs stay isolated
and idempotent even against the persistent compose stack.
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip('pymongo', reason='pymongo not installed — run: uv add yosoi[pymongo]')

from yosoi.sinks import ContentRecord, MongoSink

BASE = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(scope='module')
def mongo_uri():
    uri = os.getenv('YOSOI_TEST_MONGO_URI')
    if uri:
        yield uri
        return
    testcontainers_mongodb = pytest.importorskip('testcontainers.mongodb', reason='testcontainers not installed')
    try:
        with testcontainers_mongodb.MongoDbContainer('mongo:7') as mongo:
            yield mongo.get_connection_url()
    except Exception as exc:  # noqa: BLE001 - Docker not available / pull failed
        pytest.skip(f'MongoDB unavailable: set YOSOI_TEST_MONGO_URI or start Docker ({exc})')


@pytest.fixture
async def sink(mongo_uri):
    db_name = f'yosoi_it_{uuid.uuid4().hex}'
    try:
        async with MongoSink(mongo_uri, database=db_name, collection='content') as sink:
            yield sink
    finally:
        from pymongo import AsyncMongoClient

        client: AsyncMongoClient = AsyncMongoClient(mongo_uri)
        try:
            await client.drop_database(db_name)
        finally:
            await client.close()


async def test_mongo_roundtrip_by_url_and_time(sink):
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
