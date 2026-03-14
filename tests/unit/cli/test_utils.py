"""Tests for yosoi.cli.utils — scan_for_contracts, load_schema, helpers."""

import textwrap

import pytest
import rich_click as click

from yosoi.cli.utils import (
    _find_contract_classes,
    _load_urls_from_json,
    _raise_class_not_found,
    _suggest_file,
    load_schema,
    scan_for_contracts,
)
from yosoi.models.contract import Contract

# ---------------------------------------------------------------------------
# scan_for_contracts
# ---------------------------------------------------------------------------


class TestScanForContracts:
    def test_finds_contract_in_py_file(self, tmp_path):
        """Scans .py files and finds Contract subclasses."""
        py_file = tmp_path / 'my_schema.py'
        py_file.write_text(
            textwrap.dedent("""\
            from yosoi.models.contract import Contract
            class MySchema(Contract):
                title: str
            """)
        )
        found = scan_for_contracts([str(tmp_path)])
        assert 'MySchema' in found

    def test_skips_pycache(self, tmp_path):
        """Skips __pycache__ directories."""
        cache_dir = tmp_path / '__pycache__'
        cache_dir.mkdir()
        (cache_dir / 'schema.py').write_text('class X(Contract): pass')
        found = scan_for_contracts([str(tmp_path)])
        assert 'X' not in found

    def test_handles_syntax_error(self, tmp_path):
        """Files with syntax errors are skipped."""
        (tmp_path / 'bad.py').write_text('def broken(:')
        found = scan_for_contracts([str(tmp_path)])
        assert found == {}

    def test_default_search_dir(self):
        """With no args, searches current directory."""
        found = scan_for_contracts()
        assert isinstance(found, dict)


# ---------------------------------------------------------------------------
# _suggest_file
# ---------------------------------------------------------------------------


class TestSuggestFile:
    def test_suggests_py_extension(self, tmp_path):
        """Suggests adding .py extension when file exists."""
        (tmp_path / 'schema.py').write_text('')
        suggestions = _suggest_file(str(tmp_path / 'schema'), 'MyClass')
        assert any('.py:MyClass' in s for s in suggestions)

    def test_suggests_close_matches(self, tmp_path):
        """Suggests close filename matches."""
        (tmp_path / 'schema.py').write_text('')
        suggestions = _suggest_file(str(tmp_path / 'schma.py'), 'MyClass')
        assert len(suggestions) > 0

    def test_no_suggestions_for_missing_dir(self):
        """Returns empty list when directory doesn't exist."""
        suggestions = _suggest_file('/nonexistent/dir/file.py', 'C')
        assert suggestions == []


# ---------------------------------------------------------------------------
# _find_contract_classes
# ---------------------------------------------------------------------------


class TestFindContractClasses:
    def test_finds_concrete_subclass(self):
        """Finds concrete Contract subclasses in a module."""
        import types

        mod = types.ModuleType('test_mod')

        class TestContract(Contract):
            title: str = ''

        mod.TestContract = TestContract
        mod.Contract = Contract  # should be excluded

        result = _find_contract_classes(mod)
        assert 'TestContract' in result
        assert 'Contract' not in result


# ---------------------------------------------------------------------------
# _raise_class_not_found
# ---------------------------------------------------------------------------


class TestRaiseClassNotFound:
    def test_raises_with_close_match(self):
        """Raises ClickException with close match suggestion."""
        import types

        mod = types.ModuleType('test_mod')

        class MyContract(Contract):
            title: str = ''

        mod.MyContract = MyContract

        with pytest.raises(click.ClickException, match='Did you mean'):
            _raise_class_not_found('MyContrat', 'file.py', mod, ['MyContract'])

    def test_raises_with_available_contracts(self):
        """Shows available Contract subclasses when no close match."""
        import types

        mod = types.ModuleType('test_mod')

        class FooContract(Contract):
            title: str = ''

        mod.FooContract = FooContract

        with pytest.raises(click.ClickException, match='Available Contract subclasses'):
            _raise_class_not_found('Completely_Different', 'file.py', mod, ['FooContract'])

    def test_raises_with_available_classes(self):
        """Shows available classes when no contracts found."""
        import types

        mod = types.ModuleType('test_mod')
        mod.SomeClass = type('SomeClass', (), {})

        with pytest.raises(click.ClickException, match='Available classes'):
            _raise_class_not_found('Missing', 'file.py', mod, [])


# ---------------------------------------------------------------------------
# load_schema
# ---------------------------------------------------------------------------


class TestLoadSchema:
    def test_missing_colon_raises(self):
        """Schema string without colon raises ClickException."""
        with pytest.raises(click.ClickException, match='path:ClassName'):
            load_schema('no_colon_here')

    def test_missing_file_raises(self):
        """Schema with nonexistent file raises ClickException."""
        with pytest.raises(click.ClickException, match='Schema file not found'):
            load_schema('/nonexistent/path.py:MyClass')

    def test_loads_valid_contract(self, tmp_path):
        """Successfully loads a Contract subclass from a file."""
        py_file = tmp_path / 'schema.py'
        py_file.write_text(
            textwrap.dedent("""\
            from yosoi.models.contract import Contract
            class TestSchema(Contract):
                title: str = ''
            """)
        )
        cls = load_schema(f'{py_file}:TestSchema')
        assert issubclass(cls, Contract)
        assert cls.__name__ == 'TestSchema'

    def test_class_not_contract_raises(self, tmp_path):
        """Non-Contract class raises ClickException."""
        py_file = tmp_path / 'schema.py'
        py_file.write_text('class NotAContract:\n    pass\n')
        with pytest.raises(click.ClickException, match='not a Contract subclass'):
            load_schema(f'{py_file}:NotAContract')

    def test_class_not_found_raises(self, tmp_path):
        """Missing class name raises ClickException."""
        py_file = tmp_path / 'schema.py'
        py_file.write_text('class Foo:\n    pass\n')
        with pytest.raises(click.ClickException, match='not found'):
            load_schema(f'{py_file}:Missing')

    def test_invalid_module_raises(self, tmp_path):
        """File that fails to exec raises ClickException."""
        py_file = tmp_path / 'bad_schema.py'
        py_file.write_text('raise RuntimeError("bad")')
        with pytest.raises(click.ClickException, match='Failed to load'):
            load_schema(f'{py_file}:X')


# ---------------------------------------------------------------------------
# _load_urls_from_json
# ---------------------------------------------------------------------------


class TestLoadUrlsFromJson:
    def test_list_of_strings(self):
        """Extracts URLs from list of strings."""
        assert _load_urls_from_json(['https://a.com', 'https://b.com']) == ['https://a.com', 'https://b.com']

    def test_list_of_dicts(self):
        """Extracts URLs from list of dicts with 'url' key."""
        assert _load_urls_from_json([{'url': 'https://a.com'}]) == ['https://a.com']

    def test_dict_of_strings(self):
        """Extracts URLs from dict values."""
        result = _load_urls_from_json({'a': 'https://a.com'})
        assert 'https://a.com' in result

    def test_dict_with_nested_url(self):
        """Extracts URLs from nested dicts with 'url' key."""
        result = _load_urls_from_json({'a': {'url': 'https://a.com'}})
        assert 'https://a.com' in result

    def test_non_string_non_dict_returns_empty(self):
        """Non-string, non-dict returns empty list."""
        assert _load_urls_from_json(42) == []

    def test_skips_empty_strings(self):
        """Empty strings are filtered."""
        assert _load_urls_from_json(['', 'https://a.com']) == ['https://a.com']

    def test_list_mixed_types(self):
        """Non-string, non-dict items in list are skipped."""
        assert _load_urls_from_json([42, 'https://a.com', None]) == ['https://a.com']
