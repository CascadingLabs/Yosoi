"""Tests for register_coercion decorator and Field factory."""

from pydantic.fields import FieldInfo

from yosoi.types.registry import _registry, register_coercion


def test_register_coercion_stores_function_in_registry():
    @register_coercion('_test_reg_abc', description='test type', my_param='default')
    def TestTypeAbc(v, config, source_url=None):
        return config.get('my_param', 'default')

    assert '_test_reg_abc' in _registry


def test_register_coercion_returns_field_factory():
    @register_coercion('_test_factory_abc', description='A test type', flag=True)
    def TestFactoryAbc(v, config, source_url=None):
        return v

    field = TestFactoryAbc()
    assert isinstance(field, FieldInfo)


def test_factory_name_preserved():
    @register_coercion('_test_name_abc', description='test')
    def MySpecialTypeName(v, config, source_url=None):
        return v

    assert MySpecialTypeName.__name__ == 'MySpecialTypeName'


def test_factory_config_kwarg_goes_to_schema_extra():
    @register_coercion('_test_config_abc', description='test', my_setting='off')
    def TestConfigTypeAbc(v, config, source_url=None):
        return v

    field = TestConfigTypeAbc(my_setting='on')
    assert isinstance(field, FieldInfo)
    assert isinstance(field.json_schema_extra, dict)
    assert field.json_schema_extra['my_setting'] == 'on'


def test_factory_non_config_kwarg_goes_to_field():
    @register_coercion('_test_fieldkw_abc', description='test', my_setting='off')
    def TestFieldKwAbc(v, config, source_url=None):
        return v

    # 'frozen' is not a config key — goes through to Yosoi's Field wrapper
    # which stores it in json_schema_extra['yosoi_frozen'], not FieldInfo.frozen
    field = TestFieldKwAbc(frozen=True)
    assert isinstance(field, FieldInfo)
    assert isinstance(field.json_schema_extra, dict)
    assert field.json_schema_extra.get('yosoi_frozen') is True
