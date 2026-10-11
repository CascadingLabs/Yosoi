from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "python_reference", Path(__file__).parents[1] / "python_reference.py"
)
reference = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reference)


class PythonReferenceTests(unittest.TestCase):
    def test_public_exports_source_signatures_and_declared_members_without_execution(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "package"
            package.mkdir()
            (package / "__init__.py").write_text(
                "from .sample import Item as Item, fetch as fetch\n"
                "from .bridge import PublicItem as PublicItem\n"
                '__all__ = ["Item", "fetch", "PublicItem"]\n'
            )
            (package / "bridge.py").write_text(
                "from . import sample as _implementation\n"
                "SharedItem = _implementation.Item\n"
                "PublicItem = SharedItem\n"
            )
            (package / "sample.py").write_text('''raise RuntimeError("must not import")

class Base:
    pass

class Item(Base):
    """A public item."""
    name: str
    quantity: int = 1
    _secret: str

    @classmethod
    def new(cls, name: str, /, *, quantity: int = 1) -> "Item":
        return cls()

    def _validate(self):
        pass

async def fetch[T](url: str, *, retries: int = 2) -> list[T]:
    """Fetch items."""
    return []

Unsigned = int
"""Unsigned values validated by their consuming field."""

Undocumented = int

def _private():
    pass
''')
            output = root / "docs"
            reference.render_reference(package, output, "a" * 40, "CascadingLabs/Yosoi")
            item = (output / "sample/types/item.md").read_text()
            self.assertIn("class Item(Base):", item)
            self.assertIn("name: str", item)
            self.assertIn("quantity: int = 1", item)
            self.assertIn(
                "@classmethod\ndef new(cls, name: str, /, *, quantity: int=1)", item
            )
            self.assertNotIn("_secret", item)
            self.assertNotIn("_validate", item)
            self.assertIn("/blob/" + "a" * 40 + "/python/yosoi/sample.py#L", item)
            self.assertIn("/yosoi/python-api/sample/types/base/", item)
            fetch = (output / "sample/functions/fetch.md").read_text()
            self.assertIn(
                "async def fetch[T](url: str, *, retries: int=2) -> list[T]:", fetch
            )
            self.assertFalse((output / "sample/functions/-private.md").exists())
            self.assertIn("ys.Item", (output / "index.md").read_text())
            alias = (output / "sample/aliases/unsigned.md").read_text()
            self.assertIn("Unsigned values validated by their consuming field.", alias)
            module = (output / "sample/index.md").read_text()
            self.assertIn("Unsigned values validated by their consuming field.", module)
            undocumented = (output / "sample/aliases/undocumented.md").read_text()
            self.assertNotIn("Unsigned values validated", undocumented)
            self.assertNotIn("does not currently have a docstring", undocumented)
            reexport = (output / "bridge/aliases/public-item.md").read_text()
            self.assertIn("A public item.", reexport)
            self.assertIn(
                "[Definition](/yosoi/python-api/sample/types/item/)", reexport
            )
            self.assertIn("/python/yosoi/sample.py#L", reexport)
            self.assertIn(
                "[`ys.PublicItem`](/yosoi/python-api/sample/types/item/)",
                (output / "index.md").read_text(),
            )

    def test_unresolved_root_export_fails_instead_of_silently_omitting_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "__init__.py").write_text('__all__ = ["Missing"]\n')
            with self.assertRaisesRegex(
                ValueError, "Unresolved public Python export: Missing"
            ):
                reference.render_reference(
                    root, root / "output", "main", "CascadingLabs/Yosoi"
                )


if __name__ == "__main__":
    unittest.main()
