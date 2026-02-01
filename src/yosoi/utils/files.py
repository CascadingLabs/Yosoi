import shutil
from pathlib import Path


def get_project_root() -> Path:
    """
    Find the project root by searching upwards from the Current Working Directory.
    Stops at the first directory containing a marker file.
    """
    # Start where the user ran the command
    current_path = Path.cwd()

    # Define what makes a folder a "project root"
    markers = {'.git', 'pyproject.toml', '.yosoi', 'requirements.txt'}

    # Walk up the filesystem
    for parent in [current_path] + list(current_path.parents):
        # Check if any marker exists in this directory
        if any((parent / marker).exists() for marker in markers):
            return parent

    # Fallback: If no markers found (e.g., running in /tmp),
    # just use the current directory.
    return current_path


def get_tracking_path() -> Path:
    """
    Returns the path to the LLM tracking file in .yosoi.
    """
    root = get_project_root()
    return root / '.yosoi' / 'llm_tracking.json'


def is_initialized() -> bool:
    """
    Checks if the .yosoi directory exists in the project root.
    """
    root = get_project_root()
    yosoi_dir = root / '.yosoi'
    return yosoi_dir.is_dir() and (yosoi_dir / 'llm_tracking.json').exists()


def init_yosoi(storage_name: str = 'selectors') -> Path:
    """
    Initializes .yosoi directory and returns the storage path.
    """
    root = get_project_root()
    yosoi_dir = root / '.yosoi'
    storage_dir = yosoi_dir / storage_name

    # Create directory structure
    storage_dir.mkdir(parents=True, exist_ok=True)

    # Initialize tracking file if it doesn't exist
    tracking_file = yosoi_dir / 'llm_tracking.json'
    root_tracking = root / 'llm_tracking.json'

    if not tracking_file.exists():
        if root_tracking.exists():
            # Move from root if it exists there
            shutil.move(str(root_tracking), str(tracking_file))
        else:
            # Create new empty tracking file
            import json

            with open(tracking_file, 'w') as f:
                json.dump({}, f, indent=2)

    # Ensure .gitignore exists to keep system-generated files out of source control
    gitignore = yosoi_dir / '.gitignore'
    if not gitignore.exists():
        gitignore.write_text('# Automatically created by yosoi\n*\n')

    return storage_dir


if __name__ == '__main__':
    path = init_yosoi()
    print(f'Yosoi initialized at: {path}')
