"""Pluggable, append-only content sinks for extracted content.

Exposes a narrow :class:`ContentSink` interface and three backends — SQLite
(stdlib), PostgreSQL, and MongoDB. Importing this package pulls in only the
interface and the record contract; database drivers are imported lazily inside
each backend and fail with a helpful message if the matching extra is missing.

Example::

    from yosoi.sinks import ContentRecord, SqliteSink

    async with SqliteSink('.yosoi/content.db') as sink:
        await sink.write(ContentRecord(url='https://x.com', content={'title': 'Hi'}, source='demo'))
        history = await sink.read_by_url('https://x.com')
"""

from yosoi.sinks.base import ContentSink
from yosoi.sinks.mongo import MongoSink
from yosoi.sinks.postgres import PostgresSink
from yosoi.sinks.record import ContentRecord
from yosoi.sinks.sqlite import SqliteSink

__all__ = [
    'ContentRecord',
    'ContentSink',
    'MongoSink',
    'PostgresSink',
    'SqliteSink',
]
