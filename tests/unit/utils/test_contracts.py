"""Tests for yosoi.utils.contracts — resolve_contract (core logic, no CLI deps)."""

import pytest

from yosoi.models.defaults import NewsArticle, Product
from yosoi.utils.contracts import resolve_contract


class TestResolveContract:
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
