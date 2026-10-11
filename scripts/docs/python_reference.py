"""Generate public Python reference Markdown without importing the native SDK."""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path


def slug(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z][a-z])", "-", name).replace("_", "-").lower()


def inline(value: str) -> str:
    return value.replace("\n", " ").replace("|", "\\|")


def signature(node: ast.AST) -> str:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
        parameters = (
            "[" + ", ".join(ast.unparse(p) for p in node.type_params) + "]"
            if node.type_params
            else ""
        )
        result = f"{prefix}def {node.name}{parameters}({ast.unparse(node.args)})"
        if node.returns:
            result += f" -> {ast.unparse(node.returns)}"
        decorators = [ast.unparse(d) for d in node.decorator_list]
        visible = [
            f"@{d}"
            for d in decorators
            if d in {"classmethod", "staticmethod", "property"}
        ]
        return "\n".join([*visible, result + ":"])
    if isinstance(node, ast.ClassDef):
        bases = ", ".join(
            [
                *(ast.unparse(base) for base in node.bases),
                *(ast.unparse(keyword) for keyword in node.keywords),
            ]
        )
        parameters = (
            "[" + ", ".join(ast.unparse(p) for p in node.type_params) + "]"
            if node.type_params
            else ""
        )
        return f"class {node.name}{parameters}" + (f"({bases})" if bases else "") + ":"
    return ast.unparse(node)


def definition_name(node: ast.AST) -> str | None:
    if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        return node.name
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    if (
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    ):
        return node.targets[0].id
    if isinstance(node, ast.TypeAlias) and isinstance(node.name, ast.Name):
        return node.name.id
    return None


def category(node: ast.AST) -> str:
    if isinstance(node, ast.ClassDef):
        return "types"
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return "functions"
    return (
        "aliases"
        if isinstance(node, ast.TypeAlias) or not definition_name(node).isupper()
        else "constants"
    )


def render_reference(package: Path, output: Path, source: str, repository: str) -> int:
    modules = {}
    for file in sorted(package.glob("*.py")):
        if file.stem.startswith("_") and file.stem != "__init__":
            continue
        modules[file.stem] = (file, ast.parse(file.read_text(encoding="utf-8")))
    if "__init__" not in modules:
        raise ValueError("Python package __init__.py is required")
    symbols = {}
    for module, (file, tree) in modules.items():
        if module == "__init__":
            continue
        for node in tree.body:
            name = definition_name(node)
            if name and not name.startswith("_") and name not in {"T", "K", "V"}:
                symbols[(module, name)] = (
                    file,
                    node,
                    f"python-api/{slug(module)}/{category(node)}/{slug(name)}",
                )
    aliases = {}
    for module, (_, tree) in modules.items():
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
                for item in node.names:
                    aliases[(module, item.asname or item.name)] = (
                        node.module,
                        item.name,
                    )

    def resolve(module, name):
        visited = set()
        key = (module, name)
        while key in aliases and key not in visited:
            visited.add(key)
            key = aliases[key]
        return symbols.get(key)

    def href(route):
        return f"/yosoi/{route}/"

    def source_link(file, node):
        relative = f"python/yosoi/{file.name}"
        line = getattr(node, "lineno", 1)
        end = getattr(node, "end_lineno", line)
        return f"[Source: {relative}:{line}](https://github.com/{repository}/blob/{source}/{relative}#L{line}-L{end})"

    written = set()

    def write(route, title, description, body):
        relative = route.removeprefix("python-api").lstrip("/")
        file = output / (relative + ".md" if relative else "index.md")
        file.parent.mkdir(parents=True, exist_ok=True)
        if file in written:
            raise ValueError(f"Duplicate Python reference route: {route}")
        written.add(file)
        frontmatter = (
            f"---\ntitle: {json.dumps(title)}\n"
            f"description: {json.dumps(description)}\norder: 0\n---\n\n"
        )
        file.write_text(frontmatter + body.rstrip() + "\n", encoding="utf-8")

    def table(rows):
        return "\n".join(["| Name | Summary |", "| --- | --- |", *rows])

    def summary(node):
        doc = (
            ast.get_docstring(node)
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            else None
        )
        return inline(doc.split("\n\n")[0]) if doc else "—"

    for (module, name), (file, node, route) in symbols.items():
        public_path = f"yosoi.{module}.{name}"
        parts = [f"`{public_path}`", "", "```python", signature(node), "```", ""]
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            parts += [
                ast.get_docstring(node)
                or "This declaration does not currently have a docstring.",
                "",
            ]
        parts += [source_link(file, node), ""]
        if isinstance(node, ast.ClassDef):
            fields = [
                n
                for n in node.body
                if isinstance(n, (ast.Assign, ast.AnnAssign))
                and (definition_name(n) or "").strip()
                and not definition_name(n).startswith("_")
            ]
            methods = [
                n
                for n in node.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and (
                    not n.name.startswith("_")
                    or n.name
                    in {
                        "__init__",
                        "__enter__",
                        "__exit__",
                        "__aenter__",
                        "__aexit__",
                        "__call__",
                        "__iter__",
                        "__aiter__",
                        "__next__",
                        "__anext__",
                        "__str__",
                    }
                )
            ]
            bases = [
                (ast.unparse(base), resolve(module, ast.unparse(base)))
                for base in node.bases
            ]
            linked = [f"[{name}]({href(item[2])})" for name, item in bases if item]
            if linked:
                parts += ["## Base classes", "", ", ".join(linked), ""]
            parts += [
                "Members below are declared on this class. Inherited Pydantic methods "
                "and generated constructor signatures are not expanded.",
                "",
            ]
            if fields:
                parts += [
                    "## Fields and class attributes",
                    "",
                    "```python",
                    "\n".join(signature(n) for n in fields),
                    "```",
                    "",
                ]
            if methods:
                parts += ["## Methods", ""]
            for method in methods:
                parts += [
                    f"### {method.name}",
                    "",
                    "```python",
                    signature(method),
                    "```",
                    "",
                    ast.get_docstring(method) or "",
                    "",
                    source_link(file, method),
                    "",
                ]
        write(route, name, f"{public_path} Python API reference.", "\n".join(parts))

    for module, (file, tree) in modules.items():
        if module == "__init__":
            continue
        module_route = f"python-api/{slug(module)}"
        overview = [
            f"`yosoi.{module}`",
            "",
            ast.get_docstring(tree) or "",
            "",
            source_link(file, tree),
            "",
        ]
        for kind, label in [
            ("types", "Types"),
            ("functions", "Functions"),
            ("aliases", "Aliases"),
            ("constants", "Constants"),
        ]:
            items = [
                (name, value)
                for (owner, name), value in symbols.items()
                if owner == module and category(value[1]) == kind
            ]
            if not items:
                continue
            rows = [
                f"| [`{name}`]({href(value[2])}) | {summary(value[1])} |"
                for name, value in sorted(items)
            ]
            overview += [f"## {label}", "", table(rows), ""]
            write(
                f"{module_route}/{kind}/index",
                label,
                f"{label} declared in yosoi.{module}.",
                table(rows),
            )
        write(
            f"{module_route}/index",
            f"yosoi.{module}",
            f"Public declarations in yosoi.{module}.",
            "\n".join(overview),
        )

    root_file, root_tree = modules["__init__"]
    public = next(
        ast.literal_eval(n.value)
        for n in root_tree.body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "__all__" for t in n.targets)
    )
    rows = []
    for name in sorted(public):
        symbol = resolve("__init__", name)
        if symbol:
            rows.append(f"| [`ys.{name}`]({href(symbol[2])}) | {summary(symbol[1])} |")
        elif name in modules:
            rows.append(
                f"| [`ys.{name}`]({href(f'python-api/{slug(name)}')}) | Module |"
            )
        elif name == "__version__":
            rows.append("| `ys.__version__` | Installed distribution version |")
        else:
            raise ValueError(f"Unresolved public Python export: {name}")
    intro = [
        "Use `import yosoi as ys`. Browse modules, then Types, Functions, Aliases, "
        "or Constants. Each symbol has its own page.",
        "",
        "This reference is generated from public Python source declarations without "
        "importing or executing the native extension. Signatures preserve Python "
        "annotations, defaults, and async declarations. Class pages show declared "
        "fields and methods; inherited or dynamically generated members are not "
        "expanded.",
        "",
        "## Package exports",
        "",
        table(rows),
        "",
        "## Modules",
        "",
        *[
            f"- [`yosoi.{module}`]({href(f'python-api/{slug(module)}')})"
            for module in modules
            if module != "__init__"
        ],
        "",
        source_link(root_file, root_tree),
    ]
    write(
        "python-api",
        "Python reference",
        "Public Python modules, types, functions, and source declarations.",
        "\n".join(intro),
    )
    return len(written)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--repository", default="CascadingLabs/Yosoi")
    args = parser.parse_args()
    count = render_reference(args.package, args.out, args.source, args.repository)
    print(f"Generated {count} Python API pages.")
