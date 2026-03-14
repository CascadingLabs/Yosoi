import json
from pathlib import Path

import yosoi.utils.files
from yosoi.utils.files import (
    get_debug_path,
    get_logs_path,
    get_project_root,
    get_tracking_path,
    init_yosoi,
    is_initialized,
)


def test_get_project_root(monkeypatch, tmp_path):
    project_root = tmp_path / 'project'
    project_root.mkdir()
    (project_root / 'pyproject.toml').touch()

    sub_dir = project_root / 'src' / 'deep' / 'dir'
    sub_dir.mkdir(parents=True)

    monkeypatch.setattr(Path, 'cwd', lambda: sub_dir)

    root = get_project_root()
    assert root == project_root
    assert (root / 'pyproject.toml').exists()


def test_get_project_root_default(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, 'cwd', lambda: tmp_path)

    root = get_project_root()
    assert root == tmp_path


def test_get_debug_html_path(monkeypatch, tmp_path):
    project_root = tmp_path / 'project'
    project_root.mkdir()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    debug_path = get_debug_path()
    assert debug_path == project_root / '.yosoi' / 'debug'


def test_get_tracking_path(monkeypatch, tmp_path):
    project_root = tmp_path / 'project'
    project_root.mkdir()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    tracking_path = get_tracking_path()
    assert tracking_path == project_root / '.yosoi' / 'stats.json'


def test_is_initialized(monkeypatch, tmp_path):
    project_root = tmp_path / 'project'
    project_root.mkdir()
    (project_root / 'pyproject.toml').touch()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    assert not is_initialized()

    init_yosoi()
    assert is_initialized()

    yosoi_dir = project_root / '.yosoi'
    assert yosoi_dir.is_dir()
    assert (yosoi_dir / 'selectors').is_dir()
    assert (yosoi_dir / 'debug').is_dir()
    assert (yosoi_dir / 'stats.json').exists()
    assert (yosoi_dir / '.gitignore').exists()
    assert (yosoi_dir / '.gitignore').read_text() == '# Automatically created by yosoi\n*\n'


def test_init_yosoi_custom_name(monkeypatch, tmp_path):
    project_root = tmp_path / 'project_custom'
    project_root.mkdir()
    (project_root / 'pyproject.toml').touch()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    storage_path = init_yosoi('custom_storage')
    assert storage_path == project_root / '.yosoi' / 'custom_storage'
    assert storage_path.is_dir()


def test_init_yosoi_from_subdirs(monkeypatch, tmp_path):
    """Test that init_yosoi always creates .yosoi in the project root."""
    project_root = tmp_path / 'app_root'
    project_root.mkdir()
    (project_root / 'pyproject.toml').touch()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    storage_path = init_yosoi()
    assert storage_path == project_root / '.yosoi' / 'selectors'
    assert (project_root / '.yosoi').exists()
    assert (project_root / '.yosoi' / 'selectors').is_dir()


def test_init_yosoi_migrates_tracking(monkeypatch, tmp_path):
    """Test that init_yosoi moves stats.json from root to .yosoi."""
    project_root = tmp_path / 'project_migration'
    project_root.mkdir()
    (project_root / 'pyproject.toml').touch()

    root_tracking = project_root / 'stats.json'
    initial_data = {'test.com': {'llm_calls': 5, 'url_count': 10}}
    root_tracking.write_text(json.dumps(initial_data))

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    init_yosoi()

    assert not root_tracking.exists()
    yosoi_tracking = project_root / '.yosoi' / 'stats.json'
    assert yosoi_tracking.exists()

    with open(yosoi_tracking) as f:
        data = json.load(f)
        assert data == initial_data


def test_get_logs_path(monkeypatch, tmp_path):
    project_root = tmp_path / 'project_logs'
    project_root.mkdir()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    logs_path = get_logs_path()
    assert logs_path == project_root / '.yosoi' / 'logs'


def test_init_yosoi_creates_logs_dir(monkeypatch, tmp_path):
    project_root = tmp_path / 'project_logs_create'
    project_root.mkdir()
    (project_root / 'pyproject.toml').touch()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    init_yosoi()
    assert (project_root / '.yosoi' / 'logs').is_dir()


def test_init_yosoi_creates_debug_dir(monkeypatch, tmp_path):
    project_root = tmp_path / 'project_debug_create'
    project_root.mkdir()
    (project_root / 'pyproject.toml').touch()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    init_yosoi()
    assert (project_root / '.yosoi' / 'debug').is_dir()


def test_init_yosoi_creates_empty_tracking_json(monkeypatch, tmp_path):
    project_root = tmp_path / 'project_tracking_new'
    project_root.mkdir()
    (project_root / 'pyproject.toml').touch()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    init_yosoi()

    tracking_file = project_root / '.yosoi' / 'stats.json'
    assert tracking_file.exists()
    with open(tracking_file) as f:
        data = json.load(f)
    # Should be an empty dict {}
    assert data == {}


def test_init_yosoi_does_not_overwrite_existing_tracking(monkeypatch, tmp_path):
    project_root = tmp_path / 'project_no_overwrite'
    project_root.mkdir()
    (project_root / 'pyproject.toml').touch()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    # Create yosoi dir first with data
    yosoi_dir = project_root / '.yosoi'
    yosoi_dir.mkdir()
    tracking_file = yosoi_dir / 'stats.json'
    existing_data = {'example.com': {'llm_calls': 3, 'url_count': 5}}
    tracking_file.write_text(json.dumps(existing_data))

    init_yosoi()

    with open(tracking_file) as f:
        data = json.load(f)
    # Should not overwrite existing tracking
    assert data == existing_data


def test_init_yosoi_gitignore_content(monkeypatch, tmp_path):
    project_root = tmp_path / 'project_gitignore'
    project_root.mkdir()
    (project_root / 'pyproject.toml').touch()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    init_yosoi()

    gitignore = project_root / '.yosoi' / '.gitignore'
    assert gitignore.exists()
    content = gitignore.read_text()
    assert '*' in content
    assert 'yosoi' in content


def test_init_yosoi_returns_storage_dir_path(monkeypatch, tmp_path):
    project_root = tmp_path / 'project_return'
    project_root.mkdir()
    (project_root / 'pyproject.toml').touch()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    result = init_yosoi('mystore')
    assert result == project_root / '.yosoi' / 'mystore'


def test_is_initialized_creates_tracking_file_if_missing(monkeypatch, tmp_path):
    """is_initialized auto-creates stats.json via ensure_tracking_file."""
    project_root = tmp_path / 'project_partial'
    project_root.mkdir()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    # Create .yosoi dir but no tracking file — is_initialized creates it
    (project_root / '.yosoi').mkdir()
    assert is_initialized()
    assert (project_root / '.yosoi' / 'stats.json').exists()


def test_get_project_root_finds_git_marker(monkeypatch, tmp_path):
    project_root = tmp_path / 'git_project'
    project_root.mkdir()
    (project_root / '.git').mkdir()

    sub_dir = project_root / 'src'
    sub_dir.mkdir()

    monkeypatch.setattr(Path, 'cwd', lambda: sub_dir)

    root = get_project_root()
    assert root == project_root


def test_get_project_root_finds_yosoi_marker(monkeypatch, tmp_path):
    project_root = tmp_path / 'yosoi_project'
    project_root.mkdir()
    (project_root / '.yosoi').mkdir()

    sub_dir = project_root / 'sub'
    sub_dir.mkdir()

    monkeypatch.setattr(Path, 'cwd', lambda: sub_dir)

    root = get_project_root()
    assert root == project_root


def test_get_project_root_finds_requirements_txt(monkeypatch, tmp_path):
    project_root = tmp_path / 'req_project'
    project_root.mkdir()
    (project_root / 'requirements.txt').touch()

    sub_dir = project_root / 'app'
    sub_dir.mkdir()

    monkeypatch.setattr(Path, 'cwd', lambda: sub_dir)

    root = get_project_root()
    assert root == project_root


def test_init_yosoi_default_storage_name_is_selectors(monkeypatch, tmp_path):
    """Default storage_name must be 'selectors', not something else."""
    project_root = tmp_path / 'proj_default'
    project_root.mkdir()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    result = init_yosoi()
    # Default is 'selectors' - verify directory name
    assert result.name == 'selectors'
    assert result == project_root / '.yosoi' / 'selectors'


def test_init_yosoi_debug_dir_name_is_debug(monkeypatch, tmp_path):
    """The debug directory must be named 'debug', not 'debug_html' or other."""
    project_root = tmp_path / 'proj_debug_name'
    project_root.mkdir()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    init_yosoi()
    debug_dir = project_root / '.yosoi' / 'debug'
    assert debug_dir.is_dir()
    # Must not have created debug_html (wrong name)
    assert not (project_root / '.yosoi' / 'debug_html').exists()


def test_init_yosoi_tracking_file_name_is_stats_json(monkeypatch, tmp_path):
    """Tracking file must be 'stats.json', not some other name."""
    project_root = tmp_path / 'proj_tracking_name'
    project_root.mkdir()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    init_yosoi()
    tracking_file = project_root / '.yosoi' / 'stats.json'
    assert tracking_file.exists()


def test_init_yosoi_yosoi_dir_name_is_dotted(monkeypatch, tmp_path):
    """The main yosoi directory must be '.yosoi' (with dot), not 'yosoi'."""
    project_root = tmp_path / 'proj_dotted'
    project_root.mkdir()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    init_yosoi()
    assert (project_root / '.yosoi').is_dir()
    assert not (project_root / 'yosoi').is_dir()


def test_init_yosoi_tracking_file_contains_empty_dict(monkeypatch, tmp_path):
    """New tracking file must contain '{}', not None or empty."""
    project_root = tmp_path / 'proj_empty_dict'
    project_root.mkdir()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    init_yosoi()
    tracking_file = project_root / '.yosoi' / 'stats.json'
    data = json.loads(tracking_file.read_text())
    assert data == {}
    assert isinstance(data, dict)


def test_init_yosoi_returns_path_object(monkeypatch, tmp_path):
    """Return type must be Path, not str."""
    project_root = tmp_path / 'proj_pathtype'
    project_root.mkdir()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    result = init_yosoi()
    from pathlib import Path

    assert isinstance(result, Path)


def test_init_yosoi_creates_parents_for_storage(monkeypatch, tmp_path):
    """Storage directory creation must use parents=True so it creates .yosoi too."""
    project_root = tmp_path / 'proj_parents'
    project_root.mkdir()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    result = init_yosoi('deep_storage')
    assert result.is_dir()
    assert result.parent.is_dir()  # .yosoi must also exist


def test_init_yosoi_gitignore_first_line_is_comment(monkeypatch, tmp_path):
    """Gitignore must start with comment '# Automatically created by yosoi'."""
    project_root = tmp_path / 'proj_gitignore2'
    project_root.mkdir()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    init_yosoi()
    gitignore = project_root / '.yosoi' / '.gitignore'
    content = gitignore.read_text()
    lines = content.split('\n')
    assert lines[0] == '# Automatically created by yosoi'


def test_init_yosoi_gitignore_second_line_is_star(monkeypatch, tmp_path):
    """Gitignore second line must be '*' to ignore all files."""
    project_root = tmp_path / 'proj_gitignore3'
    project_root.mkdir()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    init_yosoi()
    gitignore = project_root / '.yosoi' / '.gitignore'
    content = gitignore.read_text()
    lines = content.split('\n')
    assert lines[1] == '*'


def test_init_yosoi_migration_moves_file_not_copies(monkeypatch, tmp_path):
    """When migrating stats.json, original file must be removed."""
    project_root = tmp_path / 'proj_move_check'
    project_root.mkdir()

    root_tracking = project_root / 'stats.json'
    root_tracking.write_text('{}')

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    init_yosoi()

    # Original should be gone (moved, not copied)
    assert not root_tracking.exists()
    # New location should exist
    assert (project_root / '.yosoi' / 'stats.json').exists()


def test_is_initialized_auto_creates_tracking_when_dir_exists(monkeypatch, tmp_path):
    """is_initialized returns True when .yosoi exists (auto-creates stats.json)."""
    project_root = tmp_path / 'proj_notinit'
    project_root.mkdir()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    (project_root / '.yosoi').mkdir()
    assert is_initialized()  # ensure_tracking_file creates stats.json


def test_get_debug_path_returns_exact_path(monkeypatch, tmp_path):
    """get_debug_path must return exactly root / '.yosoi' / 'debug'."""
    project_root = tmp_path / 'proj_debug_path'
    project_root.mkdir()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    debug_path = get_debug_path()
    assert debug_path == project_root / '.yosoi' / 'debug'


def test_get_tracking_path_returns_exact_path(monkeypatch, tmp_path):
    """get_tracking_path must return exactly root / '.yosoi' / 'stats.json'."""
    project_root = tmp_path / 'proj_tracking_path'
    project_root.mkdir()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    tracking_path = get_tracking_path()
    assert tracking_path == project_root / '.yosoi' / 'stats.json'


def test_get_logs_path_returns_exact_path(monkeypatch, tmp_path):
    """get_logs_path must return exactly root / '.yosoi' / 'logs'."""
    project_root = tmp_path / 'proj_logs_path'
    project_root.mkdir()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    logs_path = get_logs_path()
    assert logs_path == project_root / '.yosoi' / 'logs'
