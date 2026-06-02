"""Scan installed native extensions for *vendored* copyleft code.

`pip-licenses` (and `cargo-deny`) only see a package's **declared** license
metadata. They are blind to third-party C libraries statically linked into a
wheel's compiled ``.so`` — e.g. a wheel published as "MIT" can vendor LGPL
``libidn2`` into its extension module, and the metadata gate happily passes it.
This scanner closes that blind spot by grepping the actual shipped binaries for
copyleft fingerprints (GNU licence URLs, ``libidn2`` build paths, GPL/LGPL/AGPL
strings).

It is a coarse net, not a legal audit. C/Go bundles embed identifying strings
(source paths, ``gnu.org`` URLs), so a *hit* is reliable. Stripped Rust binaries
do **not** embed licence text — their crate metadata carries the licence — so the
*absence* of a hit is not proof of cleanliness. Pair this with the declared-metadata
gate (``poe licenses``); together they cover both layers.

MPL-2.0 is intentionally **not** flagged here: it is allowed by policy (weak,
file-level, only reaches us via unremovable transitive deps). This net targets the
copyleft families we will not ship — the GPL/LGPL/AGPL lineage, ``libidn2`` included.

Exit code 1 on any hit, 0 if clean. Wired into CI via ``poe licenses-binary``.
"""

from __future__ import annotations

import argparse
import re
import sys
import sysconfig
from collections.abc import Iterable
from pathlib import Path

# Each pattern is a string a copyleft component leaves in a compiled artifact.
_COPYLEFT_MARKERS: tuple[bytes, ...] = (
    rb'gnu\.org/licenses/l?gpl',
    rb'GNU (?:Lesser )?General Public License',
    rb'\blibidn2?\b',
    rb'idn2[-_][0-9]',
    rb'GPLv[23]',
    rb'LGPLv[23]',
    rb'\bAGPL',
)
_PATTERN = re.compile(b'|'.join(_COPYLEFT_MARKERS))
_BINARY_SUFFIXES = frozenset({'.so', '.dylib', '.pyd'})

# ELF and Mach-O magic bytes — covers Linux/Windows native executables and macOS binaries.
_ELF_MAGIC = b'\x7fELF'
_MACHO_MAGIC = frozenset(
    {
        b'\xfe\xed\xfa\xce',  # Mach-O 32-bit BE
        b'\xfe\xed\xfa\xcf',  # Mach-O 64-bit BE
        b'\xce\xfa\xed\xfe',  # Mach-O 32-bit LE
        b'\xcf\xfa\xed\xfe',  # Mach-O 64-bit LE
        b'\xca\xfe\xba\xbe',  # Mach-O fat binary
    }
)


def _is_native_executable(path: Path) -> bool:
    """Return True if path starts with ELF or Mach-O magic bytes."""
    try:
        header = path.read_bytes()[:4]
    except OSError:
        return False
    return header == _ELF_MAGIC or header in _MACHO_MAGIC


def _iter_binaries(roots: Iterable[Path]) -> Iterable[Path]:
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob('*'):
            if not path.is_file():
                continue
            if path.suffix in _BINARY_SUFFIXES or '.so.' in path.name:
                yield path
            elif not path.suffix and _is_native_executable(path):
                # Extensionless native executables from binary wheels (e.g. ruff, prek).
                yield path


def scan(roots: Iterable[Path], skip: Iterable[str] = ()) -> dict[Path, set[str]]:
    """Return a mapping of binary path -> set of copyleft markers found in it.

    ``skip`` is a sequence of path substrings; any binary whose str() contains one
    of them is excluded from the results.  Use it for known-acceptable copyleft
    binaries that are intentionally bundled by a dependency (e.g. a tool that ships
    its own AGPL CLI for convenience but does not infect yosoi's wheel).
    """
    skip_patterns = list(skip)
    hits: dict[Path, set[str]] = {}
    for path in _iter_binaries(roots):
        if any(s in str(path) for s in skip_patterns):
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        found = {m.group(0).decode('latin-1') for m in _PATTERN.finditer(data)}
        if found:
            hits[path] = found
    return hits


def main(argv: list[str] | None = None) -> int:
    """Scan ``roots`` (default: site-packages) and exit non-zero on any copyleft hit."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        'roots',
        nargs='*',
        type=Path,
        help="Directories to scan (default: this interpreter's site-packages).",
    )
    parser.add_argument(
        '--skip',
        metavar='PATTERN',
        action='append',
        default=[],
        help=(
            'Path substring to exclude from scanning.  Repeat for multiple patterns. '
            'Use for known-acceptable copyleft binaries that a dependency bundles as a '
            "convenience tool and that do not reach yosoi's own wheel."
        ),
    )
    args = parser.parse_args(argv)
    if args.roots:
        roots: list[Path] = args.roots
    else:
        # purelib = pure-Python packages; platlib = native extensions (.so/.pyd);
        # scripts = installed executables (extensionless CLI binaries like ruff).
        sp = sysconfig.get_paths()
        roots = list({Path(sp[k]) for k in ('purelib', 'platlib', 'scripts')})

    print(f'scanning native extensions under: {", ".join(map(str, roots))}')
    if args.skip:
        print(f'skipping path patterns: {", ".join(args.skip)}')
    hits = scan(roots, skip=args.skip)
    if not hits:
        print('OK: no copyleft fingerprints in any bundled binary')
        return 0

    print('FAIL: copyleft fingerprints found in bundled binaries:', file=sys.stderr)
    for path, markers in sorted(hits.items()):
        print(f'  {path}', file=sys.stderr)
        for marker in sorted(markers):
            print(f'      {marker}', file=sys.stderr)
    print(
        f"\n{len(hits)} binary(ies) carry copyleft fingerprints. Inspect the wheel's "
        'vendored sources before shipping (see scan_binary_licenses docstring).',
        file=sys.stderr,
    )
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
