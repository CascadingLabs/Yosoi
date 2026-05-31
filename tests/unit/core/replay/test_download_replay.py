"""Replay-runtime coverage for the (latent) ActKind.DOWNLOAD primitive.

Nothing calls execute_plan in production yet (FUTURE: CAS-103 wires the executor, Phase 6
makes discovery emit DOWNLOAD nodes), so these drive execute_plan directly against a
download-capable fake tab to lock in the primitive's behavior.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import yosoi.core.fetcher.downloads as downloads
from yosoi.core.replay.runtime import ReplayExecutionError, execute_plan
from yosoi.models.replay import ActKind, AssertKind, ReplayAct, ReplayCondition, ReplayNode, ReplayPlan
from yosoi.models.selectors import css


class _DownloadTab:
    """Fake tab implementing the capture_download protocol (arm/click/wait)."""

    def __init__(self, *, data: bytes, content_type: str | None) -> None:
        self._data = data
        self._content_type = content_type
        self._dir: str | None = None

    async def arm_download(self, dir: str, max_bytes: int | None = None) -> object:
        self._dir = dir
        return object()

    async def click_element(self, selector: str) -> None:
        pass

    async def wait_download(self, capture: object, timeout: float = 120.0) -> Any:
        assert self._dir is not None
        path = Path(self._dir) / 'capatured.csv'
        path.write_bytes(self._data)

        class _Outcome:
            def __init__(self, p: str, ct: str | None, n: int) -> None:
                self.path = p
                self.content_type = ct
                self.bytes = n

        return _Outcome(str(path), self._content_type, len(self._data))

    async def reset_download(self) -> None:
        pass


def _download_node(output_field: str = 'rows', output: str = 'parsed') -> ReplayNode:
    return ReplayNode(
        id='dl',
        intent='download the csv',
        act=ReplayAct(
            kind=ActKind.DOWNLOAD,
            targets=[css('a.export')],
            output_field=output_field,
            metadata={'allowed_types': ['csv'], 'output': output},
        ),
        expect=ReplayCondition(kind=AssertKind.DOWNLOAD_OK),
    )


# --- validator --------------------------------------------------------------


def test_download_act_requires_target_or_url() -> None:
    with pytest.raises(ValidationError, match='download acts require'):
        ReplayAct(kind=ActKind.DOWNLOAD)


def test_download_act_forbids_repeat() -> None:
    with pytest.raises(ValidationError, match='cannot repeat'):
        ReplayAct(kind=ActKind.DOWNLOAD, targets=[css('a.dl')], repeat=True)


# --- execute_plan -----------------------------------------------------------


async def test_execute_plan_captures_download_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(downloads, 'quarantine_dir', lambda _domain: tmp_path)
    tab = _DownloadTab(data=b'm,n\n1,2\n', content_type='text/csv')

    result = await execute_plan(tab, ReplayPlan(nodes=[_download_node()]))

    assert result.passed == 1  # assess + act + DOWNLOAD_OK expect all passed
    assert result.extracted_actions['rows'] == [{'m': '1', 'n': '2'}]


async def test_execute_plan_download_bad_type_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(downloads, 'quarantine_dir', lambda _domain: tmp_path)
    tab = _DownloadTab(data=b'<html>please sign in</html>', content_type='text/html')

    with pytest.raises(ReplayExecutionError, match='allowed_types'):
        await execute_plan(tab, ReplayPlan(nodes=[_download_node()]))
