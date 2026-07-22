See nested @AGENTS.md per subdir

Always use Context7 MCP when I need library/API documentation, code generation, setup or configuration steps without me having to explicitly ask. For Library IDs we use a lot of /pydantic/pydantic-ai and /pydantic/pydantic

use uv run python

consider poe tasks in pyproject.toml

we use uv run poe ci-check for static type checking and formatting. Run it before finishing

NEVER use unittest library, ever

## Lazy loading (package `__init__.py`)
- Package `__init__.py` files use PEP 562 lazy exports via `yosoi._lazy.lazy_exports`, so `import yosoi` (and any leaf module) stays in the low ms instead of eagerly pulling pydantic-ai / provider SDKs / parsel. Don't reintroduce eager `from .submodule import X` re-exports in a package `__init__`.
- Pattern: a `TYPE_CHECKING` block with `from x import Y as Y` (for Pyrefly/IDEs) + a `_LAZY = {name: "dotted.module"}` map + `__getattr__, __dir__ = lazy_exports(__name__, globals(), _LAZY)`. The top-level `yosoi/__init__.py` is also mirrored by `yosoi/__init__.pyi` — keep them in lockstep.
- Do NOT lazy-load: packages whose `__init__` has import side effects (e.g. `yosoi/types` registers coercions), and any export whose name equals a sibling submodule (e.g. `yosoi.cli.main` — the submodule would clobber the lazy binding). Keep those eager.
- See AGENTS.md "Lazy Loading" for the full rationale.
