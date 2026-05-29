"""Unit tests for SqliteSink — full round-trip against a real (stdlib) SQLite file."""

from datetime import datetime, timedelta, timezone

import pytest

from yosoi.sinks import ContentRecord, SqliteSink

BASE = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def sink(tmp_path):
    return SqliteSink(tmp_path / 'content.db')


async def test_write_then_read_by_url(sink):
    rec = ContentRecord(url='https://x.com/a', content={'title': 'Hello'}, scraped_at=BASE, source='unit')
    await sink.write(rec)

    got = await sink.read_by_url('https://x.com/a')
    assert len(got) == 1
    assert got[0].url == 'https://x.com/a'
    assert got[0].content == {'title': 'Hello'}
    assert got[0].scraped_at == BASE
    assert got[0].source == 'unit'


async def test_append_only_keeps_every_version_newest_first(sink):
    older = ContentRecord(url='https://x.com/a', content={'v': 1}, scraped_at=BASE, source='unit')
    newer = ContentRecord(url='https://x.com/a', content={'v': 2}, scraped_at=BASE + timedelta(hours=1), source='unit')
    await sink.write(older)
    await sink.write(newer)

    got = await sink.read_by_url('https://x.com/a')
    assert [r.content['v'] for r in got] == [2, 1]  # newest first, nothing overwritten


async def test_read_by_url_isolates_urls(sink):
    await sink.write(ContentRecord(url='https://x.com/a', content={}, scraped_at=BASE, source='unit'))
    await sink.write(ContentRecord(url='https://x.com/b', content={}, scraped_at=BASE, source='unit'))

    assert len(await sink.read_by_url('https://x.com/a')) == 1
    assert await sink.read_by_url('https://x.com/missing') == []


async def test_read_by_time_inclusive_range(sink):
    for i in range(4):
        await sink.write(
            ContentRecord(
                url=f'https://x.com/{i}', content={'i': i}, scraped_at=BASE + timedelta(days=i), source='unit'
            )
        )

    got = await sink.read_by_time(BASE + timedelta(days=1), BASE + timedelta(days=2))
    assert sorted(r.content['i'] for r in got) == [1, 2]


async def test_read_by_time_open_ended(sink):
    await sink.write(ContentRecord(url='https://x.com/old', content={}, scraped_at=BASE, source='unit'))
    await sink.write(
        ContentRecord(url='https://x.com/new', content={}, scraped_at=BASE + timedelta(days=10), source='unit')
    )

    got = await sink.read_by_time(BASE + timedelta(days=5))
    assert [r.url for r in got] == ['https://x.com/new']


async def test_naive_datetime_treated_as_utc(sink):
    naive = datetime(2026, 5, 1, 12, 0, 0)  # no tzinfo
    await sink.write(ContentRecord(url='https://x.com/a', content={}, scraped_at=naive, source='unit'))

    got = await sink.read_by_time(BASE - timedelta(minutes=1), BASE + timedelta(minutes=1))
    assert len(got) == 1


async def test_list_content_roundtrips(sink):
    items = [{'title': 'A'}, {'title': 'B'}]
    await sink.write(ContentRecord(url='https://x.com/list', content=items, scraped_at=BASE, source='unit'))

    got = await sink.read_by_url('https://x.com/list')
    assert got[0].content == items


async def test_usable_as_async_context_manager(tmp_path):
    async with SqliteSink(tmp_path / 'cm.db') as sink:
        await sink.write(ContentRecord(url='https://x.com/a', content={}, scraped_at=BASE, source='unit'))
        assert len(await sink.read_by_url('https://x.com/a')) == 1
