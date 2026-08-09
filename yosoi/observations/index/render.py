"""Provider-specific packing of an existing index into a budgeted overview.

Semantic pruning decides what is *addressable*; rendering decides what is *resident*. They are
separate because they fail differently. The Wikipedia negative control makes the split concrete:
its structured index is a correct reduction of the article and is still 84 KiB across 1,038
entries, because unique prose is deliberately preserved. No amount of better pruning fixes that
— dropping the prose would destroy the evidence the index exists to address. What fixes it is
sending a smaller *view* of the same index, with every omitted entry still one `inspect` away.

So this module never re-derives anything. It reads a compiled index, chooses entries under a
declared budget, and states what it left out. An omission the reader cannot see is the failure
mode here: a short overview that silently dropped 900 entries reads exactly like a short page.
"""

from __future__ import annotations

import math
import re
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from yosoi.observations.models.index import IndexEntry, ObservationIndex
from yosoi.observations.models.view import Pagination, RenderedView

RENDERER_VERSION = '2'

_HEADING = re.compile(r'^h[1-6]\b')
_ELLIPSIS = '…'


@runtime_checkable
class Tokenizer(Protocol):
    """Counts tokens the way one provider counts them."""

    id: str

    def count(self, text: str) -> int:
        """Return the number of tokens this provider would charge for `text`."""
        ...


class CharacterEstimator:
    """Deterministic, dependency-free token estimate: one token per four characters.

    Explicitly an ESTIMATE, and named so in `id`, because this package has no provider
    tokenizer and inventing precision it does not have would be worse than approximating
    openly. Real provider tokenizers plug in by implementing `Tokenizer`; the renderer refuses
    any tokenizer whose `id` disagrees with the policy it was handed, so a rendering can never
    claim a budget it was not measured against.

    Every gate that uses this pairs the token budget with a byte budget, since bytes are the
    thing actually being measured.
    """

    id = 'estimate/chars-per-token-4'

    def count(self, text: str) -> int:
        """Return the estimated token count for `text`."""
        return math.ceil(len(text) / 4)


class RenderPolicy(BaseModel):
    """Packing limits applied after semantic pruning and index compilation."""

    model_config = ConfigDict(frozen=True)

    tokenizer_id: str = Field(min_length=1)
    token_budget: int = Field(gt=0)
    max_entry_tokens: int = Field(default=48, gt=0)
    """Per-line ceiling, so one 4,000-character summary cannot consume a whole overview."""


def _tier(entry: IndexEntry) -> int:
    """Rank one entry's claim on a scarce overview slot. Lower wins.

    The ordering is an argument about what an agent cannot recover on its own. Headings are the
    page's own table of contents and there are few of them, so they come first: a section a
    reader cannot see is a section they cannot ask to inspect. Regions come next — each stands
    in for members that would otherwise never be known to exist — then entries carrying an
    identity, since those are what a later capture can be compared against. Body prose is last
    not because it matters least, but because it is exactly what `inspect` is for.

    Headings before regions was learned, not assumed: on a 1,038-entry article the 81 regions
    consumed the whole budget first and every one of the 17 section headings was starved out.
    """
    if entry.label == 'document':
        return 0
    if _HEADING.match(entry.label):
        return 1
    if entry.coverage is not None:
        return 2
    if entry.ref_id is not None:
        return 3
    return 4


class ObservationIndexRenderer:
    """Serialise an existing index under a token budget, without re-pruning anything."""

    name = 'observation_index'
    version = RENDERER_VERSION

    def render(self, index: ObservationIndex, policy: RenderPolicy, tokenizer: Tokenizer | None = None) -> RenderedView:
        """Return a budgeted overview of `index` plus an explicit account of what it omits."""
        counter = tokenizer or CharacterEstimator()
        if counter.id != policy.tokenizer_id:
            raise ValueError(f'tokenizer {counter.id!r} cannot measure a budget declared for {policy.tokenizer_id!r}')

        lines = {entry.ordinal: self._line(entry, policy, counter) for entry in index.entries}
        units: list[list[IndexEntry]] = []
        for entry in index.entries:
            if entry.bound_to_previous and units:
                units[-1].append(entry)
            else:
                units.append([entry])
        order = sorted(units, key=lambda unit: (min(_tier(entry) for entry in unit), unit[0].ordinal))

        # Reserve the LONGEST possible footer up front. An overview that spent its last token on
        # one more entry, and so could not say what it dropped, is the failure mode here.
        reserved = counter.count(self._footer(len(index.entries), 0, index.page)) + 1
        chosen: set[int] = set()
        spent = reserved
        for unit in order:
            cost = sum(counter.count(lines[entry.ordinal]) + 1 for entry in unit)
            if spent + cost > policy.token_budget:
                continue
            chosen.update(entry.ordinal for entry in unit)
            spent += cost

        selected = [entry for entry in index.entries if entry.ordinal in chosen]
        text = '\n'.join(
            [*(lines[entry.ordinal] for entry in selected), self._footer(len(index.entries), len(selected), index.page)]
        )
        return RenderedView(
            text=text,
            included_refs=tuple(entry.ref for entry in selected),
            renderer_name=self.name,
            renderer_version=self.version,
            tokenizer_id=counter.id,
            token_budget=policy.token_budget,
            token_count=counter.count(text),
            truncated=len(selected) < len(index.entries),
        )

    def _line(self, entry: IndexEntry, policy: RenderPolicy, counter: Tokenizer) -> str:
        """Render one entry as `[ordinal] label  summary`, clipped to the per-line ceiling."""
        head = f'[{entry.ordinal}] {entry.label}'
        summary = ' '.join(entry.summary.split())
        line = f'{head}  {summary}' if summary else head
        if counter.count(line) <= policy.max_entry_tokens:
            return line
        # Clip the summary, never the label or the ordinal: the handle must survive.
        room = max(0, policy.max_entry_tokens - counter.count(head) - 1)
        clipped = summary
        while clipped and counter.count(clipped) > room:
            clipped = clipped[: max(0, len(clipped) - 8)]
        return f'{head}  {clipped}{_ELLIPSIS}' if clipped else head

    def _footer(self, held: int, shown: int, page: Pagination | None = None) -> str:
        """State the omission explicitly — both omissions, when the index is itself a page.

        There are two: the entries this rendering left out, which ARE inspectable by ordinal,
        and the candidates the reduction never handed to this index, which are not. Reporting
        only the first told a reader that 937 of 1,000 entries were missing from a page whose
        reduction proposed 271,134, and called all of them inspectable.
        """
        omitted = held - shown
        resident = (
            f'— {held} of {held} entries shown'
            if omitted <= 0
            else f'— {shown} of {held} entries shown, {omitted} omitted but inspectable by [ordinal]'
        )
        if page is None or page.complete:
            return f'{resident}; inspect any by its [ordinal] —' if omitted <= 0 else f'{resident} —'
        beyond = page.total - (page.offset + page.returned)
        return (
            f'{resident}; this index is candidates {page.offset}–{page.offset + page.returned - 1} '
            f'of {page.total} — {beyond} more are NOT in it'
            + (f'; next page at offset {page.next_offset} —' if page.next_offset is not None else ' —')
        )


__all__ = ['RENDERER_VERSION', 'CharacterEstimator', 'ObservationIndexRenderer', 'RenderPolicy', 'Tokenizer']
