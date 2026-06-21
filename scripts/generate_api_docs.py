"""Generate API reference markdown from the yosoi public API.

Uses griffe for static analysis — no need to import the package or install
optional deps. Parses Google-style docstrings into structured sections.
Only symbols listed in yosoi.__all__ are included (unless passed via --exclude).

Each symbol heading includes a linked GitHub source icon pointing to the
exact line in the repository.

Usage:
    # Single combined file (legacy):
    uv run python scripts/generate_api_docs.py --output api-reference.md

    # Split into 4 files (classes/functions/types/helpers):
    uv run python scripts/generate_api_docs.py --output-dir ../CascadingLabsFE/docs/yosoi-docs/reference

    uv run python scripts/generate_api_docs.py --exclude Pipeline,LLMConfig --output api-reference.md
"""

from __future__ import annotations

import argparse
import difflib
import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import griffe

if TYPE_CHECKING:
    from griffe import Class, Function, Object

# ---------------------------------------------------------------------------
# GitHub source link
# ---------------------------------------------------------------------------

_GITHUB_ICON = (
    '<svg aria-hidden="true" height="14" viewBox="0 0 16 16" version="1.1" width="14" '
    'xmlns="http://www.w3.org/2000/svg" style="vertical-align:-2px;display:inline-block">'
    '<path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38'
    ' 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15'
    '-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07'
    '-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21'
    ' 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16'
    ' 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0'
    ' 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/>'
    '</svg>'
)

_REPO_ROOT = Path(__file__).parent.parent


def _current_git_ref() -> str:
    """Return the current commit SHA for stable latest-docs source links."""
    result = subprocess.run(
        ['git', 'rev-parse', 'HEAD'],
        cwd=_REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _source_path_exists_at_ref(ref: str, rel_path: str) -> bool:
    """Return True when rel_path exists at ref, preserving git's case sensitivity."""
    result = subprocess.run(
        ['git', 'cat-file', '-e', f'{ref}:{rel_path}'],
        cwd=_REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _source_text_at_ref(ref: str, rel_path: str) -> str:
    """Return file content at ref:path."""
    result = subprocess.run(
        ['git', 'show', f'{ref}:{rel_path}'],
        cwd=_REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _validate_source_links(content: str, repo_url: str, ref: str) -> None:
    """Validate generated GitHub source links against the local git database."""
    link_pattern = re.compile(rf'href="{re.escape(repo_url)}/blob/{re.escape(ref)}/([^"#]+)(?:#L(\d+))?"')
    heading_pattern = re.compile(
        rf'^\#\#\#? `([^`]+)`.*?href="{re.escape(repo_url)}/blob/{re.escape(ref)}/([^"#]+)(?:#L(\d+))?"',
        re.MULTILINE,
    )
    missing = sorted(
        {path for path, _line in link_pattern.findall(content) if not _source_path_exists_at_ref(ref, path)}
    )
    if missing:
        joined = '\n'.join(f'  - {path}' for path in missing)
        raise SystemExit(f'Source link validation failed for ref {ref}:\n{joined}')
    bad_lines: list[str] = []
    for name, path, line in heading_pattern.findall(content):
        if not line:
            continue
        lines = _source_text_at_ref(ref, path).splitlines()
        lineno = int(line)
        source_line = lines[lineno - 1].strip() if 0 < lineno <= len(lines) else ''
        if not re.match(rf'(async\s+def|def|class)\s+{re.escape(name)}\b', source_line):
            bad_lines.append(f'  - {path}#L{lineno}: {source_line}')
    if bad_lines:
        joined = '\n'.join(bad_lines)
        raise SystemExit(f'Source link line validation failed for ref {ref}:\n{joined}')


def _declaration_lineno(obj: Object, rel: Path) -> int | None:
    """Find the concrete def/class line for a griffe object."""
    lineno = getattr(obj, 'lineno', None)
    if not lineno:
        return None
    source_path = _REPO_ROOT / rel
    if not source_path.exists():
        return lineno
    name = getattr(obj, 'name', '')
    keyword = 'class' if isinstance(obj, griffe.Class) else r'(?:async\s+def|def)'
    pattern = re.compile(rf'^\s*{keyword}\s+{re.escape(name)}\b')
    lines = source_path.read_text().splitlines()
    start = max(lineno - 8, 0)
    stop = min((getattr(obj, 'endlineno', None) or lineno) + 8, len(lines))
    for index in range(start, stop):
        if pattern.match(lines[index]):
            return index + 1
    return None


def _line_is_declaration_at_ref(ref: str, rel: Path, lineno: int, name: str) -> bool:
    """Return True when ref:path#Llineno points at a declaration."""
    rel_path = rel.as_posix()
    if not _source_path_exists_at_ref(ref, rel_path):
        return False
    lines = _source_text_at_ref(ref, rel_path).splitlines()
    source_line = lines[lineno - 1].strip() if 0 < lineno <= len(lines) else ''
    return bool(re.match(rf'(async\s+def|def|class)\s+{re.escape(name)}\b', source_line))


def _check_file(path: Path, expected: str) -> None:
    """Exit non-zero when path does not match expected content."""
    if not path.exists():
        raise SystemExit(f'Generated API reference is missing: {path}')
    actual = path.read_text()
    if actual == expected:
        print(f'OK: {path}')
        return
    diff = ''.join(
        difflib.unified_diff(
            actual.splitlines(keepends=True),
            expected.splitlines(keepends=True),
            fromfile=str(path),
            tofile=f'{path} (generated)',
        )
    )
    sys.stderr.write(diff)
    raise SystemExit(f'Generated API reference is out of date: {path}')


def _gh_link(obj: Object, repo_url: str, ref: str) -> str:
    """Return an inline HTML GitHub source link for the given object, or '' if unavailable."""
    filepath = getattr(obj, 'filepath', None)
    if not filepath:
        return ''
    try:
        rel = Path(filepath).relative_to(_REPO_ROOT)
    except ValueError:
        return ''
    lineno = _declaration_lineno(obj, rel)
    if not lineno:
        return ''
    name = getattr(obj, 'name', '')
    if not _line_is_declaration_at_ref(ref, rel, lineno, name):
        return ''
    url = f'{repo_url}/blob/{ref}/{rel.as_posix()}#L{lineno}'
    return (
        f' <a href="{url}" target="_blank" rel="noopener noreferrer" title="View source on GitHub">{_GITHUB_ICON}</a>'
    )


# ---------------------------------------------------------------------------
# Docstring rendering
# ---------------------------------------------------------------------------


def _render_docstring(obj: Object) -> str:
    """Render a griffe docstring as markdown, including Args/Returns/Yields."""
    if not obj.docstring:
        return ''

    parsed = obj.docstring.parse('google')
    parts: list[str] = []

    for section in parsed:
        kind = section.kind.value  # e.g. 'text', 'parameters', 'returns', 'yields', 'raises'

        if kind == 'text':
            parts.append(str(section.value).strip())

        elif kind == 'parameters':
            parts.append('**Args:**\n')
            for param in section.value:
                ann = f'`{param.annotation}`' if param.annotation else ''
                desc = param.description.strip() if param.description else ''
                parts.append(f'- `{param.name}` {ann} — {desc}')
            parts.append('')

        elif kind in ('returns', 'yields'):
            label = 'Returns' if kind == 'returns' else 'Yields'
            items = section.value if isinstance(section.value, list) else [section.value]
            descs = [(f'`{i.annotation}` — ' if i.annotation else '') + (i.description or '') for i in items]
            parts.append(f'**{label}:** {" ".join(descs)}'.strip())
            parts.append('')

        elif kind == 'raises':
            parts.append('**Raises:**\n')
            for exc in section.value:
                desc = exc.description.strip() if exc.description else ''
                parts.append(f'- `{exc.annotation}` — {desc}')
            parts.append('')

    return '\n'.join(parts).strip()


# ---------------------------------------------------------------------------
# Signature rendering
# ---------------------------------------------------------------------------


def _render_params(fn: Function) -> str:
    """Render function parameters, dropping self/cls."""
    params = [p for p in fn.parameters if p.name not in ('self', 'cls')]
    parts: list[str] = []
    for p in params:
        ann = f': {p.annotation}' if p.annotation else ''
        default = f' = {p.default}' if p.default is not None else ''
        parts.append(f'{p.name}{ann}{default}')
    ret = f' -> {fn.returns}' if fn.returns else ''
    return f'({", ".join(parts)}){ret}'


# ---------------------------------------------------------------------------
# Class / function formatters
# ---------------------------------------------------------------------------


def _format_function(name: str, obj: Function, link: str) -> list[str]:
    """Format a top-level function as markdown."""
    sig = _render_params(obj)
    lines = [f'## `{name}`{link}\n', f'`{name}{sig}`\n']
    doc = _render_docstring(obj)
    if doc:
        lines.append(doc)
        lines.append('')
    return lines


def _format_class(name: str, obj: Class, exclude: set[str], link: str, repo_url: str, ref: str) -> list[str]:
    """Format a class and its own public methods as markdown."""
    lines = [f'## `{name}`{link}\n']
    doc = _render_docstring(obj)
    if doc:
        lines.append(doc)
        lines.append('')

    # Only methods defined directly on this class (not inherited)
    for mname, member in sorted(obj.members.items()):
        if mname.startswith('_') or mname in exclude:
            continue
        if member.is_alias:
            continue  # skip re-exports / inherited aliases
        if not isinstance(member, griffe.Function):
            continue
        mlink = _gh_link(member, repo_url, ref)
        sig = _render_params(member)
        lines.append(f'### `{mname}`{mlink}\n')
        lines.append(f'`{mname}{sig}`\n')
        mdoc = _render_docstring(member)
        if mdoc:
            lines.append(mdoc)
            lines.append('')

    return lines


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------


def _simple_entry(name: str, target: Object, link: str) -> list[str]:
    """Render a single-line entry (function/factory/provider) as markdown."""
    sig = _render_params(target) if isinstance(target, griffe.Function) else '(...)'
    doc = _render_docstring(target)
    lines = [f'## `{name}`{link}\n', f'`{name}{sig}`\n']
    if doc:
        lines.append(doc)
        lines.append('')
    return lines


def _classify(
    name: str,
    target: Object,
    exclude: set[str],
    sections: dict[str, list[str]],
    repo_url: str,
    ref: str,
) -> None:
    """Route a public symbol into the correct section."""
    link = _gh_link(target, repo_url, ref)
    if name in _SELECTOR_CACHE_TYPES:
        if isinstance(target, griffe.Class):
            sections['Selector Cache'].extend(_format_class(name, target, exclude, link, repo_url, ref))
        else:
            sections['Selector Cache'].extend(_simple_entry(name, target, link))
    elif name in _TYPE_FACTORIES:
        sections['Types'].extend(_simple_entry(name, target, link))
    elif name in _PROVIDER_HELPERS:
        sections['Helpers'].extend(_simple_entry(name, target, link))
    elif name in _SELECTOR_HELPERS or isinstance(target, griffe.Function):
        sections['Functions'].extend(_format_function(name, target, link))  # type: ignore[arg-type]
    elif isinstance(target, griffe.Class):
        sections['Classes'].extend(_format_class(name, target, exclude, link, repo_url, ref))


# Known groupings — extend as the public API grows
_TYPE_FACTORIES = {'Author', 'BodyText', 'Datetime', 'Field', 'Price', 'Rating', 'Title', 'Url'}
_PROVIDER_HELPERS = {
    'alibaba',
    'anthropic',
    'azure',
    'bedrock',
    'cerebras',
    'deepseek',
    'fireworks',
    'gemini',
    'github',
    'grok',
    'groq',
    'heroku',
    'huggingface',
    'litellm',
    'mistral',
    'moonshotai',
    'nebius',
    'ollama',
    'openai',
    'openrouter',
    'ovhcloud',
    'provider',
    'sambanova',
    'together',
    'vercel',
    'vertexai',
    'xai',
}
_SELECTOR_HELPERS = {'css', 'xpath', 'regex', 'jsonld', 'discover'}
_SELECTOR_CACHE_TYPES = {
    'CacheVerdict',
    'FieldSelectors',
    'SelectorEntry',
    'SelectorLevel',
    'SelectorSnapshot',
    'SnapshotMap',
}

# Map section key → (output filename, page title, description template)
_SECTION_FILES = {
    'Classes': ('classes.md', 'Classes', 'Class reference for yosoi {version}'),
    'Functions': ('functions.md', 'Functions', 'Function reference for yosoi {version}'),
    'Types': ('types.md', 'Types', 'Type factory reference for yosoi {version}'),
    'Helpers': ('helpers.md', 'Provider Helpers', 'Provider helper reference for yosoi {version}'),
    'Selector Cache': (
        'selector-cache.md',
        'Selector Cache Types',
        'Selector cache type reference for yosoi {version}',
    ),
}


def _build_sections(version: str, exclude: set[str], repo_url: str, ref: str) -> dict[str, list[str]]:
    """Load the package and populate per-section content lists."""
    pkg = griffe.load('yosoi')

    init = pkg
    public_names: list[str] = []
    if '__all__' in init.members:
        all_obj = init.members['__all__']
        raw = str(all_obj.value) if hasattr(all_obj, 'value') else ''
        public_names = re.findall(r"'([^']+)'", raw)

    if not public_names:
        public_names = [n for n in init.members if not n.startswith('_')]

    sections: dict[str, list[str]] = {'Classes': [], 'Functions': [], 'Types': [], 'Helpers': [], 'Selector Cache': []}

    for name in sorted(public_names):
        if name in exclude or name not in pkg.members:
            continue
        obj = pkg.members[name]
        target = obj.final_target if obj.is_alias else obj
        _classify(name, target, exclude, sections, repo_url, ref)

    return sections


def generate_split(version: str, exclude: set[str], repo_url: str, ref: str) -> dict[str, str]:
    """Return {filename: content} for each of the 4 reference pages."""
    sections = _build_sections(version, exclude, repo_url, ref)
    result: dict[str, str] = {}

    for key, (filename, title, desc_tmpl) in _SECTION_FILES.items():
        description = desc_tmpl.format(version=version)
        content_lines = sections[key]
        parts: list[str] = [
            '---',
            f'title: {title}',
            f'description: {description}',
            '---',
            '',
            f'> Generated from yosoi `{version}`. Only symbols in `__all__` are listed.',
            '',
        ]
        parts.extend(content_lines)
        result[filename] = '\n'.join(parts) + '\n'

    return result


def generate(version: str, exclude: set[str], repo_url: str, ref: str) -> str:
    """Build the full combined API reference markdown for the given version."""
    sections = _build_sections(version, exclude, repo_url, ref)

    parts: list[str] = [
        '---',
        'title: API Reference',
        f'description: Full API reference for yosoi {version}',
        f'version: {version}',
        '---',
        '',
        '# API Reference',
        '',
        f'> Generated from yosoi `{version}`. Only symbols in `__all__` are listed.',
        '',
    ]

    for section_key, section_title in [
        ('Classes', 'Classes'),
        ('Functions', 'Functions'),
        ('Types', 'Type Factories'),
        ('Helpers', 'Provider Helpers'),
        ('Selector Cache', 'Selector Cache Types'),
    ]:
        content = sections[section_key]
        if not content:
            continue
        parts.append(f'## {section_title}\n')
        parts.extend(content)

    return '\n'.join(parts) + '\n'


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description='Generate yosoi API reference markdown.')
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument('--output', default='', help='Single output file path (legacy)')
    output_group.add_argument(
        '--output-dir',
        default='',
        help='Directory to write split reference files into; defaults to ../YosoiDocs/reference',
    )
    parser.add_argument('--check', action='store_true', help='Check committed docs output without writing files')
    parser.add_argument('--version', default='', help='Version string (e.g. v0.1.0)')
    parser.add_argument(
        '--exclude',
        default='',
        help='Comma-separated list of symbol names to exclude from the reference',
    )
    parser.add_argument(
        '--github-repo',
        default='https://github.com/CascadingLabs/Yosoi',
        help='GitHub repository base URL',
    )
    parser.add_argument(
        '--ref',
        default='',
        help='Git ref (tag/branch/commit) for source links; defaults to the current commit SHA',
    )
    args = parser.parse_args()

    exclude: set[str] = {s.strip() for s in args.exclude.split(',') if s.strip()}

    if not args.version:
        toml_path = Path(__file__).parent.parent / 'pyproject.toml'
        if toml_path.exists():
            text = toml_path.read_text()
            m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
            version = f'v{m.group(1)}' if m else 'unknown'
        else:
            version = 'unknown'
    else:
        version = args.version

    ref = args.ref or _current_git_ref()

    if args.output_dir or not args.output:
        files = generate_split(version, exclude, args.github_repo, ref)
        for content in files.values():
            _validate_source_links(content, args.github_repo, ref)
        out_dir = Path(args.output_dir or '../YosoiDocs/reference')
        if args.check:
            for filename, content in files.items():
                _check_file(out_dir / filename, content)
            return
        out_dir.mkdir(parents=True, exist_ok=True)
        total = 0
        for filename, content in files.items():
            dest = out_dir / filename
            dest.write_text(content)
            total += len(content)
            print(f'  Wrote {len(content):,} bytes → {dest}')
        print(f'Done. {total:,} bytes across {len(files)} files.')
    else:
        out_path = args.output or 'api-reference.md'
        content = generate(version, exclude, args.github_repo, ref)
        _validate_source_links(content, args.github_repo, ref)
        out = Path(out_path)
        if args.check:
            _check_file(out, content)
            return
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content)
        print(f'Wrote {len(content):,} bytes to {out}')


if __name__ == '__main__':
    main()
