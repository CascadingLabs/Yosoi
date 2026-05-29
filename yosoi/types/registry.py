"""Coercion function registry for Yosoi semantic types.

Each registered type may also declare a :class:`SemanticRule` describing the
*shape* a correctly-extracted value should have (numeric, url-like, concise
text, …). The shape rule lives next to the type definition so that custom types
registered via :func:`register_coercion` get semantic validation for free, and
the validator engine (``yosoi.core.verification.semantic``) stays generic — it
interprets a small set of kinds, never the specific built-in type names.
"""

import datetime
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from yosoi.types.field import Field

# Coercion config: json_schema_extra dict passed to coercion functions
CoercionConfig = dict[str, str | int | float | bool | None]

# Coercion function return type (includes datetime for Datetime coercer)
CoercedValue = str | float | int | datetime.datetime | None

# Semantic kinds the validator engine knows how to interpret. Types declare one
# of these; the engine never enumerates type names.
KIND_NUMERIC = 'numeric'  # must contain a number, must be short
KIND_URL = 'url'  # must look like a URL or path
KIND_TEXT = 'text'  # free text, optionally length-bounded / distinct


@dataclass(frozen=True)
class SemanticRule:
    """Declarative shape a well-extracted value of a type should have.

    Attributes:
        kind: One of ``KIND_NUMERIC`` / ``KIND_URL`` / ``KIND_TEXT``.
        max_chars: Upper bound on the raw string length, or None for unbounded.
            Catches "selector grabbed the whole card" failures.
        distinct: When True, the value should not equal another field's value
            (e.g. a title that accidentally returns the body).

    """

    kind: str
    max_chars: int | None = None
    distinct: bool = False


# Maps yosoi_type -> coerce(v, config, source_url) -> coerced_value
_registry: dict[str, Callable[..., CoercedValue]] = {}
# Maps yosoi_type -> SemanticRule (only types that declared one)
_semantic_registry: dict[str, SemanticRule] = {}


def semantic_rule_for(type_name: str | None) -> SemanticRule | None:
    """Return the declared :class:`SemanticRule` for a yosoi_type, if any."""
    if type_name is None:
        return None
    return _semantic_registry.get(type_name)


def register_coercion(
    type_name: str,
    *,
    description: str = '',
    semantic: SemanticRule | None = None,
    **config_defaults: Any,
) -> Callable[[Callable[..., CoercedValue]], Callable[..., Any]]:
    r"""Decorator that registers a coercion function and returns a Field factory.

    The decorated function becomes the Field factory — its name is what you use
    in a Contract.  The coercion logic is stored internally in the registry.

    Decorator kwargs define the config schema:
    - ``description``: default field description
    - all other kwargs: config keys that appear in ``json_schema_extra`` and are
      forwarded to the coerce function via ``config``

    Args:
        type_name: The ``yosoi_type`` identifier (e.g. ``'price'``).
        description: Default field description shown in manifests and to the AI.
        semantic: Optional :class:`SemanticRule` describing the shape a correct
            value should have. Used by the discovery semantic-retry loop.
        **config_defaults: Config keys with their default values. These become
            keyword arguments on the generated factory function.

    Example::

        @register_coercion('phone', description='A phone number', country_code='+1')
        def PhoneNumber(v, config, source_url=None):
            import re
            digits = re.sub(r'\D', '', str(v))
            return config.get('country_code', '+1') + digits

        # PhoneNumber is now a Field factory:
        # PhoneNumber(country_code='+44') -> Field(json_schema_extra={...})
    """

    def decorator(coerce_fn: Callable[..., CoercedValue]) -> Callable[..., Any]:
        # Store the raw coerce function in the registry.
        _registry[type_name] = coerce_fn
        if semantic is not None:
            _semantic_registry[type_name] = semantic

        # Build a Field factory whose kwargs mirror the config_defaults.
        _description = description
        _config_defaults = config_defaults

        def factory(description: str = _description, **kwargs: Any) -> Any:
            # Split kwargs: config keys go to json_schema_extra, rest go to Field.
            config: CoercionConfig = {'yosoi_type': type_name, **_config_defaults}
            field_kwargs: dict[str, Any] = {}
            for k, v in kwargs.items():
                if k in _config_defaults:
                    config[k] = v
                else:
                    field_kwargs[k] = v
            return Field(description=description, json_schema_extra=config, **field_kwargs)

        factory.__name__ = coerce_fn.__name__
        factory.__doc__ = coerce_fn.__doc__
        return factory

    return decorator
