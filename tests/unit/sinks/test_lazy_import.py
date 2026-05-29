"""Lazy-import behaviour and Protocol conformance for the sink backends.

Drivers are optional extras. A missing driver must surface a helpful
``install yosoi[...]`` message, not a raw ImportError, and only when the backend
is actually constructed — importing the module must stay driver-free.
"""

import sys

import pytest

from yosoi.sinks import ContentSink, MongoSink, PostgresSink, SqliteSink
from yosoi.sinks._internal import MissingSinkDependencyError


def test_sqlite_satisfies_content_sink_protocol():
    assert isinstance(SqliteSink(':memory:'), ContentSink)


def test_postgres_missing_driver_gives_helpful_message(monkeypatch):
    # Setting the module to None makes `import psycopg` raise ImportError.
    monkeypatch.setitem(sys.modules, 'psycopg', None)
    with pytest.raises(MissingSinkDependencyError, match=r'yosoi\[psycopg\]'):
        PostgresSink('postgresql://localhost/db')


def test_mongo_missing_driver_gives_helpful_message(monkeypatch):
    monkeypatch.setitem(sys.modules, 'pymongo', None)
    with pytest.raises(MissingSinkDependencyError, match=r'yosoi\[pymongo\]'):
        MongoSink('mongodb://localhost:27017')


def test_missing_dependency_error_is_an_import_error():
    # Existing `except ImportError` handlers keep working.
    assert issubclass(MissingSinkDependencyError, ImportError)
