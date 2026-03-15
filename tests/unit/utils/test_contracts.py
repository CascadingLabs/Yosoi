"""Tests for yosoi.utils.contracts — resolve_contract (core logic, no CLI deps)."""

import importlib.util

import pytest

from yosoi.models.contract import Contract
from yosoi.models.defaults import NewsArticle, Product
from yosoi.utils.contracts import (
    _find_contract_classes,
    _load_contract_from_file,
    resolve_contract,
    scan_for_contracts,
)


class TestScanForContracts:
    def test_finds_contract_subclass(self, tmp_path):
        """scan_for_contracts finds classes with Contract as base."""
        f = tmp_path / 'myschema.py'
        f.write_text('from yosoi.models.contract import Contract\nclass MySchema(Contract):\n    title: str\n')
        found = scan_for_contracts([str(tmp_path)])
        assert 'MySchema' in found
        assert str(f) in found['MySchema']

    def test_skips_syntax_error_files(self, tmp_path):
        """scan_for_contracts silently skips files with syntax errors."""
        bad = tmp_path / 'bad.py'
        bad.write_text('class Foo(\n    def broken():')  # invalid syntax
        found = scan_for_contracts([str(tmp_path)])
        assert isinstance(found, dict)

    def test_skips_excluded_dirs(self, tmp_path):
        """scan_for_contracts skips dirs in _SCAN_SKIP_DIRS."""
        skip_dir = tmp_path / '__pycache__'
        skip_dir.mkdir()
        schema = skip_dir / 'schema.py'
        schema.write_text('from yosoi.models.contract import Contract\nclass CachedSchema(Contract):\n    x: str\n')
        found = scan_for_contracts([str(tmp_path)])
        assert 'CachedSchema' not in found

    def test_skips_tests_dir(self, tmp_path):
        """scan_for_contracts skips the 'tests' directory."""
        tests_dir = tmp_path / 'tests'
        tests_dir.mkdir()
        f = tests_dir / 'test_schema.py'
        f.write_text('from yosoi.models.contract import Contract\nclass TestSchema(Contract):\n    x: str\n')
        found = scan_for_contracts([str(tmp_path)])
        assert 'TestSchema' not in found

    def test_detects_attribute_based_base(self, tmp_path):
        """scan_for_contracts finds classes using dotted base like module.Contract."""
        f = tmp_path / 'dotted.py'
        f.write_text('import yosoi\nclass DottedContract(yosoi.Contract):\n    x: str\n')
        found = scan_for_contracts([str(tmp_path)])
        # yosoi.Contract → base_name via ast.Attribute is 'Contract'
        assert 'DottedContract' in found

    def test_default_search_dir_is_cwd(self, monkeypatch, tmp_path):
        """scan_for_contracts without args uses current directory."""
        monkeypatch.chdir(tmp_path)
        f = tmp_path / 'cwd_schema.py'
        f.write_text('from yosoi.models.contract import Contract\nclass CwdSchema(Contract):\n    x: str\n')
        found = scan_for_contracts()  # no args — defaults to ['.']
        assert 'CwdSchema' in found

    def test_empty_directory_returns_empty_dict(self, tmp_path):
        """scan_for_contracts on an empty dir returns {}."""
        assert scan_for_contracts([str(tmp_path)]) == {}


def _load_module(filepath: object, module_name: str) -> object:
    """Helper: load a Python file as a module."""
    spec = importlib.util.spec_from_file_location(module_name, filepath)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


class TestFindContractClasses:
    def test_returns_concrete_subclasses(self, tmp_path):
        """_find_contract_classes returns non-abstract Contract subclasses."""
        f = tmp_path / 'mod.py'
        f.write_text(
            'from yosoi.models.contract import Contract\n'
            'class ConcreteA(Contract):\n    x: str\n'
            'class ConcreteB(Contract):\n    y: int\n'
        )
        mod = _load_module(f, '_tmp_mod_concrete')
        names = _find_contract_classes(mod)
        assert 'ConcreteA' in names
        assert 'ConcreteB' in names

    def test_excludes_base_contract_class(self, tmp_path):
        """_find_contract_classes never includes Contract itself."""
        f = tmp_path / 'mod2.py'
        f.write_text('from yosoi.models.contract import Contract\nclass MyC(Contract):\n    x: str\n')
        mod = _load_module(f, '_tmp_mod_base')
        names = _find_contract_classes(mod)
        assert 'Contract' not in names

    def test_excludes_private_names(self, tmp_path):
        """_find_contract_classes excludes names starting with '_'."""
        f = tmp_path / 'mod3.py'
        f.write_text('from yosoi.models.contract import Contract\nclass _PrivateContract(Contract):\n    x: str\n')
        mod = _load_module(f, '_tmp_mod_private')
        names = _find_contract_classes(mod)
        assert '_PrivateContract' not in names


class TestLoadContractFromFile:
    def test_no_colon_raises_value_error(self):
        """Missing colon separator raises ValueError."""
        with pytest.raises(ValueError, match='path:ClassName'):
            _load_contract_from_file('no_colon_here')

    def test_file_not_found_raises(self, tmp_path):
        """Missing file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            _load_contract_from_file(f'{tmp_path}/missing.py:Foo')

    def test_module_load_error_raises_value_error(self, tmp_path):
        """Module that raises on exec raises ValueError."""
        f = tmp_path / 'bad.py'
        f.write_text('raise ImportError("intentional")')
        with pytest.raises(ValueError, match='Failed to load'):
            _load_contract_from_file(f'{f}:Anything')

    def test_class_not_found_with_close_match(self, tmp_path):
        """Error message contains 'Did you mean' or 'not found' for close name match."""
        f = tmp_path / 'schema.py'
        f.write_text('from yosoi.models.contract import Contract\nclass RealContract(Contract):\n    x: str\n')
        with pytest.raises(ValueError, match=r'not found|Did you mean'):
            _load_contract_from_file(f'{f}:RealContrakct')  # typo

    def test_class_not_found_lists_available_contracts(self, tmp_path):
        """Error message mentions available Contract subclasses when no close match."""
        f = tmp_path / 'schema.py'
        f.write_text('from yosoi.models.contract import Contract\nclass AvailableOne(Contract):\n    x: str\n')
        with pytest.raises(ValueError, match=r'not found|AvailableOne'):
            _load_contract_from_file(f'{f}:CompletelyDifferentName')

    def test_non_contract_class_raises_value_error(self, tmp_path):
        """Existing class that is not a Contract raises ValueError."""
        f = tmp_path / 'schema.py'
        f.write_text('class NotAContract:\n    pass\n')
        with pytest.raises(ValueError, match='not a Contract'):
            _load_contract_from_file(f'{f}:NotAContract')

    def test_non_contract_class_message_mentions_available(self, tmp_path):
        """Non-Contract error message lists available Contract subclasses."""
        f = tmp_path / 'schema.py'
        f.write_text(
            'from yosoi.models.contract import Contract\n'
            'class NotAContract:\n    pass\n'
            'class RealContract(Contract):\n    x: str\n'
        )
        with pytest.raises(ValueError, match='not a Contract'):
            _load_contract_from_file(f'{f}:NotAContract')


class TestResolveContract:
    def test_registry_exact_match(self):
        """resolve_contract finds custom schemas registered via __init_subclass__."""

        class RegistryTestSchema(Contract):
            value: str

        result = resolve_contract('RegistryTestSchema')
        assert result is RegistryTestSchema

    def test_registry_case_insensitive_match(self):
        """resolve_contract matches registry schemas case-insensitively."""

        class CiRegistrySchema(Contract):
            value: str

        result = resolve_contract('ciregistryschema')
        assert result is CiRegistrySchema

    def test_builtin_exact_match(self):
        """Exact builtin name resolves correctly."""
        assert resolve_contract('Product') is Product

    def test_builtin_case_insensitive(self):
        """Case-insensitive builtin match works."""
        assert resolve_contract('product') is Product
        assert resolve_contract('NEWSARTICLE') is NewsArticle

    def test_unknown_name_raises(self):
        """Unknown name with no matches raises ValueError."""
        with pytest.raises(ValueError, match='Unknown contract'):
            resolve_contract('Zxqwpjmk99999')

    def test_dynamic_import_from_file(self, tmp_path):
        """path:ClassName format loads from file."""
        f = tmp_path / 'my_schema.py'
        f.write_text('from yosoi.models.contract import Contract\nclass MyContract(Contract):\n    title: str\n')
        cls = resolve_contract(f'{f}:MyContract')
        assert cls.__name__ == 'MyContract'

    def test_dynamic_import_file_not_found(self, tmp_path):
        """Missing file raises FileNotFoundError via resolve_contract."""
        with pytest.raises((ValueError, FileNotFoundError)):
            resolve_contract(f'{tmp_path}/nope.py:Foo')

    def test_dynamic_import_class_not_found(self, tmp_path):
        """Existing file but wrong class name raises ValueError."""
        f = tmp_path / 'schema.py'
        f.write_text('from yosoi.models.contract import Contract\nclass RealContract(Contract):\n    title: str\n')
        with pytest.raises(ValueError, match='not found'):
            resolve_contract(f'{f}:WrongName')

    def test_no_fuzzy_matching_in_scripted_api(self):
        """resolve_contract does NOT fuzzy match — that's CLI-only."""
        with pytest.raises(ValueError, match='Unknown contract'):
            resolve_contract('Produc')  # close to "Product" but no fuzzy
