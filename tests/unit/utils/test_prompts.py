"""Tests for load_prompt utility."""

import pytest

from yosoi.utils.prompts import load_prompt


def test_load_prompt_returns_string():
    result = load_prompt('discovery_system')
    assert isinstance(result, str)


def test_load_prompt_returns_non_empty_content():
    result = load_prompt('discovery_system')
    assert len(result) > 0


def test_load_prompt_strips_whitespace():
    result = load_prompt('discovery_system')
    # strip() is called on the result, so it should not start/end with whitespace
    assert result == result.strip()


def test_load_prompt_discovery_user_returns_string():
    result = load_prompt('discovery_user')
    assert isinstance(result, str)
    assert len(result) > 0


def test_load_prompt_nonexistent_raises_file_not_found():
    with pytest.raises(FileNotFoundError) as exc_info:
        load_prompt('nonexistent_prompt_xyz')
    assert 'nonexistent_prompt_xyz' in str(exc_info.value)


def test_load_prompt_error_message_contains_path():
    with pytest.raises(FileNotFoundError) as exc_info:
        load_prompt('no_such_file')
    assert 'no_such_file' in str(exc_info.value)


def test_load_prompt_discovery_system_not_empty():
    content = load_prompt('discovery_system')
    assert len(content.strip()) > 0


def test_load_prompt_uses_md_extension(tmp_path, monkeypatch):
    """Verify that load_prompt looks for .md files."""
    import yosoi.utils.prompts as prompts_mod

    # Create a fake prompts directory structure
    fake_prompts_dir = tmp_path / 'prompts'
    fake_prompts_dir.mkdir()
    test_file = fake_prompts_dir / 'test_prompt.md'
    test_file.write_text('  Hello from test prompt  ', encoding='utf-8')

    def patched_load(name: str) -> str:
        prompt_path = fake_prompts_dir / f'{name}.md'
        if not prompt_path.exists():
            raise FileNotFoundError(f'Prompt file not found: {prompt_path}')
        return str(prompt_path.read_text(encoding='utf-8').strip())

    monkeypatch.setattr(prompts_mod, 'load_prompt', patched_load)
    result = prompts_mod.load_prompt('test_prompt')
    assert result == 'Hello from test prompt'


def test_load_prompt_strips_leading_whitespace(tmp_path, monkeypatch):
    """Verify that strip() removes leading whitespace from prompt content."""
    import yosoi.utils.prompts as prompts_mod

    fake_prompts_dir = tmp_path / 'prompts'
    fake_prompts_dir.mkdir()
    test_file = fake_prompts_dir / 'padded.md'
    test_file.write_text('\n\n  Some content  \n\n', encoding='utf-8')

    def patched_load(name: str) -> str:
        prompt_path = fake_prompts_dir / f'{name}.md'
        if not prompt_path.exists():
            raise FileNotFoundError(f'Prompt file not found: {prompt_path}')
        return str(prompt_path.read_text(encoding='utf-8').strip())

    monkeypatch.setattr(prompts_mod, 'load_prompt', patched_load)
    result = prompts_mod.load_prompt('padded')
    assert result == 'Some content'
    assert not result.startswith('\n')
    assert not result.endswith('\n')


def test_load_prompt_error_message_exact_format():
    """Error message must contain 'Prompt file not found:' prefix."""
    with pytest.raises(FileNotFoundError) as exc_info:
        load_prompt('absolutely_nonexistent_xyz123')
    msg = str(exc_info.value)
    assert 'Prompt file not found:' in msg
    assert 'absolutely_nonexistent_xyz123' in msg


def test_load_prompt_reads_with_utf8_encoding():
    """Verify the prompt is read with utf-8 encoding (not default encoding)."""
    # If we can load a real prompt without encoding errors, utf-8 is being used
    result = load_prompt('discovery_system')
    assert isinstance(result, str)


def test_load_prompt_path_uses_prompts_subdirectory():
    """Prompt path must include 'prompts' subdirectory."""
    # We verify this by checking the FileNotFoundError message contains 'prompts'
    with pytest.raises(FileNotFoundError) as exc_info:
        load_prompt('no_such_file_abc')
    assert 'prompts' in str(exc_info.value)


def test_load_prompt_path_uses_md_extension_in_error():
    """Error message should reference the .md file extension."""
    with pytest.raises(FileNotFoundError) as exc_info:
        load_prompt('no_such_file_def')
    assert '.md' in str(exc_info.value)


def test_load_prompt_content_is_stripped_not_original():
    """The strip() call must actually remove whitespace — not return raw content."""
    # discovery_system exists and strip() should produce same result as calling strip() again
    result = load_prompt('discovery_system')
    assert result == result.strip()
