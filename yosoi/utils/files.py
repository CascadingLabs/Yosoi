"""Utility functions for file and directory management in Yosoi."""

import contextlib
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import aiofiles
import aiofiles.os

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

    The async counterpart of :func:`atomic_write_text`: the file body is
    written with ``aiofiles`` (off the event loop) and swapped into place with
    ``aiofiles.os.replace``, which is atomic on POSIX. A concurrent reader or a
    crash can never observe a torn file — only the old or the complete new
    contents.

    Note: like the original sync storage writes, this does not ``fsync`` the
    file (``aiofiles.os`` exposes no async fsync), so durability ordering after
    a hard power loss is unchanged; the atomic-visibility guarantee comes from
    the rename, not from fsync.

    Args:
        path: Destination file path.
        text: Full file contents to write.
        encoding: Text encoding. Defaults to 'utf-8'.

    """
    path = Path(path)
    await aiofiles.os.makedirs(str(path.parent), exist_ok=True)
    # mkstemp is a single fast syscall; the expensive write happens via aiofiles.
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f'.{path.name}.', suffix='.tmp')
    os.close(fd)
    try:
        async with aiofiles.open(tmp_name, 'w', encoding=encoding) as f:
            await f.write(text)
            await f.flush()
        await aiofiles.os.replace(tmp_name, str(path))
    except BaseException:
        with contextlib.suppress(OSError):
            await aiofiles.os.remove(tmp_name)
        raise


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

    # Define what makes a folder a "project root"
    markers = {'.git', 'pyproject.toml', '.yosoi', 'requirements.txt'}

    # Walk up the filesystem
    for parent in [current_path, *list(current_path.parents)]:
        # Check if any marker exists in this directory
        if any((parent / marker).exists() for marker in markers):
            return parent

    # Fallback: If no markers found (e.g., running in /tmp),
    # just use the current directory.
    return current_path


def get_tracking_path() -> Path:
    """Return the path to the LLM tracking file in .yosoi."""
    root = get_project_root()
    return root / '.yosoi' / 'stats.json'


def get_debug_path() -> Path:
    """Return the path to the debug directory in .yosoi."""
    root = get_project_root()
    return root / '.yosoi' / 'debug'


def get_logs_path() -> Path:
    """Return the path to the logs directory in .yosoi."""
    root = get_project_root()
    return root / '.yosoi' / 'logs'


def ensure_tracking_file(yosoi_dir: Path) -> None:
    """Migrate root-level tracking file or create a new one if needed.

    Handles two paths:
    - <root>/stats.json → .yosoi/stats.json (root-level move)
    - Create new empty .yosoi/stats.json

    Args:
        yosoi_dir: Path to the .yosoi directory.

    """
    tracking_file = yosoi_dir / 'stats.json'
    root_tracking = yosoi_dir.parent / 'stats.json'

    if tracking_file.exists():
        return

    if root_tracking.exists():
        try:
            shutil.move(str(root_tracking), str(tracking_file))
        except Exception:
            _logger.exception('Failed to migrate root tracking')
            raise
    else:
        atomic_write_json(tracking_file, {})


def is_initialized() -> bool:
    """Check if the .yosoi directory exists in the project root."""
    root = get_project_root()
    yosoi_dir = root / '.yosoi'
    if not yosoi_dir.is_dir():
        return False
    # Attempt migration before checking — handles legacy-only workspaces
    ensure_tracking_file(yosoi_dir)
    return (yosoi_dir / 'stats.json').exists()


def init_yosoi(storage_name: str = 'selectors') -> Path:
    """Initialize .yosoi directory and return the storage path."""
    root = get_project_root()
    yosoi_dir = root / '.yosoi'
    storage_dir = yosoi_dir / storage_name
    debug_dir = yosoi_dir / 'debug'
    logs_dir = yosoi_dir / 'logs'

    # Create directory structure
    storage_dir.mkdir(parents=True, exist_ok=True)
    debug_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Initialize tracking file if it doesn't exist
    ensure_tracking_file(yosoi_dir)

    # Ensure .gitignore exists to keep system-generated files out of source control
    gitignore = yosoi_dir / '.gitignore'
    if not gitignore.exists():
        gitignore.write_text('# Automatically created by yosoi\n*\n')

    return storage_dir


if __name__ == '__main__':
    path = init_yosoi()
    print(f'Yosoi initialized at: {path}')
