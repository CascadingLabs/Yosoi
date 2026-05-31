"""Tests for Contract schema generation, selector overrides, and validators."""

import pytest
from pydantic import Field
from pydantic_ai import Agent, capture_run_messages
from pydantic_ai.models.test import TestModel

import yosoi as ys
from yosoi.models.contract import Contract
from yosoi.types.field import Field as YsField
from yosoi.types.price import Price


class SampleContract(Contract):
    """Sample contract with custom types and hints."""

    item_price: float = Price(currency_symbol='£', description='Look for GBP symbol')
    name: str = Field(description='The name of the item')


class OverrideContract(Contract):
    """Contract with a mix of AI-discovered and selector-overridden fields."""

    title: str = Field(description='The item title')
    price: float = YsField(description='The item price', selector='p.price_color')  # type: ignore[assignment]
    rating: str = YsField(description='Star rating', selector='p.star-rating')  # type: ignore[assignment]


class BookContract(Contract):
    title: str = ys.Title()
    price: float = ys.Price()
    author: str = ys.Author()


# ---------------------------------------------------------------------------
# Selector model metadata
# ---------------------------------------------------------------------------


def test_selector_model_metadata_preservation():
    """Verify that to_selector_model preserves field descriptions."""
    SelectorModel = SampleContract.to_selector_model()

    price_field = SelectorModel.model_fields['item_price']
    assert price_field.description == 'Look for GBP symbol'

    name_field = SelectorModel.model_fields['name']
    assert name_field.description == 'The name of the item'


def test_pydantic_ai_schema_rendering():
    """Verify that Pydantic AI receives the metadata in the schema."""
    SelectorModel = SampleContract.to_selector_model()
    model = TestModel()
    agent = Agent(model, output_type=SelectorModel)

    import contextlib

    with capture_run_messages(), contextlib.suppress(BaseException):
        agent.run_sync('Test')

    schema = SelectorModel.model_json_schema()

    price_properties = schema['properties']['item_price']
    assert '$ref' in price_properties

    # The field description flows through to the selector schema.
    assert schema['properties']['item_price']['description'] == 'Look for GBP symbol'
    assert schema['properties']['name']['description'] == 'The name of the item'


# ---------------------------------------------------------------------------
# Selector overrides
# ---------------------------------------------------------------------------


def test_overridden_fields_excluded_from_selector_model():
    """Fields with yosoi_selector must not appear in the LLM selector model."""
    SelectorModel = OverrideContract.to_selector_model()
    fields = SelectorModel.model_fields

    assert 'title' in fields
    assert 'price' not in fields
    assert 'rating' not in fields


def test_overridden_fields_excluded_from_field_descriptions():
    """field_descriptions() must omit overridden fields."""
    descriptions = OverrideContract.field_descriptions()

    assert 'title' in descriptions
    assert 'price' not in descriptions
    assert 'rating' not in descriptions


def test_get_selector_overrides_returns_correct_mapping():
    """get_selector_overrides() should return only fields with yosoi_selector set."""
    overrides = OverrideContract.get_selector_overrides()

    assert overrides == {
        'price': {'primary': 'p.price_color'},
        'rating': {'primary': 'p.star-rating'},
    }
    assert 'title' not in overrides


def test_fully_overridden_contract_produces_empty_selector_model():
    """A contract where every field is overridden yields an empty selector model."""

    class AllOverride(Contract):
        name: str = YsField(description='Name', selector='h1')  # type: ignore[assignment]
        desc: str = YsField(description='Desc', selector='p.desc')  # type: ignore[assignment]

    SelectorModel = AllOverride.to_selector_model()
    assert AllOverride.field_descriptions() == {}
    # Only root remains (always added for multi-item discovery)
    assert set(SelectorModel.model_fields.keys()) == {'root'}


# ---------------------------------------------------------------------------
# Validators inner class
# ---------------------------------------------------------------------------


def test_validators_inner_class_transforms():
    class ProductContract(Contract):
        name: str
        category: str

        class Validators:
            @staticmethod
            def name(v: str) -> str:
                return v.title()

            @staticmethod
            def category(v: str) -> str:
                return v.upper()

    result = ProductContract.model_validate({'name': 'laptop stand', 'category': 'accessories'})
    assert result.name == 'Laptop Stand'
    assert result.category == 'ACCESSORIES'


def test_validators_inner_class_value_error_propagates():
    from pydantic import ValidationError

    class StrictContract(Contract):
        price: str

        class Validators:
            @staticmethod
            def price(v: str) -> str:
                if not v.startswith('$'):
                    raise ValueError('price must start with $')
                return v

    with pytest.raises(ValidationError):
        StrictContract.model_validate({'price': '12.99'})


def test_validators_only_applies_defined_fields():
    """Fields without a Validators method are passed through unchanged."""

    class PartialContract(Contract):
        name: str
        description: str

        class Validators:
            @staticmethod
            def name(v: str) -> str:
                return v.upper()

    result = PartialContract.model_validate({'name': 'item', 'description': '  some desc  '})
    assert result.name == 'ITEM'
    assert result.description == '  some desc  '


def test_validators_and_type_coercion_combined():
    """Validators inner class runs before Price coercion."""

    class ShopContract(Contract):
        price: float = ys.Price()

        class Validators:
            @staticmethod
            def price(v: str) -> str:
                return v.removeprefix('PRICE:').strip()

    result = ShopContract.model_validate({'price': 'PRICE: £19.99'})
    assert result.price == 19.99


# ---------------------------------------------------------------------------
# generate_manifest
# ---------------------------------------------------------------------------


def test_contract_generate_manifest():
    manifest = BookContract.generate_manifest()
    assert '# BookContract' in manifest
    assert '| `price`' in manifest
    assert '`price`' in manifest


# ---------------------------------------------------------------------------
# Coverage: line 37 — _apply_validators_and_coerce when data is not a dict
# ---------------------------------------------------------------------------


def test_validators_and_coerce_passthrough_for_non_dict():
    """When data is not a dict (e.g., a Contract instance), it passes through."""

    class SimpleContract(Contract):
        name: str

    instance = SimpleContract(name='test')
    # Validate from an existing instance — should pass through
    result = SimpleContract.model_validate(instance)
    assert result.name == 'test'


# ---------------------------------------------------------------------------
# Coverage: line 62 — json_schema_extra that's not a dict
# ---------------------------------------------------------------------------


def test_yosoi_type_skipped_when_extra_not_dict():
    """When json_schema_extra is not a dict, yosoi_type coercion is skipped."""

    class PlainContract(Contract):
        name: str = Field(description='A name')

    result = PlainContract.model_validate({'name': 'hello'})
    assert result.name == 'hello'


# ---------------------------------------------------------------------------
# Coverage: line 127 — generate_manifest with docstring
# ---------------------------------------------------------------------------


def test_generate_manifest_includes_docstring():
    """generate_manifest includes the contract docstring if present."""

    class DocumentedContract(Contract):
        """This is a documented contract."""

        title: str

    manifest = DocumentedContract.generate_manifest()
    assert '# DocumentedContract' in manifest
    assert 'This is a documented contract.' in manifest


def test_generate_manifest_without_docstring():
    """generate_manifest works without a docstring."""

    class UndocContract(Contract):
        title: str

    manifest = UndocContract.generate_manifest()
    assert '# UndocContract' in manifest


# ---------------------------------------------------------------------------
# Coverage: line 146 — Contract.define(name) returning ContractBuilder
# ---------------------------------------------------------------------------


def test_contract_define_returns_builder():
    """Contract.define() returns a ContractBuilder."""
    from yosoi.models.contract import ContractBuilder

    builder = Contract.define('MySchema')
    assert isinstance(builder, ContractBuilder)


# ---------------------------------------------------------------------------
# Coverage: lines 154-155 — ContractBuilder.__getattr__ raises for dunder
# ---------------------------------------------------------------------------


def test_contract_builder_dunder_raises_attribute_error():
    """Accessing dunder attributes on ContractBuilder raises AttributeError."""
    builder = Contract.define('Test')
    with pytest.raises(AttributeError):
        _ = builder.__foobar__


# ---------------------------------------------------------------------------
# Coverage: lines 159-166 — ContractBuilder.__getattr__ _add function
# ---------------------------------------------------------------------------


def test_contract_builder_add_field():
    """ContractBuilder allows adding fields via attribute access."""
    builder = Contract.define('Product')
    result = builder.title('The product title')
    # Returns self for chaining
    assert result is builder


def test_contract_builder_chain_fields():
    """ContractBuilder supports method chaining for multiple fields."""
    builder = Contract.define('Product').title('Title').price('Price', type=float)
    assert builder is not None


# ---------------------------------------------------------------------------
# Coverage: lines 170-171 — ContractBuilder.build()
# ---------------------------------------------------------------------------


def test_contract_builder_build_creates_contract():
    """ContractBuilder.build() creates a Contract subclass."""
    MyContract = Contract.define('DynContract').title('The title').price('The price', type=float).build()
    assert issubclass(MyContract, Contract)
    assert 'title' in MyContract.model_fields
    assert 'price' in MyContract.model_fields


def test_contract_builder_build_validates_data():
    """Built contract can validate data."""
    MyContract = Contract.define('ValidContract').name('Name field').build()
    instance = MyContract.model_validate({'name': 'Test'})
    assert instance.name == 'Test'


# ---------------------------------------------------------------------------
# ContractBuilder.with_root
# ---------------------------------------------------------------------------


def test_contract_builder_with_root_sets_root():
    """with_root() sets the root ClassVar on the built contract."""
    from yosoi.models.selectors import SelectorEntry, css

    MyContract = Contract.define('RootedContract').title('Title').with_root(css('.item')).build()
    assert MyContract.root is not None
    assert isinstance(MyContract.root, SelectorEntry)
    assert MyContract.root.value == '.item'
    assert MyContract.root.type == 'css'


def test_contract_builder_with_root_is_grouped():
    """Built contract with root reports is_grouped=True."""
    from yosoi.models.selectors import css

    MyContract = Contract.define('GroupedContract').title('Title').with_root(css('.row')).build()
    assert MyContract.is_grouped() is True


def test_contract_builder_without_root_not_grouped():
    """Built contract without root reports is_grouped=False."""
    MyContract = Contract.define('UngroupedContract').title('Title').build()
    assert MyContract.is_grouped() is False


# ---------------------------------------------------------------------------
# root ClassVar — not treated as a Pydantic field
# ---------------------------------------------------------------------------


def test_root_classvary_not_in_model_fields():
    """root is a ClassVar and must not appear in model_fields."""

    class Listed(Contract):
        root = ys.css('article.item')
        name: str = ys.Title()

    assert 'root' not in Listed.model_fields
    assert Listed.root is not None


def test_is_grouped_classmethod():
    """is_grouped() returns True only when root is explicitly set."""

    class WithRoot(Contract):
        root = ys.css('.card')
        title: str = ys.Title()

    class WithoutRoot(Contract):
        title: str = ys.Title()

    assert WithRoot.is_grouped() is True
    assert WithoutRoot.is_grouped() is False


# ---------------------------------------------------------------------------
# list[T] coercion in _apply_validators_and_coerce
# ---------------------------------------------------------------------------


def test_coerce_list_field_from_list_input():
    """list[str] + ['a', 'b'] → passes through (Pattern A)."""

    class TagContract(Contract):
        tags: list[str] = YsField(description='tags')

    result = TagContract.model_validate({'tags': ['a', 'b']})
    assert result.tags == ['a', 'b']


def test_coerce_list_field_splits_string():
    """list[str] + 'a, b and c' → ['a', 'b', 'c']."""

    class TagContract(Contract):
        tags: list[str] = YsField(description='tags')

    result = TagContract.model_validate({'tags': 'a, b and c'})
    assert result.tags == ['a', 'b', 'c']


def test_coerce_list_field_splits_single_item_list():
    """list[str] + ['a, b and c'] → ['a', 'b', 'c'] (Pattern B)."""

    class TagContract(Contract):
        tags: list[str] = YsField(description='tags')

    result = TagContract.model_validate({'tags': ['a, b and c']})
    assert result.tags == ['a', 'b', 'c']


def test_coerce_list_field_no_split_when_truly_single():
    """list[str] + ['hello'] → stays ['hello'] when split produces 1 item."""

    class TagContract(Contract):
        tags: list[str] = YsField(description='tags')

    result = TagContract.model_validate({'tags': ['hello']})
    assert result.tags == ['hello']


def test_coerce_list_field_with_yosoi_type():
    """list[float] = ys.Price() + ['$1.50', '$2.00'] → [1.5, 2.0]."""

    class PriceList(Contract):
        prices: list[float] = ys.Price()

    result = PriceList.model_validate({'prices': ['$1.50', '$2.00']})
    assert result.prices == [1.5, 2.0]


def test_coerce_list_field_custom_delimiter():
    """delimiter=r'\\|' + 'a|b|c' → ['a', 'b', 'c']."""

    class PipeContract(Contract):
        items: list[str] = YsField(description='items', delimiter=r'\|')

    result = PipeContract.model_validate({'items': 'a|b|c'})
    assert result.items == ['a', 'b', 'c']


def test_coerce_list_field_with_non_string_non_list():
    """Non-string, non-list raw value is wrapped in a list."""
    from yosoi.models.contract import _coerce_list_field

    # e.g. an integer or None-like value → wrapped in list
    result = _coerce_list_field(42, {}, None)
    assert result == [42]


def test_coerce_list_field_multi_item_list_passes_through():
    """Multi-item list input is passed through without splitting."""
    from yosoi.models.contract import _coerce_list_field

    result = _coerce_list_field(['a', 'b', 'c'], {}, None)
    assert result == ['a', 'b', 'c']


def test_apply_validators_and_coerce_with_non_dict():
    """_apply_validators_and_coerce passes non-dict data directly to handler."""

    class SimpleC(Contract):
        title: str

    # Passing an existing instance → model_validate returns it unchanged
    existing = SimpleC(title='hi')
    result = SimpleC.model_validate(existing)
    assert result.title == 'hi'


def test_apply_validators_and_coerce_calls_validators_class():
    """When a nested Validators class defines a field method, it transforms the value."""

    class WithValidators(Contract):
        name: str

        class Validators:
            @staticmethod
            def name(value: str) -> str:
                return value.upper()

    result = WithValidators.model_validate({'name': 'hello'})
    assert result.name == 'HELLO'


def test_list_fields_returns_inner_types():
    """list_fields() returns {field_name: inner_type} for list[T] fields."""

    class TagContract(Contract):
        tags: list[str] = YsField(description='tags')
        title: str = YsField(description='title')

    lf = TagContract.list_fields()
    assert 'tags' in lf
    assert lf['tags'] is str
    assert 'title' not in lf


def test_list_fields_empty_when_no_list_fields():
    """list_fields() returns {} when no list fields are defined."""

    class FlatC(Contract):
        title: str
        price: float

    assert FlatC.list_fields() == {}


def test_action_fields_returns_js_action_config():
    """action_fields() returns {field_name: action_config} for ys.js fields."""

    class TechContract(Contract):
        title: str = ys.Title()
        signals: dict = ys.js('(() => ({has_alita: true}))()', default=None)  # type: ignore[assignment]

    actions = TechContract.action_fields()
    assert 'signals' in actions
    assert actions['signals']['type'] == 'js'
    assert actions['signals']['script'] == '(() => ({has_alita: true}))()'
    assert 'title' not in actions


def test_action_fields_excluded_from_discovery():
    """discovery_field_names() excludes fields annotated with yosoi_action."""

    class TechContract(Contract):
        title: str = ys.Title()
        signals: dict = ys.js('(() => ({}))()', default=None)  # type: ignore[assignment]

    names = TechContract.discovery_field_names()
    assert 'title' in names
    assert 'signals' not in names


def test_action_fields_excluded_from_field_descriptions():
    """field_descriptions() excludes action fields."""

    class TechContract(Contract):
        title: str = ys.Title(description='Main title')
        signals: dict = ys.js('(() => ({}))()', default=None)  # type: ignore[assignment]

    descs = TechContract.field_descriptions()
    assert 'title' in descs
    assert 'signals' not in descs


# ---------------------------------------------------------------------------
# undiscovered_action_fields coverage (lines 145, 151, 170, 174-178)
# ---------------------------------------------------------------------------

import yosoi as ys


class _JsHandAuthoredContract(Contract):
    """Hand-authored js(script=...) fields should NOT appear in undiscovered."""

    signal: str = ys.js(script='(() => window.__signal__)()')


class _JsDiscoveryContract(Contract):
    """Discovery-driven js(description=...) fields appear in undiscovered."""

    signal: str = ys.js(description='Detect competitor widgets')


class _NoActionContract(Contract):
    """No action fields — undiscovered returns {}."""

    title: str = ys.Title()


def test_undiscovered_action_fields_excludes_hand_authored():
    """Fields with an explicit script= are already authored and must not appear (lines 174-175)."""
    result = _JsHandAuthoredContract.undiscovered_action_fields()
    assert 'signal' not in result


def test_undiscovered_action_fields_includes_description_only():
    """Fields with only description= (no script) need discovery (lines 176-178)."""
    result = _JsDiscoveryContract.undiscovered_action_fields()
    assert 'signal' in result
    assert result['signal'] == 'Detect competitor widgets'


def test_undiscovered_action_fields_skips_non_dict_extra():
    """Fields where json_schema_extra is not a dict are skipped (line 170)."""
    result = _NoActionContract.undiscovered_action_fields()
    assert result == {}


def test_discovery_field_names_includes_action_field_free_fields():
    """discovery_field_names skips fields that are action_fields (line 252-253)."""
    names = _JsDiscoveryContract.discovery_field_names()
    # JS action fields are excluded from discovery_field_names
    assert 'signal' not in names


def test_list_field_coercion_skips_none_values():
    """List field coercion silently skips None list field values (line 151)."""

    class _OptListContract(Contract):
        tags: list[str] | None = ys.Field(default=None)

    result = _OptListContract.model_validate({'tags': None})
    assert result.tags is None


def test_undiscovered_action_fields_skips_fields_without_json_extra():
    """Fields with no json_schema_extra (e.g. bare `str` annotation) are skipped (line 170)."""

    class _BareContract(Contract):
        name: str  # no json_schema_extra at all → json_schema_extra is None

    result = _BareContract.undiscovered_action_fields()
    assert 'name' not in result


def test_list_field_coercion_skips_none_via_validation_error():
    """List field coercion continues on None value before pydantic raises (line 151)."""
    from pydantic import ValidationError

    class _ListContract(Contract):
        tags: list[str] = ys.Field()

    # The mode='before' validator runs first (line 151 continue), then pydantic rejects None
    with pytest.raises(ValidationError):
        _ListContract.model_validate({'tags': None})


def test_discovery_field_names_expands_nested_contract_fields():
    """Nested Contract-typed fields are expanded to flat parent_child names (lines 256-257)."""

    class _ChildContract(Contract):
        headline: str = ys.Title()
        author: str = ys.Author()

    class _ParentContract(Contract):
        article: _ChildContract = ys.Field()  # type: ignore[assignment]
        date: str = ys.Field()

    names = _ParentContract.discovery_field_names()
    assert 'article_headline' in names
    assert 'article_author' in names
    assert 'date' in names
    assert 'article' not in names  # the container itself is not a target


def test_to_selector_model_skips_overridden_nested_child_fields():
    """Nested child field with a parent-level override is excluded from selector model (line 286)."""

    class _ChildContract(Contract):
        headline: str = ys.Title()
        author: str = ys.Author()

    class _ParentContract(Contract):
        article: _ChildContract = ys.Field()  # type: ignore[assignment]
        title: str = ys.Field(selector='h1')  # overridden at parent level

    model = _ParentContract.to_selector_model()
    fields = model.model_fields
    # Parent-level override ('title') must be excluded
    assert 'title' not in fields
    # Nested child fields from article should be expanded
    assert 'article_headline' in fields or 'article_author' in fields


class TestCoerceField:
    """CAS-114: per-field value oracle reused by JS discovery + scrape enforcement."""

    @staticmethod
    def _contract():
        from typing import Annotated

        from pydantic import BeforeValidator

        import yosoi as ys

        def _count(v: object) -> int:
            s = str(v).strip()
            return int(s.replace(',', '')) if s and s.lower() != 'none' else 0

        class Counts(ys.Contract):
            review_count: Annotated[int, BeforeValidator(_count)] = ys.js(description='count', default=0)
            label: str = ys.Field(default='')

        return Counts

    def test_coerces_native_int(self):
        assert self._contract().coerce_field('review_count', 43) == 43

    def test_runs_before_validator_on_comma_string(self):
        assert self._contract().coerce_field('review_count', '1,234') == 1234

    def test_rejects_uncoercible_value(self):
        from pydantic import ValidationError

        with pytest.raises((ValidationError, ValueError)):
            self._contract().coerce_field('review_count', 'not a number at all')

    def test_untyped_str_field_accepts_anything(self):
        assert self._contract().coerce_field('label', 'whatever') == 'whatever'

    def test_unknown_field_passthrough(self):
        assert self._contract().coerce_field('nope', 'x') == 'x'

    def test_field_default(self):
        c = self._contract()
        assert c.field_default('review_count') == 0
        assert c.field_default('label') == ''
        assert c.field_default('missing') is None
