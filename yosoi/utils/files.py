"""Utility functions for file and directory management in Yosoi."""

import shutil
from pathlib import Path

import logfire


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
        with logfire.span('tracking.migrate.root', source=str(root_tracking), destination=str(tracking_file)):
            try:
                shutil.move(str(root_tracking), str(tracking_file))
            except Exception:
                logfire.exception('Failed to migrate root tracking')
                raise
    else:
        with logfire.span('tracking.create.new', path=str(tracking_file)):
            import json

            with open(tracking_file, 'w') as f:
                json.dump({}, f, indent=2)


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
