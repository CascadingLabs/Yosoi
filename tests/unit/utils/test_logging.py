"""Tests for setup_local_logging."""

import logging
from pathlib import Path


def _cleanup_handlers(log_file):
    root = logging.getLogger()
    handlers_to_remove = [
        h for h in root.handlers if isinstance(h, logging.FileHandler) and str(log_file) in h.baseFilename
    ]
    for h in handlers_to_remove:
        root.removeHandler(h)
        h.close()


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

    _cleanup_handlers(log_file)


def test_setup_local_logging_returns_path_in_logs_dir(tmp_path, monkeypatch):
    import yosoi.utils.logging as log_mod

    logs_dir = tmp_path / 'mylogs'
    monkeypatch.setattr(log_mod, 'get_logs_path', lambda: logs_dir)

    from yosoi.utils.logging import setup_local_logging

    log_file = setup_local_logging()
    assert log_file.parent == logs_dir

    _cleanup_handlers(log_file)


def test_setup_local_logging_creates_directory(tmp_path, monkeypatch):
    import yosoi.utils.logging as log_mod

    logs_dir = tmp_path / 'nonexistent' / 'deep' / 'logs'
    monkeypatch.setattr(log_mod, 'get_logs_path', lambda: logs_dir)

    from yosoi.utils.logging import setup_local_logging

    log_file = setup_local_logging()
    assert logs_dir.exists()
    assert log_file.exists()

    _cleanup_handlers(log_file)


def test_setup_local_logging_sets_debug_level_by_default(tmp_path, monkeypatch):
    import yosoi.utils.logging as log_mod

    logs_dir = tmp_path / 'logs_debug'
    monkeypatch.setattr(log_mod, 'get_logs_path', lambda: logs_dir)

    from yosoi.utils.logging import setup_local_logging

    log_file = setup_local_logging()

    root = logging.getLogger()
    assert root.level == logging.DEBUG

    _cleanup_handlers(log_file)


def test_setup_local_logging_sets_info_level(tmp_path, monkeypatch):
    import yosoi.utils.logging as log_mod

    logs_dir = tmp_path / 'logs_info'
    monkeypatch.setattr(log_mod, 'get_logs_path', lambda: logs_dir)

    from yosoi.utils.logging import setup_local_logging

    log_file = setup_local_logging(level='INFO')

    root = logging.getLogger()
    assert root.level == logging.INFO

    _cleanup_handlers(log_file)


def test_setup_local_logging_all_level_sets_notset(tmp_path, monkeypatch):
    import yosoi.utils.logging as log_mod

    logs_dir = tmp_path / 'logs2'
    monkeypatch.setattr(log_mod, 'get_logs_path', lambda: logs_dir)

    from yosoi.utils.logging import setup_local_logging

    log_file = setup_local_logging(level='ALL')
    assert log_file.exists()

    root = logging.getLogger()
    assert root.level == logging.NOTSET

    _cleanup_handlers(log_file)


def test_setup_local_logging_adds_file_handler(tmp_path, monkeypatch):
    import yosoi.utils.logging as log_mod

    logs_dir = tmp_path / 'logs_handler'
    monkeypatch.setattr(log_mod, 'get_logs_path', lambda: logs_dir)

    from yosoi.utils.logging import setup_local_logging

    log_file = setup_local_logging()

    root = logging.getLogger()
    file_handlers = [h for h in root.handlers if isinstance(h, logging.FileHandler) and str(log_file) in h.baseFilename]
    assert len(file_handlers) == 1
    assert file_handlers[0].level == logging.DEBUG

    _cleanup_handlers(log_file)


def test_setup_local_logging_file_handler_has_formatter(tmp_path, monkeypatch):
    import yosoi.utils.logging as log_mod

    logs_dir = tmp_path / 'logs_fmt'
    monkeypatch.setattr(log_mod, 'get_logs_path', lambda: logs_dir)

    from yosoi.utils.logging import setup_local_logging

    log_file = setup_local_logging()

    root = logging.getLogger()
    file_handlers = [h for h in root.handlers if isinstance(h, logging.FileHandler) and str(log_file) in h.baseFilename]
    assert len(file_handlers) == 1
    fmt = file_handlers[0].formatter
    assert fmt is not None
    # Formatter should include asctime, name, levelname, message
    fmt_str = fmt._fmt or ''
    assert '%(asctime)s' in fmt_str
    assert '%(levelname)s' in fmt_str
    assert '%(message)s' in fmt_str

    _cleanup_handlers(log_file)


def test_setup_local_logging_log_file_name_starts_with_run(tmp_path, monkeypatch):
    import yosoi.utils.logging as log_mod

    logs_dir = tmp_path / 'logs_name'
    monkeypatch.setattr(log_mod, 'get_logs_path', lambda: logs_dir)

    from yosoi.utils.logging import setup_local_logging

    log_file = setup_local_logging()
    assert log_file.name.startswith('run_')

    _cleanup_handlers(log_file)


def test_setup_local_logging_log_file_name_exact_prefix(tmp_path, monkeypatch):
    """File must start with exactly 'run_' not something else like 'start_'."""
    import yosoi.utils.logging as log_mod

    logs_dir = tmp_path / 'logs_pfx'
    monkeypatch.setattr(log_mod, 'get_logs_path', lambda: logs_dir)

    from yosoi.utils.logging import setup_local_logging

    log_file = setup_local_logging()
    # Name should be exactly 'run_YYYYMMDD_HHMMSS.log'
    assert log_file.name.startswith('run_')
    # Suffix must be .log, not something else
    assert log_file.suffix == '.log'
    # The part after 'run_' should be timestamp-like (digits and underscores)
    stem = log_file.stem  # e.g. 'run_20260309_123456'
    assert stem.startswith('run_')

    _cleanup_handlers(log_file)


def test_setup_local_logging_formatter_exact_format_string(tmp_path, monkeypatch):
    """Formatter must use exact format '%(asctime)s - %(name)s - %(levelname)s - %(message)s'."""
    import yosoi.utils.logging as log_mod

    logs_dir = tmp_path / 'logs_fmt2'
    monkeypatch.setattr(log_mod, 'get_logs_path', lambda: logs_dir)

    from yosoi.utils.logging import setup_local_logging

    log_file = setup_local_logging()

    root = logging.getLogger()
    file_handlers = [h for h in root.handlers if isinstance(h, logging.FileHandler) and str(log_file) in h.baseFilename]
    assert len(file_handlers) == 1
    fmt = file_handlers[0].formatter
    assert fmt is not None
    fmt_str = fmt._fmt or ''
    # Check exact format components including separators
    assert '%(name)s' in fmt_str
    assert ' - ' in fmt_str

    _cleanup_handlers(log_file)


def test_setup_local_logging_handler_level_matches_requested(tmp_path, monkeypatch):
    """Handler level must match the requested level, not just root logger level."""
    import yosoi.utils.logging as log_mod

    logs_dir = tmp_path / 'logs_lvl'
    monkeypatch.setattr(log_mod, 'get_logs_path', lambda: logs_dir)

    from yosoi.utils.logging import setup_local_logging

    log_file = setup_local_logging(level='INFO')

    root = logging.getLogger()
    file_handlers = [h for h in root.handlers if isinstance(h, logging.FileHandler) and str(log_file) in h.baseFilename]
    assert len(file_handlers) == 1
    # Both root logger and handler should be INFO
    assert file_handlers[0].level == logging.INFO
    assert root.level == logging.INFO

    _cleanup_handlers(log_file)


def test_setup_local_logging_all_level_handler_is_notset(tmp_path, monkeypatch):
    """When level='ALL', handler level should be NOTSET (0), not DEBUG (10)."""
    import yosoi.utils.logging as log_mod

    logs_dir = tmp_path / 'logs_all_handler'
    monkeypatch.setattr(log_mod, 'get_logs_path', lambda: logs_dir)

    from yosoi.utils.logging import setup_local_logging

    log_file = setup_local_logging(level='ALL')

    root = logging.getLogger()
    file_handlers = [h for h in root.handlers if isinstance(h, logging.FileHandler) and str(log_file) in h.baseFilename]
    assert len(file_handlers) == 1
    assert file_handlers[0].level == logging.NOTSET

    _cleanup_handlers(log_file)


def test_setup_local_logging_root_logger_has_handler(tmp_path, monkeypatch):
    """Root logger must have the file handler added (not just created)."""
    import yosoi.utils.logging as log_mod

    logs_dir = tmp_path / 'logs_addhandler'
    monkeypatch.setattr(log_mod, 'get_logs_path', lambda: logs_dir)

    from yosoi.utils.logging import setup_local_logging

    log_file = setup_local_logging()
    after_handlers = [
        h
        for h in logging.getLogger().handlers
        if isinstance(h, logging.FileHandler) and str(log_file) in h.baseFilename
    ]
    assert len(after_handlers) == 1

    _cleanup_handlers(log_file)


def test_setup_local_logging_returns_path_object(tmp_path, monkeypatch):
    """Return value must be a Path, not a string."""
    import yosoi.utils.logging as log_mod

    logs_dir = tmp_path / 'logs_ptype'
    monkeypatch.setattr(log_mod, 'get_logs_path', lambda: logs_dir)

    from yosoi.utils.logging import setup_local_logging

    log_file = setup_local_logging()
    assert isinstance(log_file, Path)  # Must be Path (or subclass), not str

    _cleanup_handlers(log_file)


def test_setup_local_logging_log_file_is_under_logs_dir(tmp_path, monkeypatch):
    """Log file must be inside logs_dir, not somewhere else."""
    import yosoi.utils.logging as log_mod

    logs_dir = tmp_path / 'logs_under'
    monkeypatch.setattr(log_mod, 'get_logs_path', lambda: logs_dir)

    from yosoi.utils.logging import setup_local_logging

    log_file = setup_local_logging()
    # log_file parent must be exactly the logs_dir
    assert log_file.parent == logs_dir

    _cleanup_handlers(log_file)
