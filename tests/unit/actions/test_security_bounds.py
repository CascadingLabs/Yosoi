import subprocess
import sys

import pytest
from pydantic import ValidationError

from yosoi.actions.models import ActionSpec, EffectClass, ElementRef
from yosoi.observations.models.artifact import EvidenceKind
from yosoi.observations.models.view import RegionRef

_SHA = 'a' * 64


def _region() -> RegionRef:
    return RegionRef(
        snapshot_id='s',
        artifact_sha256=_SHA,
        modality=EvidenceKind.RENDERED_DOM,
        locator='//*[@id="target"]',
    )


def test_first_slice_has_no_write_secret_or_unknown_effect_class() -> None:
    assert {effect.value for effect in EffectClass} == {'observation', 'reversible_ui'}
    for effect in ('unknown', 'local_unsaved_input', 'authenticated_external_write', 'destructive'):
        with pytest.raises(ValidationError):
            ActionSpec.model_validate({'kind': 'back', 'effect': effect})


@pytest.mark.parametrize(
    'selector',
    [
        'input[type=password]',
        '[value=visible-secret]',
        '[data-token="visible"]',
        '[data-cookie="visible"]',
        '[authorization="bearer"]',
    ],
)
def test_selector_hints_cannot_be_a_secret_or_auth_side_channel(selector: str) -> None:
    with pytest.raises(ValidationError, match='secret-bearing'):
        ElementRef(snapshot_id='s', evidence=(_region(),), selector_hints=(selector,))


def test_actions_package_does_not_pull_qa_browser_or_provider_runtime() -> None:
    probe = """
import sys
import yosoi.actions
assert not any(name.startswith("yosoi.qa") for name in sys.modules)
assert "yosoi.core.fetcher.voiddriver" not in sys.modules
assert "pydantic_ai" not in sys.modules
"""
    subprocess.run([sys.executable, '-c', probe], check=True)
