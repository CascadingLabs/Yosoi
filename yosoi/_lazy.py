"""PEP 562 lazy package exports — keep ``import yosoi.*`` cheap.

Eager ``from .submodule import X`` in a package ``__init__`` forces every heavy
submodule to import whenever *anything* in (or under) that package is imported —
even a bare ``import yosoi`` or pulling one light leaf module. That dragged
``import yosoi`` to ~1.6s (pydantic-ai, the provider SDKs, parsel, …) and taxed
every short-lived subprocess.

Instead, a package ``__init__`` declares a ``name -> submodule`` map and installs
this helper. Names resolve on first attribute access; ``import package`` stays in
the low milliseconds. See ``CLAUDE.md`` ("Lazy loading") for the full convention.

Usage::

    from __future__ import annotations
    from typing import TYPE_CHECKING
    from yosoi._lazy import lazy_exports

    if TYPE_CHECKING:  # static typing only — no runtime cost
        from yosoi.foo.bar import Thing as Thing

    _LAZY = {'Thing': 'yosoi.foo.bar'}
    __all__ = ['Thing']
    __getattr__, __dir__ = lazy_exports(__name__, globals(), _LAZY)
"""

from __future__ import annotations

import importlib
from collections.abc import Callable


def lazy_exports(
    module_name: str,
    module_globals: dict[str, object],
    lazy_map: dict[str, str],
) -> tuple[Callable[[str], object], Callable[[], list[str]]]:
    """Return ``(__getattr__, __dir__)`` implementing lazy attribute resolution.

    Args:
        module_name: The package ``__name__`` (for error messages).
        module_globals: The package ``globals()`` — resolved names are cached here
            so each is imported at most once.
        lazy_map: Public name -> dotted submodule that defines it.

    Returns:
        A ``(__getattr__, __dir__)`` pair to assign at module scope.

    """

    def __getattr__(name: str) -> object:
        target = lazy_map.get(name)
        if target is None:
            raise AttributeError(f'module {module_name!r} has no attribute {name!r}')
        value = getattr(importlib.import_module(target), name)
        module_globals[name] = value  # cache: subsequent access skips __getattr__
        return value

    def __dir__() -> list[str]:
        return sorted(lazy_map)

    return __getattr__, __dir__
