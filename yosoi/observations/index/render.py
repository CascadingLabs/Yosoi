"""Provider/tokenizer-specific index rendering scaffold."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from yosoi.observations.models.index import ObservationIndex
from yosoi.observations.models.view import RenderedView


class RenderPolicy(BaseModel):
    """Packing limits applied after semantic pruning and index compilation."""

    model_config = ConfigDict(frozen=True)

    tokenizer_id: str = Field(min_length=1)
    token_budget: int = Field(gt=0)


class ObservationIndexRenderer:
    """Future serializer that never reruns semantic pruning."""

    name = 'observation_index'
    version = 'scaffold'

    def render(self, index: ObservationIndex, policy: RenderPolicy) -> RenderedView:
        """Refuse rendering until deterministic provider packing is implemented."""
        raise NotImplementedError('observation index rendering is not implemented; see observations/ROADMAP.md')


__all__ = ['ObservationIndexRenderer', 'RenderPolicy']
