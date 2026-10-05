#!/usr/bin/env python3
"""Build a fail-closed Python/Rust SDK surface inventory from rustdoc artifacts.

Rust API discovery is deliberately delegated to the repository's compiler-backed
reference generator. This module imports its immutable page artifacts instead
of trying to parse Rust source declarations itself.
"""

from __future__ import annotations

import argparse
import enum
import hashlib
import importlib
import inspect
import json
import pkgutil
import sys
import types
import typing
from collections import Counter
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA_VERSION = 1
TOOL_VERSION = "0.1.0"
STATUS_VALUES = {"mapped", "verified", "stale", "missing", "language-specific"}
SHA256_LENGTH = 64
PUBLIC_DUNDER_MEMBERS = {
    "__eq__",
    "__hash__",
    "__len__",
    "__repr__",
    "__str__",
}


class ParityError(ValueError):
    """Raised when an input cannot safely describe the selected SDK snapshot."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_json(value: Any) -> str:
    return digest_bytes(canonical_bytes(value))


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ParityError(f"cannot read JSON file {path}: {error}") from error


def _safe_artifact_path(value: str) -> Path:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or "\\" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ParityError(f"unsafe rust reference artifact path: {value!r}")
    return Path(*path.parts)


def _inventory_symbol(
    *,
    symbol_key: str,
    item_id: str,
    rust_path: str,
    aliases: list[str],
    kind: str,
    signature: str,
    surface: str,
    parent: str | None = None,
    trait: str | None = None,
) -> dict[str, Any]:
    return {
        "symbolKey": symbol_key,
        "id": item_id,
        "rustPath": rust_path,
        "aliases": sorted(set(aliases)),
        "kind": kind,
        "signature": signature,
        "rustArguments": (
            _rust_function_arguments(signature)
            if kind == "function"
            else _rust_variant_arguments(signature)
            if kind == "variant"
            else []
        ),
        "surface": surface,
        "parentRustPath": parent,
        "trait": trait,
    }


_MATCHING_DELIMITERS = {"(": ")", "[": "]", "{": "}", "<": ">"}


def _rust_function_arguments(signature: str) -> list[dict[str, Any]]:
    """Split the compiler-rendered fn parameter list while respecting nesting."""
    function_at = signature.find("fn ")
    if function_at < 0:
        raise ParityError(f"rustdoc function signature has no fn keyword: {signature}")
    stack: list[str] = []
    opening = None
    index = function_at + len("fn ")
    while index < len(signature):
        char = signature[index]
        if char == ">" and index > 0 and signature[index - 1] == "-":
            index += 1
            continue
        if char in "([{<":
            if char == "(" and not stack:
                opening = index
                break
            stack.append(char)
        elif char in ")]}>":
            if stack and _MATCHING_DELIMITERS.get(stack[-1]) == char:
                stack.pop()
        index += 1
    if opening is None:
        raise ParityError(f"rustdoc function has no parameter list: {signature}")

    pieces: list[str] = []
    current: list[str] = []
    stack = ["("]
    index = opening + 1
    while index < len(signature):
        char = signature[index]
        if char == ">" and index > 0 and signature[index - 1] == "-":
            current.append(char)
            index += 1
            continue
        if char in "([{<":
            stack.append(char)
            current.append(char)
        elif char in ")]}>":
            if stack and _MATCHING_DELIMITERS.get(stack[-1]) == char:
                stack.pop()
                if not stack:
                    if current:
                        pieces.append("".join(current).strip())
                    break
            current.append(char)
        elif char == "," and len(stack) == 1:
            if current:
                pieces.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        index += 1
    if stack:
        raise ParityError(f"unbalanced Rust function signature: {signature}")

    result = []
    for piece in pieces:
        if piece == "...":
            result.append({"name": "...", "type": "...", "receiver": False})
            continue
        if ":" not in piece:
            if piece.replace(" ", "") in {
                "self",
                "&self",
                "&mutself",
            } or piece.endswith(" self"):
                result.append({"name": "self", "type": piece, "receiver": True})
                continue
            raise ParityError(
                f"cannot identify Rust function argument in signature: {piece!r}"
            )
        name, type_text = piece.split(":", 1)
        name = name.strip().removeprefix("mut ").strip()
        result.append(
            {
                "name": name,
                "type": type_text.strip(),
                "receiver": name == "self",
            }
        )
    return result


def _split_rust_delimited_list(signature: str, opening: int) -> list[str]:
    first = signature[opening]
    stack = [first]
    pieces: list[str] = []
    current: list[str] = []
    index = opening + 1
    while index < len(signature):
        char = signature[index]
        if char == ">" and index > 0 and signature[index - 1] == "-":
            current.append(char)
            index += 1
            continue
        if char in "([{<":
            stack.append(char)
            current.append(char)
        elif char in ")]}>":
            if stack and _MATCHING_DELIMITERS.get(stack[-1]) == char:
                stack.pop()
                if not stack:
                    if current:
                        pieces.append("".join(current).strip())
                    return pieces
            current.append(char)
        elif char == "," and len(stack) == 1:
            if current:
                pieces.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        index += 1
    raise ParityError(f"unbalanced Rust signature: {signature}")


def _rust_variant_arguments(signature: str) -> list[dict[str, Any]]:
    """Describe compiler-rendered tuple and record enum-variant payloads."""
    candidates = [
        index for index in (signature.find("("), signature.find("{")) if index >= 0
    ]
    if not candidates:
        return []
    opening = min(candidates)
    delimiter = signature[opening]
    pieces = _split_rust_delimited_list(signature, opening)
    result = []
    for index, piece in enumerate(pieces):
        if delimiter == "(":
            result.append({"name": str(index), "type": piece, "receiver": False})
            continue
        if ":" not in piece:
            raise ParityError(f"cannot identify Rust variant field: {piece!r}")
        name, type_text = piece.split(":", 1)
        result.append(
            {"name": name.strip(), "type": type_text.strip(), "receiver": False}
        )
    return result


def load_rust_inventory(reference_dir: Path, locale: str = "en") -> dict[str, Any]:
    """Load and integrity-check the compiler-derived public reference pages."""
    reference_dir = reference_dir.resolve()
    manifest_path = reference_dir / "manifest.json"
    manifest = read_json(manifest_path)
    if (
        manifest.get("schemaVersion") != 1
        or manifest.get("kind") != "rust-api-reference"
    ):
        raise ParityError("input is not a supported rust-api-reference artifact")
    revision = manifest.get("source", {}).get("commit")
    if not isinstance(revision, str) or len(revision) != 40:
        raise ParityError("rust reference manifest has no full source commit")
    if any(char not in "0123456789abcdef" for char in revision):
        raise ParityError("rust reference source commit is not hexadecimal")
    if locale not in manifest.get("locales", []):
        raise ParityError(f"rust reference does not contain locale {locale!r}")

    sdk = manifest.get("sdk") or {}
    crate = sdk.get("crate")
    pages = manifest.get("pages")
    if not isinstance(crate, str) or not isinstance(pages, dict):
        raise ParityError("rust reference manifest is missing sdk or pages")

    inventory: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for slug, descriptor in sorted(pages.items()):
        if not isinstance(descriptor, dict):
            raise ParityError(f"invalid page descriptor for {slug!r}")
        relative = _safe_artifact_path(f"{locale}/{descriptor.get('file', '')}")
        page_path = reference_dir / relative
        component = reference_dir
        for part in relative.parts:
            component = component / part
            if component.is_symlink():
                raise ParityError(
                    f"rust reference artifact contains a symlink: {component}"
                )
        try:
            raw_page = page_path.read_bytes()
        except OSError as error:
            raise ParityError(
                f"cannot read rust reference page {page_path}: {error}"
            ) from error
        expected_digest = (descriptor.get("localeHashes") or {}).get(locale)
        if (
            not isinstance(expected_digest, str)
            or digest_bytes(raw_page) != expected_digest
        ):
            raise ParityError(f"rust reference page integrity failed: {locale}/{slug}")
        try:
            page = json.loads(raw_page)
        except json.JSONDecodeError as error:
            raise ParityError(
                f"invalid JSON in rust reference page {page_path}"
            ) from error
        if page.get("schemaVersion") != 1:
            raise ParityError(f"unsupported page schema in {locale}/{slug}")

        # The index page is an overview that repeats every top-level symbol as a
        # navigation member. Those links are not additional Rust API items.
        if page.get("publicPath") == crate and page.get("kind") == "module":
            continue

        aliases = sorted(
            set(descriptor.get("aliases") or []) | set(page.get("aliases") or [])
        )
        parent = _inventory_symbol(
            symbol_key=f"page:{page['id']}",
            item_id=page["id"],
            rust_path=page["publicPath"],
            aliases=aliases,
            kind=page["kind"],
            signature=page["signature"],
            surface="item",
        )
        _insert_unique(inventory, seen_keys, parent)

        for member in page.get("members", []):
            member_trait = member.get("trait")
            signature_digest = digest_bytes(member["signature"].encode("utf-8"))
            member_key = f"member:{member['id']}@signature:{signature_digest}"
            if member_trait:
                member_key += f"@trait:{member_trait}"
            source = member.get("source") or {}
            if source.get("file") and source.get("lineStart") and source.get("lineEnd"):
                source_key = digest_json(
                    {
                        "file": source["file"],
                        "lineStart": source["lineStart"],
                        "lineEnd": source["lineEnd"],
                    }
                )
                member_key += f"@source:{source_key}"
            record = _inventory_symbol(
                symbol_key=member_key,
                item_id=member["id"],
                rust_path=member["publicPath"],
                aliases=[],
                kind=member["kind"],
                signature=member["signature"],
                surface="member",
                parent=page["publicPath"],
                trait=member_trait,
            )
            _insert_unique(inventory, seen_keys, record)

    inventory.sort(key=lambda item: item["symbolKey"])
    signature = digest_json(inventory)
    build = manifest.get("build") or {}
    feature_profile = {
        "requestedFeatures": sorted(build.get("features") or []),
        "defaultFeaturesEnabled": True,
        "target": build.get("target"),
        "referenceGeneratorDigest": build.get("generatorDigest"),
        "compiler": {
            "toolchain": build.get("toolchain"),
            "rustdocVersion": build.get("rustdocVersion"),
            "compilerCommit": build.get("compilerCommit"),
            "rustdocFormatVersion": build.get("formatVersion"),
        },
    }
    feature_digest = digest_json(feature_profile)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "rust-public-sdk-inventory",
        "sourceRevision": revision,
        "sdk": {
            "crate": crate,
            "package": sdk.get("package"),
            "version": sdk.get("version"),
        },
        "reference": {
            "version": manifest.get("version"),
            "generatorDigest": build.get("generatorDigest"),
            "locale": locale,
        },
        "featureProfile": feature_profile,
        "featureProfileDigest": feature_digest,
        "inventorySignature": signature,
        "items": inventory,
    }


def _insert_unique(
    inventory: list[dict[str, Any]], seen: set[str], item: dict[str, Any]
) -> None:
    key = item["symbolKey"]
    if key in seen:
        prior = next(existing for existing in inventory if existing["symbolKey"] == key)
        if prior != item:
            raise ParityError(f"conflicting duplicate rustdoc symbol: {key}")
        return
    seen.add(key)
    inventory.append(item)


def _annotation_text(value: Any) -> str | None:
    if value is inspect.Signature.empty:
        return None
    return getattr(value, "__qualname__", None) or str(value)


def _safe_default(value: Any) -> Any:
    if value is inspect.Signature.empty:
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, tuple):
        return [_safe_default(item) for item in value]
    if isinstance(value, list):
        return [_safe_default(item) for item in value]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {key: _safe_default(item) for key, item in value.items()}
    value_type = type(value)
    return {
        "display": f"<{value_type.__module__}.{value_type.__qualname__}>",
        "stable": False,
    }


def _describe_signature(
    value: Any, *, bound_member: bool = False
) -> dict[str, Any] | None:
    try:
        signature = inspect.signature(value)
    except (TypeError, ValueError):
        return None
    parameters_to_describe = list(signature.parameters.values())
    if (
        bound_member
        and parameters_to_describe
        and parameters_to_describe[0].name in {"self", "cls"}
    ):
        parameters_to_describe = parameters_to_describe[1:]
    parameters = []
    for parameter in parameters_to_describe:
        parameters.append(
            {
                "name": parameter.name,
                "kind": parameter.kind.name.lower(),
                "annotation": _annotation_text(parameter.annotation),
                "hasDefault": parameter.default is not inspect.Signature.empty,
                "default": _safe_default(parameter.default),
            }
        )
    return {
        "display": str(signature.replace(parameters=parameters_to_describe)),
        "parameters": parameters,
        "returnAnnotation": _annotation_text(signature.return_annotation),
    }


def _is_public_native_exception(
    value: Any, module_name: str, package_name: str
) -> bool:
    """Include extension exceptions re-exported from public Python modules."""
    try:
        return (
            inspect.isclass(value)
            and issubclass(value, BaseException)
            and getattr(value, "__module__", None)
            in {"_native", f"{package_name}._native"}
            and module_name.startswith(f"{package_name}.")
            and not module_name.rsplit(".", 1)[-1].startswith("_")
        )
    except TypeError:
        return False


def _field_default(field: Any) -> dict[str, Any]:
    if field.is_required():
        return {"kind": "required"}
    if field.default_factory is not None:
        factory = field.default_factory
        return {
            "kind": "factory",
            "callable": f"{getattr(factory, '__module__', '')}.{getattr(factory, '__qualname__', type(factory).__name__)}",
        }
    return {"kind": "value", "value": _safe_default(field.default)}


def _literal_choices(annotation: Any) -> list[Any]:
    alias_type = getattr(typing, "TypeAliasType", None)
    if alias_type is not None and isinstance(annotation, alias_type):
        try:
            annotation = annotation.__value__
        except Exception:
            return []
    if typing.get_origin(annotation) is typing.Literal:
        return [_safe_default(item) for item in typing.get_args(annotation)]
    return []


def _model_fields(value: type[Any]) -> list[dict[str, Any]]:
    fields = getattr(value, "model_fields", None)
    if not isinstance(fields, dict):
        return []
    result = []
    for name, field in sorted(fields.items()):
        result.append(
            {
                "name": name,
                "alias": getattr(field, "alias", None),
                "validationAlias": str(getattr(field, "validation_alias", None))
                if getattr(field, "validation_alias", None) is not None
                else None,
                "serializationAlias": getattr(field, "serialization_alias", None),
                "annotation": _annotation_text(getattr(field, "annotation", None)),
                "literalChoices": _literal_choices(getattr(field, "annotation", None)),
                "default": _field_default(field),
            }
        )
    return result


def _type_alias_shape(value: Any, package_name: str) -> dict[str, Any]:
    """Describe literal choices and one-level tagged-union members for aliases."""
    alias_type = getattr(typing, "TypeAliasType", None)
    is_pep695_alias = alias_type is not None and isinstance(value, alias_type)
    try:
        annotation = value.__value__ if is_pep695_alias else value
    except Exception:
        annotation = value

    metadata: tuple[Any, ...] = ()
    if typing.get_origin(annotation) is typing.Annotated:
        parts = typing.get_args(annotation)
        annotation = parts[0]
        metadata = parts[1:]
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    discriminator = next(
        (
            item.discriminator
            for item in metadata
            if isinstance(getattr(item, "discriminator", None), str)
        ),
        None,
    )

    if origin is typing.Literal:
        alias_kind = "literal"
        choices = _literal_choices(annotation)
    elif origin in {typing.Union, types.UnionType}:
        alias_kind = "discriminated-union" if discriminator else "union"
        choices = []
    else:
        alias_kind = "alias"
        choices = []

    union_members = []
    if origin in {typing.Union, types.UnionType}:
        for member in args:
            name = getattr(member, "__qualname__", None) or str(member)
            module = getattr(member, "__module__", None)
            target = f"{module}.{name}" if isinstance(module, str) else None
            discriminator_value: Any = None
            if discriminator and inspect.isclass(member):
                fields = getattr(member, "model_fields", {})
                field = fields.get(discriminator) if isinstance(fields, dict) else None
                member_annotation = getattr(field, "annotation", None)
                if member_annotation is None:
                    member_annotation = getattr(member, "__annotations__", {}).get(
                        discriminator
                    )
                if typing.get_origin(member_annotation) is typing.Literal:
                    values = typing.get_args(member_annotation)
                    if len(values) == 1:
                        discriminator_value = _safe_default(values[0])
            union_members.append(
                {
                    "name": name,
                    "module": module,
                    "target": target
                    if isinstance(target, str)
                    and target.startswith(f"{package_name}.")
                    and not name.startswith("_")
                    else None,
                    "discriminatorValue": discriminator_value,
                }
            )
    return {
        "kind": alias_kind,
        "annotation": (
            str(annotation)
            if typing.get_origin(annotation) is not None
            else _annotation_text(annotation) or str(annotation)
        ),
        "choices": choices,
        "discriminator": discriminator,
        "unionMembers": union_members,
    }


def _class_member_descriptions(
    value: type[Any], aliases: list[str]
) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    fields = {item["name"]: item for item in _model_fields(value)}
    declared_members: dict[str, Any] = {}
    for base in reversed(value.__mro__):
        if base.__module__ == value.__module__:
            declared_members.update(vars(base))
    for alias in aliases:
        for name, field in fields.items():
            members.append(
                {
                    "target": f"{alias}.{name}",
                    "kind": "field",
                    "annotation": field["annotation"],
                    "field": field,
                }
            )
        for name, raw_member in declared_members.items():
            if name.startswith("_") and name not in PUBLIC_DUNDER_MEMBERS:
                continue
            target = f"{alias}.{name}"
            if isinstance(raw_member, property):
                members.append(
                    {
                        "target": target,
                        "kind": "property",
                        "signature": _describe_signature(
                            raw_member.fget, bound_member=True
                        )
                        if raw_member.fget
                        else None,
                    }
                )
                continue
            callable_member = raw_member
            if isinstance(raw_member, (classmethod, staticmethod)):
                callable_member = raw_member.__func__
            if inspect.isfunction(callable_member) or inspect.isbuiltin(
                callable_member
            ):
                members.append(
                    {
                        "target": target,
                        "kind": "callable",
                        "signature": _describe_signature(
                            getattr(value, name), bound_member=True
                        ),
                    }
                )
    return members


def _python_implementation_digest(package_name: str, package: Any) -> str:
    files: dict[str, str] = {}
    for package_dir in getattr(package, "__path__", []):
        root = Path(package_dir)
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.is_symlink() or not path.is_file():
                continue
            if path.suffix not in {".py", ".pyi"} and path.name != "py.typed":
                continue
            relative = path.relative_to(root).as_posix()
            files[f"source/{relative}"] = digest_bytes(path.read_bytes())
    native = sys.modules.get(f"{package_name}._native")
    native_path = getattr(native, "__file__", None)
    if isinstance(native_path, str):
        path = Path(native_path)
        if path.is_file() and not path.is_symlink():
            files[f"native/{path.name}"] = digest_bytes(path.read_bytes())
    return digest_json(files)


def _distribution_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def introspect_python_package(
    package_name: str = "yosoi-engine", python_root: Path | None = None
) -> dict[str, Any]:
    """Import public package modules and describe targets and Pydantic fields."""
    python_root_entry: str | None = None
    if python_root is not None:
        python_root_entry = str(python_root.resolve())
        sys.path.insert(0, python_root_entry)
    try:
        package = importlib.import_module(package_name)
        modules = [package]
        package_path = getattr(package, "__path__", None)
        if package_path is not None:
            names = sorted(
                item.name
                for item in pkgutil.walk_packages(
                    package_path, prefix=f"{package_name}."
                )
                if not item.name.rsplit(".", 1)[-1].startswith("_")
            )
            modules.extend(importlib.import_module(name) for name in names)
    except Exception as error:
        raise ParityError(
            f"cannot import {package_name!r} for live Python introspection: {error}"
        ) from error
    finally:
        if python_root_entry is not None and python_root_entry in sys.path:
            sys.path.remove(python_root_entry)

    candidates: dict[int, tuple[Any, set[str], str]] = {}
    for module in modules:
        module_name = module.__name__
        exported = set(getattr(module, "__all__", ()))
        for name, value in vars(module).items():
            if name.startswith("_"):
                continue
            target = f"{module_name}.{name}"
            is_module = isinstance(
                value, types.ModuleType
            ) and value.__name__.startswith(f"{package_name}.")
            is_public_object = (
                inspect.isclass(value)
                or inspect.isfunction(value)
                or inspect.isbuiltin(value)
            ) and (
                getattr(value, "__module__", "")
                in {package_name, f"{package_name}._native"}
                or getattr(value, "__module__", "").startswith(f"{package_name}.")
                or name in exported
                or _is_public_native_exception(value, module_name, package_name)
            )
            pep695_alias = getattr(typing, "TypeAliasType", None)
            is_type_alias = (
                typing.get_origin(value) is not None
                or (pep695_alias is not None and isinstance(value, pep695_alias))
            ) and not isinstance(value, types.ModuleType)
            if not is_module and not is_public_object and not is_type_alias:
                continue
            identity = id(value)
            prior = candidates.get(identity)
            if prior is None:
                candidate_kind = (
                    "module"
                    if is_module
                    else "type-alias"
                    if is_type_alias
                    else "object"
                )
                candidates[identity] = (value, {target}, candidate_kind)
            else:
                prior[1].add(target)

    targets: dict[str, dict[str, Any]] = {}
    objects: list[dict[str, Any]] = []
    for value, target_set, candidate_kind in candidates.values():
        aliases = sorted(target_set, key=lambda target: (target.count("."), target))
        canonical_target = aliases[0]
        if candidate_kind == "module":
            record = {"target": canonical_target, "kind": "module", "aliases": aliases}
            objects.append(record)
            for target in aliases:
                targets[target] = {
                    "kind": "module",
                    "canonicalTarget": canonical_target,
                }
            continue

        if candidate_kind == "type-alias":
            kind = "type-alias"
            alias = _type_alias_shape(value, package_name)
            signature = {
                "display": alias["annotation"],
                "parameters": [],
                "returnAnnotation": None,
            }
            fields = []
            members = []
            enum_values = []
        elif inspect.isclass(value):
            kind = "class"
            signature = _describe_signature(value)
            fields = _model_fields(value)
            members = _class_member_descriptions(value, aliases)
            enum_values = (
                [
                    {"name": member.name, "value": _safe_default(member.value)}
                    for member in value
                ]
                if issubclass(value, enum.Enum)
                else []
            )
        else:
            kind = "callable"
            signature = _describe_signature(value)
            fields = []
            members = []
            enum_values = []
        record = {
            "target": canonical_target,
            "kind": kind,
            "aliases": aliases,
            "signature": signature,
            "fields": fields,
            "enumValues": enum_values,
        }
        if candidate_kind == "type-alias":
            record["alias"] = alias
        objects.append(record)
        for target in aliases:
            targets[target] = {
                "kind": kind,
                "canonicalTarget": canonical_target,
                "signature": signature,
                "fields": fields,
                "enumValues": enum_values,
            }
            if candidate_kind == "type-alias":
                targets[target]["alias"] = alias
        for member in members:
            target = member["target"]
            # A Pydantic field takes precedence over class attributes that merely
            # expose the same model field through BaseModel machinery.
            if target not in targets or member["kind"] == "field":
                targets[target] = member
        for enum_value in enum_values:
            for alias in aliases:
                target = f"{alias}.{enum_value['name']}"
                targets[target] = {
                    "target": target,
                    "kind": "enum-member",
                    "canonicalTarget": canonical_target,
                    "value": enum_value["value"],
                }

    objects.sort(key=lambda item: item["target"])
    surface_material = {
        "objects": [
            {key: value for key, value in item.items() if key != "aliases"}
            | {"aliases": item["aliases"]}
            for item in objects
        ],
        "targets": targets,
    }
    implementation_digest = _python_implementation_digest(package_name, package)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "python-package-surface",
        "package": package_name,
        "runtime": {
            "implementation": sys.implementation.name,
            "version": ".".join(str(part) for part in sys.version_info[:3]),
            "abi": getattr(sys, "abiflags", ""),
            "dependencies": {
                "pydantic": _distribution_version("pydantic"),
                "pydantic-core": _distribution_version("pydantic-core"),
            },
        },
        "surfaceDigest": digest_json(surface_material),
        "implementationDigest": implementation_digest,
        "objects": objects,
        "targets": targets,
    }


def load_ledger(path: Path) -> dict[str, Any]:
    ledger = read_json(path)
    if (
        ledger.get("schemaVersion") != SCHEMA_VERSION
        or ledger.get("kind") != "python-rust-sdk-parity-ledger"
    ):
        raise ParityError("unsupported parity ledger schema or kind")
    entries = ledger.get("entries")
    if not isinstance(entries, list):
        raise ParityError("parity ledger must contain an entries array")
    paths = [entry.get("rustPath") for entry in entries]
    if any(not isinstance(item, str) or not item for item in paths):
        raise ParityError("every parity ledger entry needs a rustPath")
    selectors = [
        entry.get("symbolKey") or f"{entry['rustPath']}@trait:{entry.get('trait', '')}"
        for entry in entries
    ]
    if len(selectors) != len(set(selectors)):
        raise ParityError("parity ledger contains duplicate rustPath entries")
    for entry in entries:
        if entry.get("symbolKey") is not None and not isinstance(
            entry["symbolKey"], str
        ):
            raise ParityError(f"invalid symbolKey for ledger entry {entry['rustPath']}")
        if entry.get("trait") is not None and not isinstance(entry["trait"], str):
            raise ParityError(
                f"invalid trait selector for ledger entry {entry['rustPath']}"
            )
        decision = entry.get("decision")
        if decision not in {"mapped", "language-specific"}:
            raise ParityError(f"unsupported ledger decision for {entry['rustPath']}")
        if decision == "mapped" and not isinstance(entry.get("pythonTarget"), str):
            raise ParityError(f"mapped entry has no pythonTarget: {entry['rustPath']}")
        for field_name in (
            "argumentMappings",
            "defaults",
            "units",
            "cardinality",
        ):
            value = entry.get(field_name, [])
            if not isinstance(value, list):
                raise ParityError(
                    f"{field_name} must be an array for {entry['rustPath']}"
                )
            if not all(isinstance(item, dict) for item in value):
                raise ParityError(
                    f"{field_name} rows must be objects for {entry['rustPath']}"
                )
        for argument in entry.get("argumentMappings", []):
            if not all(
                isinstance(argument.get(field), str) and argument[field]
                for field in ("rustArgument", "pythonArgument", "conversion")
            ):
                raise ParityError(
                    f"argument mappings need rustArgument, pythonArgument, and conversion: {entry['rustPath']}"
                )
        for field_name in ("defaults", "units", "cardinality"):
            if any(
                not isinstance(item.get("id"), str) or not item["id"]
                for item in entry.get(field_name, [])
            ):
                raise ParityError(
                    f"{field_name} rows need stable ids for {entry['rustPath']}"
                )
        if decision == "language-specific":
            review = entry.get("review") or {}
            if review.get("status") not in {"proposed", "reviewed"}:
                raise ParityError(
                    f"language-specific entry needs review metadata: {entry['rustPath']}"
                )
            if (
                not isinstance(review.get("pythonEquivalent"), str)
                or not review["pythonEquivalent"].strip()
            ):
                raise ParityError(
                    f"language-specific entry needs an explicit Python semantic equivalent: {entry['rustPath']}"
                )
        if entry.get("semanticEquivalent") is not None and not isinstance(
            entry["semanticEquivalent"], str
        ):
            raise ParityError(
                f"semanticEquivalent must be a string for {entry['rustPath']}"
            )
    return ledger


def _pin_state(
    ledger: dict[str, Any], rust: dict[str, Any], python: dict[str, Any]
) -> dict[str, Any]:
    source_pin = ledger.get("sourcePin") or {}
    python_pin = ledger.get("pythonPin") or {}
    current = {
        "sourceRevision": rust["sourceRevision"],
        "inventorySignature": rust["inventorySignature"],
        "featureProfileDigest": rust["featureProfileDigest"],
        "pythonSurfaceDigest": python["surfaceDigest"],
        "pythonImplementationDigest": python["implementationDigest"],
    }
    expected = {
        "sourceRevision": source_pin.get("sourceRevision"),
        "inventorySignature": source_pin.get("inventorySignature"),
        "featureProfileDigest": source_pin.get("featureProfileDigest"),
        "pythonSurfaceDigest": python_pin.get("surfaceDigest"),
        "pythonImplementationDigest": python_pin.get("implementationDigest"),
    }
    matches = {
        name: expected[name] is not None and expected[name] == current[name]
        for name in current
    }
    return {
        "current": current,
        "expected": expected,
        "matches": matches,
        "pinned": all(value is not None for value in expected.values()),
        "matchesAll": all(matches.values()),
    }


def _load_evidence(
    path: Path, rust: dict[str, Any], python: dict[str, Any]
) -> dict[str, Any]:
    evidence = read_json(path)
    if (
        evidence.get("schemaVersion") != SCHEMA_VERSION
        or evidence.get("kind") != "yosoi-python-rust-conformance"
    ):
        raise ParityError(f"unsupported conformance evidence file: {path}")
    required_strings = ["runId", "executedAt"]
    if any(
        not isinstance(evidence.get(name), str) or not evidence[name]
        for name in required_strings
    ):
        raise ParityError(f"conformance evidence lacks runId or executedAt: {path}")
    try:
        datetime.fromisoformat(evidence["executedAt"].replace("Z", "+00:00"))
    except ValueError as error:
        raise ParityError(
            f"invalid executedAt in conformance evidence: {path}"
        ) from error
    runner = evidence.get("runner") or {}
    if (
        not isinstance(runner.get("command"), list)
        or not runner["command"]
        or not all(isinstance(part, str) and part for part in runner["command"])
    ):
        raise ParityError(f"conformance evidence needs runner.command: {path}")
    if evidence.get("outcome") not in {"passed", "failed"}:
        raise ParityError(f"invalid conformance run outcome: {path}")
    artifact = evidence.get("resultArtifact") or {}
    artifact_path = artifact.get("path")
    artifact_digest = artifact.get("sha256")
    if not isinstance(artifact_path, str) or not _is_sha256(artifact_digest):
        raise ParityError(
            f"conformance evidence needs a digested resultArtifact: {path}"
        )
    relative = _safe_artifact_path(artifact_path)
    artifact_bytes_path = path.resolve().parent / relative
    try:
        result_bytes = artifact_bytes_path.read_bytes()
    except OSError as error:
        raise ParityError(
            f"cannot read conformance result artifact {artifact_bytes_path}"
        ) from error
    actual_artifact_digest = digest_bytes(result_bytes)
    if actual_artifact_digest != artifact_digest:
        raise ParityError(
            f"conformance result artifact digest mismatch: {artifact_bytes_path}"
        )
    try:
        result_artifact = json.loads(result_bytes)
    except json.JSONDecodeError as error:
        raise ParityError(
            f"conformance result artifact is not JSON: {artifact_bytes_path}"
        ) from error
    if (
        result_artifact.get("schemaVersion") != SCHEMA_VERSION
        or result_artifact.get("kind") != "yosoi-python-rust-conformance-results"
    ):
        raise ParityError(
            f"unsupported conformance result artifact: {artifact_bytes_path}"
        )
    for field_name in ("runId", "outcome", "source", "python", "cases"):
        if canonical_bytes(result_artifact.get(field_name)) != canonical_bytes(
            evidence.get(field_name)
        ):
            raise ParityError(
                f"conformance result artifact disagrees on {field_name}: {artifact_bytes_path}"
            )

    source = evidence.get("source") or {}
    python_evidence = evidence.get("python") or {}
    runtime_matches = python_evidence.get("runtime") == python["runtime"]
    snapshot_matches = {
        "sourceRevision": source.get("sourceRevision") == rust["sourceRevision"],
        "inventorySignature": source.get("inventorySignature")
        == rust["inventorySignature"],
        "featureProfileDigest": source.get("featureProfileDigest")
        == rust["featureProfileDigest"],
        "pythonSurfaceDigest": python_evidence.get("surfaceDigest")
        == python["surfaceDigest"],
        "pythonImplementationDigest": python_evidence.get("implementationDigest")
        == python["implementationDigest"],
        "pythonRuntime": runtime_matches,
    }
    cases = evidence.get("cases")
    if not isinstance(cases, list):
        raise ParityError(f"conformance evidence needs a cases array: {path}")
    return {
        "path": str(path),
        "runId": evidence["runId"],
        "outcome": evidence.get("outcome"),
        "snapshotMatches": snapshot_matches,
        "snapshotMatchesAll": all(snapshot_matches.values()),
        "resultArtifactSha256": artifact_digest,
        "cases": cases,
    }


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == SHA256_LENGTH
        and all(char in "0123456789abcdef" for char in value)
    )


def _case_passes(case: Any, rust_item: dict[str, Any], entry: dict[str, Any]) -> bool:
    if not isinstance(case, dict) or case.get("outcome") != "passed":
        return False
    if not isinstance(case.get("testId"), str) or not case["testId"]:
        return False
    if case.get("symbolKey") is not None:
        if case["symbolKey"] != rust_item["symbolKey"]:
            return False
    elif case.get("rustPath") not in {rust_item["rustPath"], *rust_item["aliases"]}:
        return False
    elif rust_item["trait"] is not None and case.get("trait") != rust_item["trait"]:
        return False
    if case.get("pythonTarget") != entry.get("pythonTarget"):
        return False
    assertions = case.get("comparisons")
    if not isinstance(assertions, list) or not assertions:
        return False
    for assertion in assertions:
        if (
            not isinstance(assertion, dict)
            or not isinstance(assertion.get("name"), str)
            or assertion.get("equal") is not True
            or not _is_sha256(assertion.get("rustSha256"))
            or not _is_sha256(assertion.get("pythonSha256"))
            or assertion["rustSha256"] != assertion["pythonSha256"]
        ):
            return False
    mapping_checks = case.get("mappingChecks")
    if not isinstance(mapping_checks, list):
        return False
    expected_checks = [
        ("argument", item["rustArgument"]) for item in entry.get("argumentMappings", [])
    ]
    expected_checks.extend(
        (kind, item["id"])
        for kind, field in (
            ("default", "defaults"),
            ("unit", "units"),
            ("cardinality", "cardinality"),
        )
        for item in entry.get(field, [])
    )
    for kind, key in expected_checks:
        matching = [
            check
            for check in mapping_checks
            if isinstance(check, dict)
            and check.get("kind") == kind
            and check.get("key") == key
        ]
        if len(matching) != 1:
            return False
        check = matching[0]
        if (
            check.get("equal") is not True
            or not _is_sha256(check.get("rustSha256"))
            or not _is_sha256(check.get("pythonSha256"))
            or check["rustSha256"] != check["pythonSha256"]
        ):
            return False
    return True


def _case_targets_rust_item(case: Any, rust_item: dict[str, Any]) -> bool:
    if not isinstance(case, dict):
        return False
    if case.get("symbolKey") is not None:
        return case["symbolKey"] == rust_item["symbolKey"]
    if case.get("rustPath") not in {rust_item["rustPath"], *rust_item["aliases"]}:
        return False
    return rust_item["trait"] is None or case.get("trait") == rust_item["trait"]


def _case_targets_item(
    case: Any, rust_item: dict[str, Any], entry: dict[str, Any]
) -> bool:
    return _case_targets_rust_item(case, rust_item) and case.get(
        "pythonTarget"
    ) == entry.get("pythonTarget")


def _mapping_configuration_problem(
    rust_item: dict[str, Any], entry: dict[str, Any], target: dict[str, Any]
) -> str | None:
    if (
        rust_item["kind"] in {"trait", "macro", "proc_macro"}
        and not str(entry.get("semanticEquivalent", "")).strip()
    ):
        return "Rust trait or macro mapping needs an explicit semantic equivalent"
    if rust_item["kind"] not in {"function", "variant"}:
        return None
    rust_arguments = rust_item.get("rustArguments")
    if not isinstance(rust_arguments, list):
        return "Rust function arguments could not be read from the compiler signature"
    expected = {
        argument["name"] for argument in rust_arguments if not argument.get("receiver")
    }
    mappings = entry.get("argumentMappings", [])
    mapped = {argument["rustArgument"] for argument in mappings}
    if expected != mapped:
        details = []
        missing = sorted(expected - mapped)
        extra = sorted(mapped - expected)
        if missing:
            details.append(f"unmapped Rust arguments: {', '.join(missing)}")
        if extra:
            details.append(f"unknown Rust arguments: {', '.join(extra)}")
        return "; ".join(details)
    python_parameters = {
        parameter["name"]
        for parameter in ((target.get("signature") or {}).get("parameters") or [])
        if isinstance(parameter, dict) and isinstance(parameter.get("name"), str)
    }
    for argument in mappings:
        if argument["pythonArgument"] not in python_parameters:
            return (
                f"Python argument {argument['pythonArgument']} for Rust argument "
                f"{argument['rustArgument']} is absent from the introspected signature"
            )
    if rust_item["kind"] == "function" and target.get("kind") == "class":
        mapped_python = {argument["pythonArgument"] for argument in mappings}
        required_python = {
            parameter["name"]
            for parameter in ((target.get("signature") or {}).get("parameters") or [])
            if isinstance(parameter, dict)
            and parameter.get("hasDefault") is False
            and isinstance(parameter.get("name"), str)
        }
        missing_python = sorted(required_python - mapped_python)
        if missing_python:
            return "unmapped required Python arguments: " + ", ".join(missing_python)
    return None


def build_report(
    rust: dict[str, Any],
    python: dict[str, Any],
    ledger: dict[str, Any],
    evidence_documents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Join complete Rust and Python inventories with explicit mappings/evidence."""
    evidence_documents = evidence_documents or []
    pin = _pin_state(ledger, rust, python)
    rust_by_path: dict[str, list[dict[str, Any]]] = {}
    rust_by_key = {item["symbolKey"]: item for item in rust["items"]}
    for item in rust["items"]:
        for path in [item["rustPath"], *item["aliases"]]:
            paths = rust_by_path.setdefault(path, [])
            if all(existing["symbolKey"] != item["symbolKey"] for existing in paths):
                paths.append(item)

    entry_by_item: dict[str, dict[str, Any]] = {}
    stale_ledger_entries: list[dict[str, str]] = []
    for entry in ledger["entries"]:
        if entry.get("symbolKey"):
            item = rust_by_key.get(entry["symbolKey"])
            candidates = [item] if item is not None else []
        else:
            candidates = rust_by_path.get(entry["rustPath"], [])
            if "trait" in entry:
                candidates = [
                    item for item in candidates if item["trait"] == entry["trait"]
                ]
        if not candidates:
            stale_ledger_entries.append(
                {
                    "rustPath": entry["rustPath"],
                    "reason": "path absent from current Rust inventory",
                }
            )
            continue
        if len(candidates) > 1:
            raise ParityError(
                f"ambiguous Rust public path {entry['rustPath']}; ledger must identify symbolKey or trait"
            )
        item = candidates[0]
        if entry["rustPath"] not in {item["rustPath"], *item["aliases"]}:
            stale_ledger_entries.append(
                {
                    "rustPath": entry["rustPath"],
                    "reason": "symbolKey no longer matches rustPath",
                }
            )
            continue
        if item["symbolKey"] in entry_by_item:
            raise ParityError(
                f"multiple ledger rows map the same Rust item: {entry['rustPath']}"
            )
        entry_by_item[item["symbolKey"]] = entry

    evidence_by_item: dict[str, list[dict[str, str]]] = {}
    stale_evidence: dict[str, list[str]] = {}
    for evidence in evidence_documents:
        if evidence.get("outcome") != "passed":
            continue
        for item in rust["items"]:
            entry = entry_by_item.get(item["symbolKey"])
            if not entry or entry.get("decision") != "mapped":
                continue
            rust_cases = [
                case
                for case in evidence["cases"]
                if _case_targets_rust_item(case, item)
            ]
            if not rust_cases:
                continue
            if not evidence["snapshotMatchesAll"]:
                stale_evidence.setdefault(item["symbolKey"], []).append(
                    evidence["runId"]
                )
                continue
            matching = [
                case for case in rust_cases if _case_targets_item(case, item, entry)
            ]
            if not matching:
                stale_evidence.setdefault(item["symbolKey"], []).append(
                    evidence["runId"]
                )
                continue
            passing_cases = [
                case for case in matching if _case_passes(case, item, entry)
            ]
            for case in passing_cases:
                evidence_by_item.setdefault(item["symbolKey"], []).append(
                    {
                        "runId": evidence["runId"],
                        "testId": case["testId"],
                        "resultArtifactSha256": evidence["resultArtifactSha256"],
                        "comparisons": case["comparisons"],
                    }
                )

    report_items = []
    for item in rust["items"]:
        entry = entry_by_item.get(item["symbolKey"])
        status = "missing"
        reason = "no explicit parity ledger mapping"
        target_info = None
        item_evidence: list[dict[str, Any]] = []
        if entry is not None:
            if entry.get("decision") == "language-specific":
                review = entry.get("review") or {}
                if (
                    review.get("status") == "reviewed"
                    and review.get("reviewer")
                    and review.get("rationale")
                    and review.get("pythonEquivalent")
                ):
                    status = "language-specific"
                    reason = review["rationale"]
                else:
                    status = "missing"
                    reason = "language-specific disposition requires completed review"
            else:
                target = entry["pythonTarget"]
                target_info = python["targets"].get(target)
                expected_signature_digest = entry.get("rustSignatureSha256")
                actual_signature_digest = digest_bytes(
                    item["signature"].encode("utf-8")
                )
                signature_stale = (
                    expected_signature_digest is not None
                    and expected_signature_digest != actual_signature_digest
                )
                global_stale = any(
                    pin["expected"][name] is not None and not pin["matches"][name]
                    for name in pin["matches"]
                )
                if signature_stale:
                    status = "stale"
                    reason = (
                        "Rust signature differs from the ledger's reviewed signature"
                    )
                elif global_stale:
                    status = "stale"
                    reason = (
                        "Rust or Python surface pin differs from the ledger baseline"
                    )
                elif target_info is None:
                    status = "stale"
                    reason = (
                        "mapped Python target is absent from live package introspection"
                    )
                elif (
                    mapping_problem := _mapping_configuration_problem(
                        item, entry, target_info
                    )
                ) is not None:
                    status = "missing"
                    reason = f"incomplete argument mapping: {mapping_problem}"
                elif stale_evidence.get(item["symbolKey"]):
                    status = "stale"
                    reason = "available conformance evidence is bound to an older surface snapshot"
                else:
                    item_evidence = evidence_by_item.get(item["symbolKey"], [])
                    if item_evidence:
                        status = "verified"
                        reason = "matching executed conformance evidence is bound to this snapshot"
                    else:
                        status = "mapped"
                        reason = "target and mapping are declared; no matching executed conformance evidence"

        report_items.append(
            {
                **item,
                "status": status,
                "statusReason": reason,
                "python": (
                    {
                        "target": entry.get("pythonTarget"),
                        "targetKind": target_info.get("kind") if target_info else None,
                        "signature": target_info.get("signature")
                        if target_info
                        else None,
                        "fields": target_info.get("fields", []) if target_info else [],
                        "alias": target_info.get("alias") if target_info else None,
                        "value": target_info.get("value") if target_info else None,
                    }
                    if entry and entry.get("decision") == "mapped"
                    else None
                ),
                "mapping": (
                    {
                        "decision": entry.get("decision"),
                        "pythonTarget": entry.get("pythonTarget"),
                        "semanticEquivalent": entry.get("semanticEquivalent"),
                        "argumentMappings": entry.get("argumentMappings", []),
                        "defaults": entry.get("defaults", []),
                        "units": entry.get("units", []),
                        "cardinality": entry.get("cardinality", []),
                        "rationale": entry.get("rationale"),
                        "review": entry.get("review"),
                    }
                    if entry
                    else None
                ),
                "evidence": item_evidence,
            }
        )

    counts = Counter(item["status"] for item in report_items)
    denominator = len(report_items)
    covered = counts["verified"] + counts["language-specific"]
    if (
        stale_ledger_entries
        or counts["stale"]
        or (pin["pinned"] and not pin["matchesAll"])
    ):
        parity_status = "stale"
    elif denominator > 0 and covered == denominator and pin["matchesAll"]:
        parity_status = "complete"
    else:
        parity_status = "incomplete"

    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "python-rust-sdk-parity-report",
        "toolVersion": TOOL_VERSION,
        "generatedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source": {
            "revision": rust["sourceRevision"],
            "sdk": rust["sdk"],
            "reference": rust["reference"],
            "inventorySignature": rust["inventorySignature"],
            "featureProfile": rust["featureProfile"],
            "featureProfileDigest": rust["featureProfileDigest"],
        },
        "python": {
            "package": python["package"],
            "runtime": python["runtime"],
            "surfaceDigest": python["surfaceDigest"],
            "implementationDigest": python["implementationDigest"],
            "objects": python["objects"],
            "targets": python["targets"],
        },
        "ledger": {
            "sourceRevision": pin["expected"]["sourceRevision"],
            "inventorySignature": pin["expected"]["inventorySignature"],
            "featureProfileDigest": pin["expected"]["featureProfileDigest"],
            "pythonSurfaceDigest": pin["expected"]["pythonSurfaceDigest"],
            "pythonImplementationDigest": pin["expected"]["pythonImplementationDigest"],
            "pinState": pin,
            "staleEntries": stale_ledger_entries,
        },
        "parityStatus": parity_status,
        "coverage": {
            "denominator": denominator,
            "counts": {status: counts[status] for status in sorted(STATUS_VALUES)},
            "covered": covered,
            "mappedButUnverified": counts["mapped"],
            "staleOrMissing": counts["stale"] + counts["missing"],
            "items": report_items,
        },
    }


def strict_failures(report: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    pin = report["ledger"]["pinState"]
    if not pin["pinned"]:
        failures.append(
            "ledger baseline is not fully pinned to Rust and Python surfaces"
        )
    elif not pin["matchesAll"]:
        failures.append(
            "ledger baseline does not match the current source and feature profile"
        )
    if report["ledger"]["staleEntries"]:
        failures.append("ledger contains paths absent from the current Rust inventory")
    counts = report["coverage"]["counts"]
    if counts["missing"]:
        failures.append(
            f"{counts['missing']} public Rust symbols or members are unmapped"
        )
    if counts["stale"]:
        failures.append(f"{counts['stale']} mappings or evidence records are stale")
    if counts["mapped"]:
        failures.append(f"{counts['mapped']} mappings lack conformance evidence")
    return failures


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rust-reference", type=Path, required=True)
    parser.add_argument(
        "--ledger", type=Path, default=Path("python/parity/ledger.json")
    )
    parser.add_argument("--python-root", type=Path, default=Path("python"))
    parser.add_argument("--package", default="yosoi-engine")
    parser.add_argument("--locale", default="en")
    parser.add_argument("--evidence", type=Path, action="append", default=[])
    parser.add_argument(
        "--output", type=Path, default=Path("python/parity/report.json")
    )
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="write an incomplete inventory report with exit status zero",
    )
    args = parser.parse_args(argv)
    try:
        rust = load_rust_inventory(args.rust_reference, args.locale)
        python = introspect_python_package(args.package, args.python_root)
        ledger = load_ledger(args.ledger)
        evidence = [_load_evidence(path, rust, python) for path in args.evidence]
        report = build_report(rust, python, ledger, evidence)
        write_report(args.output, report)
    except ParityError as error:
        parser.error(str(error))
    failures = strict_failures(report)
    counts = report["coverage"]["counts"]
    print(
        f"{report['parityStatus']}: {report['coverage']['denominator']} Rust items; "
        f"{counts['verified']} verified, {counts['mapped']} mapped, "
        f"{counts['language-specific']} language-specific, {counts['missing']} missing, "
        f"{counts['stale']} stale; report={args.output}"
    )
    if failures and not args.allow_incomplete:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
