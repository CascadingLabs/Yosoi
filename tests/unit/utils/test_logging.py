"""Tests for setup_local_logging."""

import logging
from pathlib import Path


def test_setup_local_logging_creates_log_file(tmp_path, monkeypatch):
    import yosoi.utils.logging as log_mod

    logs_dir = tmp_path / 'logs'
    monkeypatch.setattr(log_mod, 'get_logs_path', lambda: logs_dir)

    from yosoi.utils.logging import setup_local_logging

    log_file = setup_local_logging()
    assert isinstance(log_file, Path)
    assert log_file.exists()
    assert log_file.suffix == '.log'
    assert 'run_' in log_file.name

    # Cleanup: remove the file handler we added
    root = logging.getLogger()
    handlers_to_remove = [
        h for h in root.handlers if isinstance(h, logging.FileHandler) and str(log_file) in h.baseFilename
    ]
    for h in handlers_to_remove:
        root.removeHandler(h)
        h.close()


def test_setup_local_logging_all_level(tmp_path, monkeypatch):
    import yosoi.utils.logging as log_mod

    logs_dir = tmp_path / 'logs2'
    monkeypatch.setattr(log_mod, 'get_logs_path', lambda: logs_dir)

    from yosoi.utils.logging import setup_local_logging

    log_file = setup_local_logging(level='ALL')
    assert log_file.exists()

    root = logging.getLogger()
    handlers_to_remove = [
        h for h in root.handlers if isinstance(h, logging.FileHandler) and str(log_file) in h.baseFilename
    ]
    for h in handlers_to_remove:
        root.removeHandler(h)
        h.close()
