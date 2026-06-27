import json
import sqlite3
from pathlib import Path

import pytest

import yosoi.utils.files
from yosoi.utils.files import (
    atomic_write_json,
    atomic_write_json_async,
    atomic_write_text,
    atomic_write_text_async,
    ensure_tracking_file,
    get_debug_path,
    get_logs_path,
    get_project_root,
    get_tracking_path,
    init_yosoi,
    is_initialized,
    safe_domain,
)


def _tracking_row(db_path: Path, domain: str) -> tuple | None:
    with sqlite3.connect(db_path) as db:
        return db.execute('SELECT llm_calls, url_count FROM tracking_stats WHERE domain = ?', (domain,)).fetchone()


def test_safe_domain_replaces_separators():
    assert safe_domain('finance.yahoo.com') == 'finance_yahoo_com'


def test_safe_domain_strips_port_and_path_separators():
    """The single source of truth handles ':' and '/' too, so port/path-bearing
    domains map to one stable filename across every store (was the drift)."""
    assert safe_domain('localhost:8080/app') == 'localhost_8080_app'


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
    assert tracking_path == project_root / '.yosoi' / 'yosoi.sqlite3'


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
    assert not (yosoi_dir / 'selectors').exists()
    assert not (yosoi_dir / 'debug').exists()
    assert not (yosoi_dir / 'logs').exists()
    assert not (yosoi_dir / 'stats.json').exists()
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
    assert storage_path == project_root / '.yosoi'
    assert (project_root / '.yosoi').exists()
    assert not (project_root / '.yosoi' / 'selectors').exists()


def test_init_yosoi_migrates_tracking(monkeypatch, tmp_path):
    """Test that init_yosoi imports root stats.json into SQLite and removes it."""
    project_root = tmp_path / 'project_migration'
    project_root.mkdir()
    (project_root / 'pyproject.toml').touch()

    root_tracking = project_root / 'stats.json'
    initial_data = {'test.com': {'llm_calls': 5, 'url_count': 10}}
    root_tracking.write_text(json.dumps(initial_data))

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    init_yosoi()

    assert not root_tracking.exists()
    yosoi_tracking = project_root / '.yosoi' / 'yosoi.sqlite3'
    assert yosoi_tracking.exists()
    assert _tracking_row(yosoi_tracking, 'test.com') == (5, 10)


def test_get_logs_path(monkeypatch, tmp_path):
    project_root = tmp_path / 'project_logs'
    project_root.mkdir()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    logs_path = get_logs_path()
    assert logs_path == project_root / '.yosoi' / 'logs'


def test_init_yosoi_does_not_create_logs_dir_until_requested(monkeypatch, tmp_path):
    project_root = tmp_path / 'project_logs_create'
    project_root.mkdir()
    (project_root / 'pyproject.toml').touch()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    init_yosoi()
    assert not (project_root / '.yosoi' / 'logs').exists()


def test_init_yosoi_does_not_create_debug_dir_until_requested(monkeypatch, tmp_path):
    project_root = tmp_path / 'project_debug_create'
    project_root.mkdir()
    (project_root / 'pyproject.toml').touch()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    init_yosoi()
    assert not (project_root / '.yosoi' / 'debug').exists()


def test_init_yosoi_does_not_create_tracking_json(monkeypatch, tmp_path):
    project_root = tmp_path / 'project_tracking_new'
    project_root.mkdir()
    (project_root / 'pyproject.toml').touch()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    init_yosoi()

    tracking_file = project_root / '.yosoi' / 'stats.json'
    assert not tracking_file.exists()


def test_init_yosoi_migrates_existing_tracking(monkeypatch, tmp_path):
    project_root = tmp_path / 'project_no_overwrite'
    project_root.mkdir()
    (project_root / 'pyproject.toml').touch()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    yosoi_dir = project_root / '.yosoi'
    yosoi_dir.mkdir()
    tracking_file = yosoi_dir / 'stats.json'
    existing_data = {'example.com': {'llm_calls': 3, 'url_count': 5}}
    tracking_file.write_text(json.dumps(existing_data))

    init_yosoi()

    assert not tracking_file.exists()
    assert _tracking_row(yosoi_dir / 'yosoi.sqlite3', 'example.com') == (3, 5)


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


def test_is_initialized_does_not_create_tracking_json(monkeypatch, tmp_path):
    project_root = tmp_path / 'project_partial'
    project_root.mkdir()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    (project_root / '.yosoi').mkdir()
    assert is_initialized()
    assert not (project_root / '.yosoi' / 'stats.json').exists()


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


def test_init_yosoi_default_returns_yosoi_dir(monkeypatch, tmp_path):
    """Default init creates only the .yosoi root and metadata."""
    project_root = tmp_path / 'proj_default'
    project_root.mkdir()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    result = init_yosoi()
    assert result.name == '.yosoi'
    assert result == project_root / '.yosoi'
    assert not (result / 'selectors').exists()


def test_init_yosoi_does_not_create_dead_debug_html_dir(monkeypatch, tmp_path):
    """The old debug_html directory must not be created."""
    project_root = tmp_path / 'proj_debug_name'
    project_root.mkdir()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    init_yosoi()
    assert not (project_root / '.yosoi' / 'debug').exists()
    assert not (project_root / '.yosoi' / 'debug_html').exists()


def test_init_yosoi_tracking_file_name_is_sqlite(monkeypatch, tmp_path):
    project_root = tmp_path / 'proj_tracking_name'
    project_root.mkdir()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    init_yosoi()
    assert not (project_root / '.yosoi' / 'stats.json').exists()


def test_init_yosoi_yosoi_dir_name_is_dotted(monkeypatch, tmp_path):
    """The main yosoi directory must be '.yosoi' (with dot), not 'yosoi'."""
    project_root = tmp_path / 'proj_dotted'
    project_root.mkdir()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    init_yosoi()
    assert (project_root / '.yosoi').is_dir()
    assert not (project_root / 'yosoi').is_dir()


def test_init_yosoi_tracking_file_absent_until_sqlite_use(monkeypatch, tmp_path):
    project_root = tmp_path / 'proj_empty_dict'
    project_root.mkdir()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    init_yosoi()
    assert not (project_root / '.yosoi' / 'stats.json').exists()


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


def test_init_yosoi_migration_removes_json(monkeypatch, tmp_path):
    project_root = tmp_path / 'proj_move_check'
    project_root.mkdir()

    root_tracking = project_root / 'stats.json'
    root_tracking.write_text('{}')

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    init_yosoi()

    assert not root_tracking.exists()
    assert not (project_root / '.yosoi' / 'stats.json').exists()
    assert (project_root / '.yosoi' / 'yosoi.sqlite3').exists()


def test_is_initialized_true_when_dir_exists(monkeypatch, tmp_path):
    project_root = tmp_path / 'proj_notinit'
    project_root.mkdir()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    (project_root / '.yosoi').mkdir()
    assert is_initialized()


def test_get_debug_path_returns_exact_path(monkeypatch, tmp_path):
    """get_debug_path must return exactly root / '.yosoi' / 'debug'."""
    project_root = tmp_path / 'proj_debug_path'
    project_root.mkdir()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    debug_path = get_debug_path()
    assert debug_path == project_root / '.yosoi' / 'debug'


def test_get_tracking_path_returns_exact_path(monkeypatch, tmp_path):
    """get_tracking_path returns the SQLite DB path used for tracking."""
    project_root = tmp_path / 'proj_tracking_path'
    project_root.mkdir()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    tracking_path = get_tracking_path()
    assert tracking_path == project_root / '.yosoi' / 'yosoi.sqlite3'


def test_get_logs_path_returns_exact_path(monkeypatch, tmp_path):
    """get_logs_path must return exactly root / '.yosoi' / 'logs'."""
    project_root = tmp_path / 'proj_logs_path'
    project_root.mkdir()

    monkeypatch.setattr(yosoi.utils.files, 'get_project_root', lambda: project_root)

    logs_path = get_logs_path()
    assert logs_path == project_root / '.yosoi' / 'logs'


# ---------------------------------------------------------------------------
# Coverage: ensure_tracking_file root migration
# ---------------------------------------------------------------------------


def test_ensure_tracking_migrates_root_file(tmp_path):
    """ensure_tracking_file imports <root>/stats.json into SQLite."""
    yosoi_dir = tmp_path / '.yosoi'
    yosoi_dir.mkdir()
    root_tracking = tmp_path / 'stats.json'
    root_tracking.write_text('{"root.com": {"llm_calls": 1, "url_count": 2}}')

    ensure_tracking_file(yosoi_dir)

    assert not (yosoi_dir / 'stats.json').exists()
    assert not root_tracking.exists()
    assert _tracking_row(yosoi_dir / 'yosoi.sqlite3', 'root.com') == (1, 2)


# ---------------------------------------------------------------------------
# Atomic write helpers (sync + async)
# ---------------------------------------------------------------------------


def _no_tmp_left(directory: Path) -> bool:
    """No leftover temp files (atomic writer cleans up on success and failure)."""
    return not list(directory.glob('.*.tmp'))


def test_atomic_write_text_creates_parents_and_writes(tmp_path):
    target = tmp_path / 'nested' / 'deep' / 'out.txt'
    atomic_write_text(target, 'hello')
    assert target.read_text() == 'hello'
    assert _no_tmp_left(target.parent)


def test_atomic_write_json_roundtrips(tmp_path):
    target = tmp_path / 'data.json'
    atomic_write_json(target, {'a': 1, 'b': [2, 3]})
    assert json.loads(target.read_text()) == {'a': 1, 'b': [2, 3]}
    assert _no_tmp_left(target.parent)


def test_atomic_write_text_failure_cleans_tmp_and_preserves_original(tmp_path, mocker):
    target = tmp_path / 'out.txt'
    target.write_text('original')
    mocker.patch('yosoi.utils.files.os.replace', side_effect=OSError('boom'))

    with pytest.raises(OSError, match='boom'):
        atomic_write_text(target, 'new content')

    # Original is untouched and no temp file is left behind.
    assert target.read_text() == 'original'
    assert _no_tmp_left(tmp_path)


async def test_atomic_write_text_async_creates_parents_and_writes(tmp_path):
    target = tmp_path / 'nested' / 'out.txt'
    await atomic_write_text_async(target, 'hello async')
    assert target.read_text() == 'hello async'
    assert _no_tmp_left(target.parent)


async def test_atomic_write_json_async_roundtrips(tmp_path):
    target = tmp_path / 'data.json'
    await atomic_write_json_async(target, {'x': 'y'}, ensure_ascii=False)
    assert json.loads(target.read_text()) == {'x': 'y'}
    assert _no_tmp_left(target.parent)


async def test_atomic_write_async_failure_cleans_tmp_and_preserves_original(tmp_path, mocker):
    target = tmp_path / 'out.txt'
    target.write_text('original')
    mocker.patch('yosoi.utils.files.os.replace', side_effect=OSError('boom'))

    with pytest.raises(OSError, match='boom'):
        await atomic_write_text_async(target, 'new content')

    assert target.read_text() == 'original'
    assert _no_tmp_left(tmp_path)


def test_ensure_tracking_file_reraises_on_migration_failure(tmp_path, mocker):
    """A failed stats.json SQLite import must re-raise."""
    yosoi_dir = tmp_path / '.yosoi'
    yosoi_dir.mkdir()
    (tmp_path / 'stats.json').write_text(json.dumps({'a.com': {}}))

    mocker.patch('yosoi.utils.files.sqlite3.connect', side_effect=OSError('sqlite failed'))

    with pytest.raises(OSError, match='sqlite failed'):
        ensure_tracking_file(yosoi_dir)
