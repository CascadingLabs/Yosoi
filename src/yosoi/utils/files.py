from pathlib import Path


def get_project_root() -> Path:
    """
    Traverse upwards from this file to find the project root.
    """
    # Start from the directory containing this script
    current = Path(__file__).resolve().parent

    # Check parents until we hit the filesystem root
    for parent in [current] + list(current.parents):
        if any((parent / marker).exists() for marker in ['.git', 'pyproject.toml', '.yosoi']):
            return parent

    return Path.cwd()


def is_initialized() -> bool:
    """
    Checks if the .yosoi directory exists in the project root.
    """
    root = get_project_root()
    return (root / '.yosoi').is_dir()


def init_yosoi(storage_name: str = 'selectors') -> Path:
    """
    Initializes .yosoi directory and returns the storage path.
    """
    root = get_project_root()
    yosoi_dir = root / '.yosoi'
    storage_dir = yosoi_dir / storage_name

    # Create directory structure
    storage_dir.mkdir(parents=True, exist_ok=True)

    # Ensure .gitignore exists to keep system-generated files out of source control
    gitignore = yosoi_dir / '.gitignore'
    if not gitignore.exists():
        gitignore.write_text('# Automatically created by yosoi\n*\n')

    return storage_dir


if __name__ == '__main__':
    path = init_yosoi()
    print(f'Yosoi initialized at: {path}')
