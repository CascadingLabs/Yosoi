"""Tests for register_coercion decorator and Field factory."""

from pydantic.fields import FieldInfo

from yosoi.types.registry import _registry, register_coercion


def test_register_coercion_stores_function_in_registry():
    @register_coercion('_test_reg_abc', description='test type', my_param='default')
    def TestTypeAbc(v, config, source_url=None):
        return config.get('my_param', 'default')

    assert '_test_reg_abc' in _registry


def test_register_coercion_stores_callable_in_registry():
    @register_coercion('_test_callable_abc', description='test')
    def TestCallableAbc(v, config, source_url=None):
        return v

    assert callable(_registry['_test_callable_abc'])


def test_register_coercion_function_is_callable():
    @register_coercion('_test_fn_abc', description='test')
    def TestFnAbc(v, config, source_url=None):
        return str(v) + '_processed'

    result = _registry['_test_fn_abc']('hello', {})
    assert result == 'hello_processed'


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


def test_factory_doc_preserved():
    @register_coercion('_test_doc_abc', description='test')
    def TestDocAbc(v, config, source_url=None):
        """My docstring."""
        return v

    assert TestDocAbc.__doc__ == 'My docstring.'


def test_factory_yosoi_type_in_schema_extra():
    @register_coercion('_test_type_abc', description='test')
    def TestTypeSchemaAbc(v, config, source_url=None):
        return v

    field = TestTypeSchemaAbc()
    assert isinstance(field.json_schema_extra, dict)
    assert field.json_schema_extra['yosoi_type'] == '_test_type_abc'


def test_factory_config_kwarg_goes_to_schema_extra():
    @register_coercion('_test_config_abc', description='test', my_setting='off')
    def TestConfigTypeAbc(v, config, source_url=None):
        return v

    field = TestConfigTypeAbc(my_setting='on')
    assert isinstance(field, FieldInfo)
    assert isinstance(field.json_schema_extra, dict)
    assert field.json_schema_extra['my_setting'] == 'on'


def test_factory_config_kwarg_default_in_schema_extra():
    @register_coercion('_test_default_abc', description='test', rate=0.5)
    def TestDefaultAbc(v, config, source_url=None):
        return v

    field = TestDefaultAbc()
    assert isinstance(field.json_schema_extra, dict)
    assert field.json_schema_extra['rate'] == 0.5


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


def test_factory_description_default():
    @register_coercion('_test_desc_def_abc', description='Default desc')
    def TestDescDefAbc(v, config, source_url=None):
        return v

    field = TestDescDefAbc()
    assert field.description == 'Default desc'


def test_factory_description_can_be_overridden():
    @register_coercion('_test_desc_override_abc', description='Default desc')
    def TestDescOverrideAbc(v, config, source_url=None):
        return v

    field = TestDescOverrideAbc(description='Custom desc')
    assert field.description == 'Custom desc'
