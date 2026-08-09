"""A3 learning and deterministic replay projections over the action ledger."""

from __future__ import annotations

from typing import TYPE_CHECKING

from yosoi._lazy import lazy_exports

if TYPE_CHECKING:
    from yosoi.a3.compiler import ActionEpisodeBuilder as ActionEpisodeBuilder
    from yosoi.a3.compiler import ActionReplayCompileError as ActionReplayCompileError
    from yosoi.a3.compiler import compile_action_episode as compile_action_episode
    from yosoi.a3.models import A3_ACTION_SCHEMA_VERSION as A3_ACTION_SCHEMA_VERSION
    from yosoi.a3.models import ActionEpisode as ActionEpisode
    from yosoi.a3.models import ActionEpisodeStep as ActionEpisodeStep
    from yosoi.a3.models import ActionReplayPlan as ActionReplayPlan
    from yosoi.a3.models import ActionReplayRun as ActionReplayRun
    from yosoi.a3.models import ActionReplayStep as ActionReplayStep
    from yosoi.a3.models import AxPropertyExpectation as AxPropertyExpectation
    from yosoi.a3.models import ReplayExpectation as ReplayExpectation
    from yosoi.a3.models import ReplayRunStatus as ReplayRunStatus
    from yosoi.a3.models import ReplayTargetSignature as ReplayTargetSignature
    from yosoi.a3.runtime import ActionReplayExecutor as ActionReplayExecutor
    from yosoi.a3.runtime import AxReplayVerifier as AxReplayVerifier
    from yosoi.a3.runtime import ReplaySnapshotCapture as ReplaySnapshotCapture
    from yosoi.a3.storage import ActionEpisodeStore as ActionEpisodeStore

_MODELS = {
    'A3_ACTION_SCHEMA_VERSION',
    'ActionEpisode',
    'ActionEpisodeStep',
    'ActionReplayPlan',
    'ActionReplayRun',
    'ActionReplayStep',
    'AxPropertyExpectation',
    'ReplayExpectation',
    'ReplayRunStatus',
    'ReplayTargetSignature',
}
_LAZY = dict.fromkeys(_MODELS, 'yosoi.a3.models')
_LAZY.update(
    {
        'ActionEpisodeBuilder': 'yosoi.a3.compiler',
        'ActionReplayCompileError': 'yosoi.a3.compiler',
        'compile_action_episode': 'yosoi.a3.compiler',
        'ActionReplayExecutor': 'yosoi.a3.runtime',
        'AxReplayVerifier': 'yosoi.a3.runtime',
        'ReplaySnapshotCapture': 'yosoi.a3.runtime',
        'ActionEpisodeStore': 'yosoi.a3.storage',
    }
)

__all__ = sorted(_LAZY)
__getattr__, __dir__ = lazy_exports(__name__, globals(), _LAZY)
