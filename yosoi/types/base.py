"""YosoiType base class for user-defined semantic types."""

from typing import Any

from yosoi.types.registry import _registry, register_coercion


class YosoiType:
    r"""Optional base class for user-defined Yosoi semantic types.

    The preferred pattern is the ``@register_coercion`` decorator — it handles
    both registration and Field factory generation in one step::

        @register_coercion('phone', description='A phone number', country_code='+1')
        def PhoneNumber(v, config, source_url=None):
            import re
            digits = re.sub(r'\D', '', str(v))
            return config.get('country_code', '+1') + digits

        # PhoneNumber is now a Field factory:
        # PhoneNumber(country_code='+44') -> Field(json_schema_extra={...})

    Subclassing ``YosoiType`` is useful when you prefer the OOP style and want
    to group the factory and coercer under one class name::

        class PhoneNumber(YosoiType):
            type_name = 'phone'

            @staticmethod
            def coerce(v, config, source_url=None):
                import re
                digits = re.sub(r'\D', '', str(v))
                return config.get('country_code', '+1') + digits

            @classmethod
            def field(cls, country_code='+1', description='A phone number', **kwargs):
                from yosoi.types.field import Field
                return Field(
                    description=description,
                    json_schema_extra={'yosoi_type': cls.type_name, 'country_code': country_code},
                    **kwargs,
                )
    """

    type_name: str

    @classmethod
    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Auto-register coerce method when both type_name and coerce are defined."""
        super().__init_subclass__(**kwargs)
        if 'type_name' in cls.__dict__ and 'coerce' in cls.__dict__:
            _registry[cls.type_name] = cls.coerce

    @staticmethod
    def coerce(v: object, config: dict[str, Any], source_url: str | None = None) -> Any:  # noqa: ARG004
        """Default coercion: strip whitespace. Override in subclasses."""
        return str(v).strip() if v is not None else ''


__all__ = ['YosoiType', '_registry', 'register_coercion']
