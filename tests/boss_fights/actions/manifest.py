"""Offline metadata for the first action boss-fight slice."""

from __future__ import annotations

import json
from enum import Enum
from urllib.parse import parse_qsl, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from yosoi.actions.models import ActionKind, EffectClass


class InputMechanism(str, Enum):
    HTML_NAVIGATION = 'html_navigation'
    ARIA_CONTROL = 'aria_control'
    LAYER_CONTROL = 'layer_control'
    AJAX_CONTROL = 'ajax_control'
    SCROLL_GESTURE = 'scroll_gesture'
    KEYBOARD = 'keyboard'


class EvidenceModality(str, Enum):
    SOURCE_HTML = 'source_html'
    RENDERED_DOM = 'rendered_dom'
    AX_TREE = 'ax_tree'
    NETWORK = 'network'
    URL_HISTORY = 'url_history'
    GEOMETRY = 'geometry'


class Lane(str, Enum):
    CANDIDATE = 'candidate'
    LIVE_SMOKE = 'live_smoke'
    FROZEN = 'frozen'
    SELFHOST = 'selfhost'


class Freshness(str, Enum):
    UNPINNED = 'unpinned'
    PINNED = 'pinned'


_SECRET_QUERY_KEYS = frozenset({'access_token', 'api_key', 'authorization', 'cookie', 'password', 'secret', 'token'})


class ActionCase(BaseModel):
    """One auth-free candidate with explicit evidence and unsupported behavior."""

    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)

    id: str = Field(pattern=r'^A[0-5]$')
    name: str = Field(min_length=1)
    target_url: str | None = None
    action_kind: ActionKind
    input_mechanism: InputMechanism
    effect_class: EffectClass
    required_modalities: tuple[EvidenceModality, ...] = Field(min_length=1)
    postconditions: tuple[str, ...] = Field(min_length=1)
    freshness: Freshness
    lane: Lane
    fixture: str | None = None
    ci_gate: bool = False
    auth_required: bool = False
    unsupported_behavior: str = Field(min_length=1)
    deferred: bool = False

    @field_validator('postconditions')
    @classmethod
    def _nonempty_postconditions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError('postconditions must be non-empty')
        return values

    @field_validator('required_modalities')
    @classmethod
    def _unique_modalities(cls, values: tuple[EvidenceModality, ...]) -> tuple[EvidenceModality, ...]:
        if len(values) != len(set(values)):
            raise ValueError('required modalities must be unique')
        return values

    @model_validator(mode='after')
    def _policy_safe_metadata(self) -> ActionCase:
        if self.auth_required:
            raise ValueError('auth-required cases are not in the offline slice')
        if self.effect_class not in {EffectClass.OBSERVATION, EffectClass.REVERSIBLE_UI}:
            raise ValueError('write effects are not permitted')
        if self.target_url is not None:
            parts = urlsplit(self.target_url)
            if (
                parts.username
                or parts.password
                or any(key.casefold() in _SECRET_QUERY_KEYS for key, _ in parse_qsl(parts.query))
            ):
                raise ValueError('targets cannot contain credentials or secret-bearing query values')
            if parts.scheme not in {'http', 'https'} or not parts.netloc:
                raise ValueError('target_url must be an absolute HTTP(S) URL')
        if self.deferred and self.lane is not Lane.CANDIDATE:
            raise ValueError('deferred cases must remain candidates')
        if self.lane in {Lane.FROZEN, Lane.SELFHOST}:
            if self.fixture is None or self.freshness is not Freshness.PINNED:
                raise ValueError('frozen/selfhost cases require a real pinned fixture')
        elif self.fixture is not None or self.freshness is Freshness.PINNED:
            raise ValueError('unpinned candidate/live-smoke cases cannot claim a fixture')
        if self.ci_gate and self.lane not in {Lane.FROZEN, Lane.SELFHOST}:
            raise ValueError('only fixture-backed lanes can gate CI')
        if (
            self.ci_gate
            and self.target_url is not None
            and urlsplit(self.target_url).hostname not in {'localhost', '127.0.0.1'}
        ):
            raise ValueError('public targets cannot be deterministic CI gates')
        return self

    def canonical_json(self) -> str:
        """Return stable metadata serialization."""
        return json.dumps(self.model_dump(mode='json'), sort_keys=True, separators=(',', ':'), ensure_ascii=True)


CASES: tuple[ActionCase, ...] = (
    ActionCase(
        id='A0',
        name='Books HTML navigation',
        target_url='https://books.toscrape.com/',
        action_kind=ActionKind.NAVIGATE,
        input_mechanism=InputMechanism.HTML_NAVIGATION,
        effect_class=EffectClass.OBSERVATION,
        required_modalities=(EvidenceModality.SOURCE_HTML, EvidenceModality.URL_HISTORY),
        postconditions=('destination URL or document identity changes',),
        freshness=Freshness.UNPINNED,
        lane=Lane.CANDIDATE,
        unsupported_behavior='report unsupported when source HTML cannot establish navigation.',
    ),
    ActionCase(
        id='A1',
        name='W3C ARIA tabs',
        target_url='https://www.w3.org/WAI/ARIA/apg/patterns/tabs/examples/tabs-automatic/',
        action_kind=ActionKind.CLICK,
        input_mechanism=InputMechanism.ARIA_CONTROL,
        effect_class=EffectClass.REVERSIBLE_UI,
        required_modalities=(EvidenceModality.RENDERED_DOM, EvidenceModality.AX_TREE),
        postconditions=('selected tab changes', 'corresponding tabpanel becomes available'),
        freshness=Freshness.UNPINNED,
        lane=Lane.LIVE_SMOKE,
        unsupported_behavior='report unsupported when ARIA or rendered state is unavailable.',
    ),
    ActionCase(
        id='A2',
        name='UITP hidden layers',
        target_url='http://www.uitestingplayground.com/hiddenlayers',
        action_kind=ActionKind.CLICK,
        input_mechanism=InputMechanism.LAYER_CONTROL,
        effect_class=EffectClass.REVERSIBLE_UI,
        required_modalities=(
            EvidenceModality.RENDERED_DOM,
            EvidenceModality.AX_TREE,
            EvidenceModality.GEOMETRY,
        ),
        postconditions=('target layer visibility changes',),
        freshness=Freshness.UNPINNED,
        lane=Lane.LIVE_SMOKE,
        unsupported_behavior='report unsupported when hidden-layer state is not observable.',
    ),
    ActionCase(
        id='A3',
        name='UITP AJAX',
        target_url='http://www.uitestingplayground.com/ajax',
        action_kind=ActionKind.CLICK,
        input_mechanism=InputMechanism.AJAX_CONTROL,
        effect_class=EffectClass.REVERSIBLE_UI,
        required_modalities=(
            EvidenceModality.RENDERED_DOM,
            EvidenceModality.AX_TREE,
            EvidenceModality.NETWORK,
        ),
        postconditions=('new content is present', '`/ajaxdata` request settles'),
        freshness=Freshness.UNPINNED,
        lane=Lane.LIVE_SMOKE,
        unsupported_behavior='report unsupported when network evidence is unavailable.',
    ),
    ActionCase(
        id='A4',
        name='Quotes infinite scroll',
        target_url='https://quotes.toscrape.com/scroll',
        action_kind=ActionKind.SCROLL,
        input_mechanism=InputMechanism.SCROLL_GESTURE,
        effect_class=EffectClass.OBSERVATION,
        required_modalities=(EvidenceModality.RENDERED_DOM, EvidenceModality.NETWORK),
        postconditions=('additional quote records are present',),
        freshness=Freshness.UNPINNED,
        lane=Lane.LIVE_SMOKE,
        unsupported_behavior='report unsupported when incremental loading cannot be observed.',
    ),
    ActionCase(
        id='A5',
        name='TodoMVC (deferred)',
        target_url='https://todomvc.com/examples/react/dist/',
        action_kind=ActionKind.CLICK,
        input_mechanism=InputMechanism.KEYBOARD,
        effect_class=EffectClass.REVERSIBLE_UI,
        required_modalities=(EvidenceModality.RENDERED_DOM,),
        postconditions=('todo state changes',),
        freshness=Freshness.UNPINNED,
        lane=Lane.CANDIDATE,
        unsupported_behavior='deferred: requires keyboard/text input beyond the first slice.',
        deferred=True,
    ),
)


def manifest() -> tuple[ActionCase, ...]:
    """Return the immutable first-slice metadata."""
    return CASES


def canonical_manifest_json() -> str:
    """Serialize all cases deterministically without filesystem or network access."""
    return json.dumps(
        [case.model_dump(mode='json') for case in CASES], sort_keys=True, separators=(',', ':'), ensure_ascii=True
    )


__all__ = [
    'CASES',
    'ActionCase',
    'ActionKind',
    'EffectClass',
    'EvidenceModality',
    'Freshness',
    'InputMechanism',
    'Lane',
    'canonical_manifest_json',
    'manifest',
]
