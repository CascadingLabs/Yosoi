"""Generate public Python reference Markdown without importing the native SDK."""

from __future__ import annotations

import argparse
import ast
import copy
import json
import re
from pathlib import Path


def slug(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z][a-z])", "-", name).replace("_", "-").lower()


def inline(value: str) -> str:
    return value.replace("\n", " ").replace("|", "\\|")


def _contains_self(node: ast.AST | None) -> bool:
    return node is not None and any(
        isinstance(child, ast.Name) and child.id == "Self" for child in ast.walk(node)
    )


def signature(node: ast.AST, concrete_class: str | None = None) -> str:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
        parameters = (
            "[" + ", ".join(ast.unparse(p) for p in node.type_params) + "]"
            if node.type_params
            else ""
        )
        decorators = [ast.unparse(d) for d in node.decorator_list]
        arguments = copy.deepcopy(node.args)
        returns = node.returns
        if concrete_class and "classmethod" in decorators and _contains_self(returns):
            positional = [*arguments.posonlyargs, *arguments.args]
            if positional and positional[0].arg == "cls":
                positional[0].annotation = ast.Subscript(
                    value=ast.Name(id="type", ctx=ast.Load()),
                    slice=ast.Name(id=concrete_class, ctx=ast.Load()),
                    ctx=ast.Load(),
                )
            if returns:
                returns = _specialize_self(returns, concrete_class)
        result = f"{prefix}def {node.name}{parameters}({ast.unparse(arguments)})"
        if returns:
            result += f" -> {ast.unparse(returns)}"
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


def _specialize_self(node: ast.AST, concrete_class: str) -> ast.AST:
    """Render an authored classmethod's Self annotation for its public subclass."""

    class SelfSpecializer(ast.NodeTransformer):
        def visit_Name(self, name: ast.Name) -> ast.AST:
            if name.id == "Self":
                return ast.copy_location(
                    ast.Name(id=concrete_class, ctx=name.ctx), name
                )
            return name

    return SelfSpecializer().visit(copy.deepcopy(node))


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
    # PEP 258 attribute docstrings belong to the preceding assignment or alias.
    # They provide source prose for declarations that cannot carry function or
    # class docstrings. Do not infer explanations from names or annotations.
    attribute_docs = {}
    for _, tree in modules.values():
        bodies = [tree.body]
        bodies.extend(node.body for node in tree.body if isinstance(node, ast.ClassDef))
        for body in bodies:
            for node, following in zip(body, body[1:], strict=False):
                if (
                    isinstance(node, (ast.Assign, ast.AnnAssign, ast.TypeAlias))
                    and isinstance(following, ast.Expr)
                    and isinstance(following.value, ast.Constant)
                    and isinstance(following.value.value, str)
                ):
                    attribute_docs[id(node)] = following.value.value.strip()

    def field_description(node):
        value = getattr(node, "value", None)
        if isinstance(value, ast.Call):
            for keyword in value.keywords:
                if (
                    keyword.arg == "description"
                    and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str)
                ):
                    return keyword.value.value
        return ""

    reexport_targets = {}

    def source_docs(node):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            return ast.get_docstring(node) or ""
        if id(node) in attribute_docs:
            return attribute_docs[id(node)]
        description = field_description(node)
        if description:
            return description
        target = reexport_targets.get(id(node))
        if target:
            definition = target[1]
            if isinstance(
                definition, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                return ast.get_docstring(definition) or ""
            return attribute_docs.get(id(definition), "")
        return ""

    class_definitions = {
        (module, node.name): (file, node)
        for module, (file, tree) in modules.items()
        for node in tree.body
        if isinstance(node, ast.ClassDef)
    }
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
    module_aliases = {}
    for module, (_, tree) in modules.items():
        for node in tree.body:
            if (
                isinstance(node, ast.ImportFrom)
                and node.level == 1
                and node.module is None
            ):
                for item in node.names:
                    if item.name in modules:
                        module_aliases[(module, item.asname or item.name)] = item.name
            if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
                for item in node.names:
                    aliases[(module, item.asname or item.name)] = (
                        node.module,
                        item.name,
                    )
    for module, (_, tree) in modules.items():
        for node in tree.body:
            name = definition_name(node)
            if not name or not isinstance(
                node, (ast.Assign, ast.AnnAssign, ast.TypeAlias)
            ):
                continue
            value = node.value
            if isinstance(value, ast.Name) and (module, value.id) in symbols:
                aliases[(module, name)] = (module, value.id)
            elif isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name):
                target_module = module_aliases.get((module, value.value.id))
                if target_module:
                    aliases[(module, name)] = (target_module, value.attr)

    def resolve(module, name):
        visited = set()
        key = (module, name)
        while key in aliases:
            if key in visited:
                return None
            visited.add(key)
            key = aliases[key]
        return symbols.get(key)

    def authored_class_members(module, root):
        """Collect authored members in a source-only C3 order for local bases."""
        members = []
        member_names = set()
        linearizations = {}

        def merge(sequences, class_name):
            result = []
            sequences = [sequence for sequence in sequences if sequence]
            while sequences:
                candidate = None
                for sequence in sequences:
                    head = sequence[0]
                    if not any(head in tail[1:] for tail in sequences):
                        candidate = head
                        break
                if candidate is None:
                    raise ValueError(
                        f"Inconsistent same-module inheritance order for "
                        f"{module}.{class_name}"
                    )
                result.append(candidate)
                remaining = []
                for sequence in sequences:
                    if sequence[0] == candidate:
                        sequence = sequence[1:]
                    if sequence:
                        remaining.append(sequence)
                sequences = remaining
            return result

        def linearize(class_node, visiting):
            key = ("local", module, class_node.name)
            if key in linearizations:
                return list(linearizations[key])
            if key in visiting:
                raise ValueError(
                    f"Cyclic same-module inheritance involving {module}.{class_node.name}"
                )
            visiting.add(key)
            direct_bases = []
            sequences = []
            for base in class_node.bases:
                local_base = (
                    class_definitions.get((module, base.id))
                    if isinstance(base, ast.Name)
                    else None
                )
                base_key = (
                    ("local", module, base.id)
                    if local_base
                    else ("external", ast.unparse(base))
                )
                if base_key in direct_bases:
                    raise ValueError(
                        f"Duplicate source base {ast.unparse(base)} "
                        f"in {module}.{class_node.name}"
                    )
                direct_bases.append(base_key)
                sequences.append(
                    linearize(local_base[1], visiting) if local_base else [base_key]
                )
            sequences.append(direct_bases.copy())
            order = (key, *merge(sequences, class_node.name))
            visiting.remove(key)
            linearizations[key] = order
            return list(order)

        for key in linearize(root, set()):
            if key[0] != "local":
                continue
            class_node = class_definitions[(key[1], key[2])][1]
            for member in class_node.body:
                if not isinstance(
                    member,
                    (ast.Assign, ast.AnnAssign, ast.FunctionDef, ast.AsyncFunctionDef),
                ):
                    continue
                name = definition_name(member)
                if not name or name in member_names:
                    continue
                member_names.add(name)
                members.append(member)
        return members

    for key, (_, node, _) in symbols.items():
        target = resolve(*key)
        if target and target[1] is not node:
            reexport_targets[id(node)] = target

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
        doc = source_docs(node)
        return inline(doc.split("\n\n")[0]) if doc else "—"

    for (module, name), (file, node, route) in symbols.items():
        public_path = f"yosoi.{module}.{name}"
        parts = [f"`{public_path}`", "", "```python", signature(node), "```", ""]
        if source_docs(node):
            parts += [source_docs(node), ""]
        parts += [source_link(file, node), ""]
        target = reexport_targets.get(id(node))
        if target:
            parts += [
                f"[Definition]({href(target[2])})",
                "",
                source_link(target[0], target[1]),
                "",
            ]
        if isinstance(node, ast.ClassDef):
            class_members = authored_class_members(module, node)
            fields = [
                n
                for n in class_members
                if isinstance(n, (ast.Assign, ast.AnnAssign))
                and (definition_name(n) or "").strip()
                and not definition_name(n).startswith("_")
            ]
            methods = [
                n
                for n in class_members
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
                "Members below are authored on this class or inherited from authored "
                "classes in the same module. External-base and dynamically generated "
                "members are not expanded.",
                "",
            ]
            if fields:
                parts += ["## Fields and class attributes", ""]
                for field in fields:
                    field_name = definition_name(field)
                    parts += [
                        f"### `{field_name}`",
                        "",
                        "```python",
                        signature(field),
                        "```",
                        "",
                    ]
                    if source_docs(field):
                        parts += [source_docs(field), ""]
                    parts += [source_link(file, field), ""]
            if methods:
                parts += ["## Methods", ""]
            for method in methods:
                method_decorators = [ast.unparse(d) for d in method.decorator_list]
                specializes_self = (
                    "classmethod" in method_decorators
                    and _contains_self(method.returns)
                )
                parts += [
                    f"### {method.name}",
                    "",
                    "```python",
                    signature(method, name),
                    "```",
                    "",
                    source_docs(method),
                    "",
                    source_link(file, method),
                    "",
                ]
                if specializes_self:
                    parts += [
                        "The classmethod receiver and `Self` return type are shown "
                        "for this concrete class; the source link identifies the "
                        "original declaration.",
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
        "annotations, defaults, and async declarations. Class pages show authored "
        "fields and methods declared locally or inherited from same-module authored "
        "bases. External-base and dynamically generated members are not expanded.",
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
