from yosoi.utils.files import get_project_root, init_yosoi, is_initialized


def test_get_project_root():
    root = get_project_root()
    assert root.exists()
    assert (root / 'pyproject.toml').exists()


def test_is_initialized(tmp_path):
    # Create a dummy project structure in a temp directory
    project_root = tmp_path / 'project'
    project_root.mkdir()
    (project_root / 'pyproject.toml').touch()

    # Mock get_project_root to return our temp project root
    import yosoi.utils.files

    original_get_project_root = yosoi.utils.files.get_project_root
    yosoi.utils.files.get_project_root = lambda: project_root

    try:
        assert not is_initialized()

        # Initialize
        init_yosoi()
        assert is_initialized()

        yosoi_dir = project_root / '.yosoi'
        assert yosoi_dir.is_dir()
        assert (yosoi_dir / 'selectors').is_dir()
        assert (yosoi_dir / '.gitignore').exists()
        assert (yosoi_dir / '.gitignore').read_text() == '*\n'

    finally:
        yosoi.utils.files.get_project_root = original_get_project_root


def test_init_yosoi_custom_name(tmp_path):
    project_root = tmp_path / 'project_custom'
    project_root.mkdir()
    (project_root / 'pyproject.toml').touch()

    import yosoi.utils.files

    original_get_project_root = yosoi.utils.files.get_project_root
    yosoi.utils.files.get_project_root = lambda: project_root

    try:
        storage_path = init_yosoi('custom_storage')
        assert storage_path == project_root / '.yosoi' / 'custom_storage'
        assert storage_path.is_dir()
    finally:
        yosoi.utils.files.get_project_root = original_get_project_root


def test_init_yosoi_from_subdirs(tmp_path):
    """Test that init_yosoi always creates .yosoi in the project root."""
    project_root = tmp_path / 'app_root'
    project_root.mkdir()
    (project_root / 'pyproject.toml').touch()

    src_dir = project_root / 'src'
    src_dir.mkdir()

    yosoi_dir = src_dir / 'yosoi'
    yosoi_dir.mkdir()

    import yosoi.utils.files

    original_get_project_root = yosoi.utils.files.get_project_root

    # Mock get_project_root to return project_root regardless of where it's "called" from
    yosoi.utils.files.get_project_root = lambda: project_root

    try:
        # Simulate call
        storage_path = init_yosoi()
        assert storage_path == project_root / '.yosoi' / 'selectors'
        assert (project_root / '.yosoi').exists()
        assert (project_root / '.yosoi' / 'selectors').is_dir()

    finally:
        yosoi.utils.files.get_project_root = original_get_project_root
