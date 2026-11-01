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

    def test_public_classes_expand_only_authored_same_module_members(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "package"
            package.mkdir()
            (package / "__init__.py").write_text(
                "from .media import ImageDocument as ImageDocument\n"
                "from .media import VideoDocument as VideoDocument\n"
                "from .media import AudioDocument as AudioDocument\n"
                "from .media import BinaryDocument as BinaryDocument\n"
                '__all__ = ["ImageDocument", "VideoDocument", "AudioDocument", "BinaryDocument"]\n'
            )
            (package / "media.py").write_text(
                '''from pydantic import BaseModel, Field
from typing import Self

class _FileDocument(BaseModel):
    """Shared authored file document API."""
    id: str = Field(description="Stable file identity.")
    metadata: dict = Field(description="File provenance and digest.")

    @classmethod
    def from_bytes(cls, content: bytes) -> Self:
        """Retain exact file bytes without decoding."""
        raise NotImplementedError

    @property
    def bytes(self) -> bytes:
        """Return exact retained bytes."""
        raise NotImplementedError

class ImageDocument(_FileDocument):
    """Image file with no decoder assumptions."""

class VideoDocument(_FileDocument):
    """Video file with no decoder assumptions."""

    @classmethod
    def from_bytes(cls, content: bytes, *, profile: str = "opaque") -> Self:
        """Retain video bytes with a video-specific profile."""
        raise NotImplementedError

class AudioDocument(_FileDocument):
    """Audio file with no decoder assumptions."""

class BinaryDocument(_FileDocument):
    """Opaque file with no decoder assumptions."""
'''
            )
            output = root / "docs"
            reference.render_reference(package, output, "b" * 40, "CascadingLabs/Yosoi")

            for name in ("ImageDocument", "AudioDocument", "BinaryDocument"):
                page = (output / f"media/types/{reference.slug(name)}.md").read_text()
                self.assertIn("id: str = Field(description='Stable file identity.')", page)
                self.assertIn(
                    "metadata: dict = Field(description='File provenance and digest.')",
                    page,
                )
                self.assertIn("Return exact retained bytes.", page)
                self.assertIn("Retain exact file bytes without decoding.", page)
                self.assertIn(
                    f"def from_bytes(cls: type[{name}], content: bytes) -> {name}:",
                    page,
                )
                self.assertIn("/python/yosoi/media.py#L7-", page)
                self.assertNotIn("model_dump", page)
                self.assertNotIn("def __init__", page)

            video = (output / "media/types/video-document.md").read_text()
            self.assertIn("Retain video bytes with a video-specific profile.", video)
            self.assertIn(
                "def from_bytes(cls: type[VideoDocument], content: bytes, *, profile: str='opaque') -> VideoDocument:",
                video,
            )
            self.assertNotIn("Retain exact file bytes without decoding.", video)

    def test_same_module_inheritance_uses_c3_override_order_and_rejects_inconsistent_mro(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "diamond"
            package.mkdir()
            (package / "__init__.py").write_text(
                "from .types import D as D\n__all__ = [\"D\"]\n"
            )
            (package / "types.py").write_text(
                '''class A:
    def value(self) -> str:
        """Value from the oldest base."""
        raise NotImplementedError

class B(A):
    pass

class C(A):
    def value(self) -> str:
        """Value from the later C3 base."""
        raise NotImplementedError

class D(B, C):
    pass
'''
            )
            output = root / "docs"
            reference.render_reference(package, output, "c" * 40, "CascadingLabs/Yosoi")
            diamond = (output / "types/types/d.md").read_text()
            self.assertIn("Value from the later C3 base.", diamond)
            self.assertNotIn("Value from the oldest base.", diamond)
            self.assertIn("/python/yosoi/types.py#L10-", diamond)

            inconsistent = root / "inconsistent"
            inconsistent.mkdir()
            (inconsistent / "__init__.py").write_text(
                "from .types import C as C\n__all__ = [\"C\"]\n"
            )
            (inconsistent / "types.py").write_text(
                '''class X:
    pass

class Y:
    pass

class A(X, Y):
    pass

class B(Y, X):
    pass

class C(A, B):
    pass
'''
            )
            with self.assertRaisesRegex(
                ValueError, "Inconsistent same-module inheritance order for types.C"
            ):
                reference.render_reference(
                    inconsistent,
                    root / "invalid-docs",
                    "d" * 40,
                    "CascadingLabs/Yosoi",
                )


if __name__ == "__main__":
    unittest.main()
