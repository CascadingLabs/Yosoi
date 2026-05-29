"""Unit tests for the ContentRecord contract."""

from datetime import datetime, timezone

from yosoi.sinks import ContentRecord


def test_defaults_scraped_at_to_utc_now():
    rec = ContentRecord(url='https://example.com', content={'title': 'Hi'}, source='unit')
    assert rec.scraped_at.tzinfo is not None
    assert rec.scraped_at.utcoffset() == timezone.utc.utcoffset(None)


def test_accepts_dict_content():
    rec = ContentRecord(url='https://example.com', content={'title': 'Hi', 'price': 9.99}, source='unit')
    assert rec.content == {'title': 'Hi', 'price': 9.99}


def test_accepts_list_content_for_multi_item_pages():
    items = [{'title': 'A'}, {'title': 'B'}]
    rec = ContentRecord(url='https://example.com', content=items, source='unit')
    assert rec.content == items


def test_preserves_explicit_scraped_at():
    when = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    rec = ContentRecord(url='https://example.com', content={}, scraped_at=when, source='unit')
    assert rec.scraped_at == when
