"""Utility functions for file and directory management in Yosoi."""

import contextlib
import json
import logging
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)


def atomic_write_text(path: str | Path, text: str, *, encoding: str = 'utf-8') -> None:
    """Atomically write *text* to *path*.

    Writes to a temporary file in the same directory, flushes and fsyncs it,
    then ``os.replace``s it onto the target. Because ``os.replace`` is atomic
    on POSIX (and Windows for same-volume moves), a concurrent reader, crash,
    or kill mid-write can never observe a truncated or partially written file:
    it sees either the old contents or the complete new contents.

    Args:
        path: Destination file path.
        text: Full file contents to write.
        encoding: Text encoding. Defaults to 'utf-8'.

    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Temp file must live on the same filesystem as the target for os.replace
    # to be atomic, so create it in the destination directory.
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f'.{path.name}.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding=encoding) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, str(path))
    except BaseException:
        # Never leave a stray temp file behind on failure.
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def atomic_write_json(
    path: str | Path,
    data: Any,
    *,
    indent: int | None = 2,
    ensure_ascii: bool = True,
) -> None:
    """Atomically serialise *data* to JSON at *path*.

    Thin wrapper over :func:`atomic_write_text` so all JSON persistence shares
    the crash-safe write path. See :func:`atomic_write_text` for guarantees.

    Args:
        path: Destination file path.
        data: JSON-serialisable object.
        indent: ``json.dump`` indent. Defaults to 2.
        ensure_ascii: ``json.dump`` ensure_ascii. Defaults to True.

    """
    atomic_write_text(path, json.dumps(data, indent=indent, ensure_ascii=ensure_ascii))


async def atomic_write_text_async(path: str | Path, text: str, *, encoding: str = 'utf-8') -> None:
    """Async, crash-safe write of *text* to *path*.

    Delegates to the synchronous atomic writer. These writes are small local
    cache artifacts, and keeping one stdlib implementation avoids runtime
    differences in async file/threadpool shims.

    Args:
        path: Destination file path.
        text: Full file contents to write.
        encoding: Text encoding. Defaults to 'utf-8'.

    """
    atomic_write_text(path, text, encoding=encoding)


async def atomic_write_json_async(
    path: str | Path,
    data: Any,
    *,
    indent: int | None = 2,
    ensure_ascii: bool = True,
) -> None:
    """Async, crash-safe JSON serialisation to *path*.

    Thin wrapper over :func:`atomic_write_text_async`. See it for guarantees.

    Args:
        path: Destination file path.
        data: JSON-serialisable object.
        indent: ``json.dumps`` indent. Defaults to 2.
        ensure_ascii: ``json.dumps`` ensure_ascii. Defaults to True.

    """
    await atomic_write_text_async(path, json.dumps(data, indent=indent, ensure_ascii=ensure_ascii))


def safe_domain(domain: str) -> str:
    """Return a filesystem-safe form of a domain for use in cache filenames.

    Single source of truth for the per-domain cache key. Replaces the
    ``domain.replace('.', '_')...`` snippets that were copied across the storage modules
    and had drifted (some stripped ``:``, some did not), so the same domain always maps
    to the same on-disk filename across every store.
    """
    return domain.replace('.', '_').replace('/', '_').replace(':', '_')


def get_project_root() -> Path:
    """Find the project root by searching upwards from the Current Working Directory.

    Stops at the first directory containing a marker file.
    """
    # Start where the user ran the command
    current_path = Path.cwd()
    tmp_root = Path(tempfile.gettempdir()).resolve()

    # Define what makes a folder a "project root"
    markers = {'.git', 'pyproject.toml', '.yosoi', 'requirements.txt'}

    # Walk up the filesystem
    for parent in [current_path, *list(current_path.parents)]:
        if parent.resolve() == tmp_root and parent != current_path:
            continue
        # Check if any marker exists in this directory
        if any((parent / marker).exists() for marker in markers):
            return parent

    # Fallback: If no markers found (e.g., running in /tmp),
    # just use the current directory.
    return current_path


def get_yosoi_dir() -> Path:
    """Return the project-local .yosoi directory path without creating it."""
    return get_project_root() / '.yosoi'


def get_yosoi_storage_path(storage_name: str | Path) -> Path:
    """Return a child path under .yosoi without creating directories."""
    return get_yosoi_dir() / Path(storage_name)


def get_tracking_path() -> Path:
    """Deprecated: return the SQLite DB path that now stores tracking data."""
    return get_yosoi_dir() / 'yosoi.sqlite3'


def get_debug_path() -> Path:
    """Return the path to the debug directory in .yosoi."""
    return get_yosoi_dir() / 'debug'


def get_logs_path() -> Path:
    """Return the path to the logs directory in .yosoi."""
    return get_yosoi_dir() / 'logs'


def migrate_legacy_tracking_stats(yosoi_dir: Path) -> None:
    """Import legacy stats.json files into `.yosoi/yosoi.sqlite3`, then remove them."""
    legacy_paths = [yosoi_dir.parent / 'stats.json', yosoi_dir / 'stats.json']
    payloads: list[dict[str, Any]] = []
    for path in legacy_paths:
        if not path.exists():
            continue
        try:
            raw = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(raw, dict):
                payloads.append(raw)
        except (OSError, json.JSONDecodeError):
            _logger.warning('Ignoring unreadable legacy tracking file: %s', path)
        path.unlink(missing_ok=True)

    if not payloads:
        return

    db_path = yosoi_dir / 'yosoi.sqlite3'
    with sqlite3.connect(db_path) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS tracking_stats (
                domain TEXT PRIMARY KEY,
                llm_calls INTEGER NOT NULL DEFAULT 0,
                url_count INTEGER NOT NULL DEFAULT 0,
                level_distribution TEXT NOT NULL DEFAULT '{}',
                total_elapsed REAL NOT NULL DEFAULT 0,
                partial_rediscovery_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        for payload in payloads:
            for domain, entry in payload.items():
                if not isinstance(entry, dict):
                    continue
                dist = entry.get('level_distribution') if isinstance(entry.get('level_distribution'), dict) else {}
                db.execute(
                    """
                    INSERT INTO tracking_stats (
                        domain, llm_calls, url_count, level_distribution,
                        total_elapsed, partial_rediscovery_count, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(domain) DO UPDATE SET
                        llm_calls = tracking_stats.llm_calls + excluded.llm_calls,
                        url_count = tracking_stats.url_count + excluded.url_count,
                        level_distribution = excluded.level_distribution,
                        total_elapsed = tracking_stats.total_elapsed + excluded.total_elapsed,
                        partial_rediscovery_count = (
                            tracking_stats.partial_rediscovery_count + excluded.partial_rediscovery_count
                        ),
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        str(domain),
                        int(entry.get('llm_calls') or 0),
                        int(entry.get('url_count') or 0),
                        json.dumps(dist, separators=(',', ':')),
                        float(entry.get('total_elapsed') or 0.0),
                        int(entry.get('partial_rediscovery_count') or 0),
                    ),
                )


def ensure_tracking_file(yosoi_dir: Path) -> None:
    """Deprecated compatibility shim: migrate legacy stats.json into SQLite."""
    migrate_legacy_tracking_stats(yosoi_dir)


def is_initialized() -> bool:
    """Check if the .yosoi directory exists in the project root."""
    yosoi_dir = get_yosoi_dir()
    if not yosoi_dir.is_dir():
        return False
    migrate_legacy_tracking_stats(yosoi_dir)
    return True


def _ensure_yosoi_gitignore(yosoi_dir: Path) -> None:
    """Ensure .yosoi has a local ignore file for generated artifacts."""
    gitignore = yosoi_dir / '.gitignore'
    if not gitignore.exists():
        gitignore.write_text('# Automatically created by yosoi\n*\n', encoding='utf-8')


def init_yosoi(storage_name: str | Path | None = None) -> Path:
    """Initialize .yosoi metadata and optionally one requested child directory."""
    yosoi_dir = get_yosoi_dir()
    yosoi_dir.mkdir(parents=True, exist_ok=True)

    migrate_legacy_tracking_stats(yosoi_dir)
    _ensure_yosoi_gitignore(yosoi_dir)

    if storage_name is None:
        return yosoi_dir

    storage_dir = yosoi_dir / Path(storage_name)
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir


if __name__ == '__main__':
    path = init_yosoi()
    print(f'Yosoi initialized at: {path}')
