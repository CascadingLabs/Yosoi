import json
from pathlib import Path

import yosoi.utils.files
from yosoi.utils.files import (
    get_debug_path,
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
    assert tracking_path == project_root / '.yosoi' / 'llm_tracking.json'


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
    assert (yosoi_dir / 'llm_tracking.json').exists()
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
    """Test that init_yosoi moves llm_tracking.json from root to .yosoi."""
    project_root = tmp_path / 'project_migration'
    project_root.mkdir()
    (project_root / 'pyproject.toml').touch()

    root_tracking = project_root / 'llm_tracking.json'
    initial_data = {'test.com': {'llm_calls': 5, 'url_count': 10}}
    root_tracking.write_text(json.dumps(initial_data))

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    init_yosoi()

    assert not root_tracking.exists()
    yosoi_tracking = project_root / '.yosoi' / 'llm_tracking.json'
    assert yosoi_tracking.exists()

    with open(yosoi_tracking) as f:
        data = json.load(f)
        assert data == initial_data
