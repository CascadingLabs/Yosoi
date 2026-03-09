"""Coercion function registry for Yosoi semantic types."""

from collections.abc import Callable
from typing import Any

from yosoi.types.field import Field

# Maps yosoi_type -> coerce(v, config, source_url) -> coerced_value
_registry: dict[str, Callable[..., Any]] = {}


def register_coercion(
    type_name: str,
    *,
    description: str = '',
    **config_defaults: Any,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
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

    def decorator(coerce_fn: Callable[..., Any]) -> Callable[..., Any]:
        # Store the raw coerce function in the registry.
        _registry[type_name] = coerce_fn

        # Build a Field factory whose kwargs mirror the config_defaults.
        _description = description
        _config_defaults = config_defaults

        def factory(description: str = _description, **kwargs: Any) -> Any:
            # Split kwargs: config keys go to json_schema_extra, rest go to Field.
            config: dict[str, Any] = {'yosoi_type': type_name, **_config_defaults}
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
