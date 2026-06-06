"""Guard: every headline number in a FINDINGS_*.md must appear in a results/*.txt.

Why this exists: twice during this spike a findings doc carried numbers that were
hand-authored BEFORE (or without) the run that supposedly produced them — once a
'real embedding run' that never executed, once contrastive numbers written ahead of
the output. Both are trust defects: a reader can't tell which numbers are real.

This test enforces the rule the governance review demanded: a findings doc may only
state a numeric result that is grounded in a committed results file. It greps decimal
numbers out of fenced ``` blocks in each FINDINGS_*.md (where the results tables live)
and asserts each appears verbatim somewhere under results/. Prose numbers outside code
fences (rounded approximations, '~3.7x', citys like 'n=52') are NOT checked — only the
fenced result blocks, which is where fabrication does real damage.

Run: uv run pytest experiments/scope_spike/test_findings_numbers.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

HERE = Path(__file__).parent
RESULTS = HERE / 'results'

# decimals like 0.90, 0.584, 47, 12.5 — the shape of a reported metric
_NUM = re.compile(r'(?<![\w.])\d+\.\d+(?![\w.])')

# Numbers that are structural/illustrative, not run outputs — exempt.
_EXEMPT = {
    '0.0',
    '1.0',
    '0.5',
    '0.90',
    '0.15',  # thresholds/limits cited generically
}


def _fenced_blocks(md: str) -> list[str]:
    """Return the contents of ``` fenced code blocks (where result tables live)."""
    return re.findall(r'```[^\n]*\n(.*?)```', md, flags=re.DOTALL)


def _results_corpus() -> str:
    """All committed results text concatenated — the ground truth."""
    if not RESULTS.is_dir():
        return ''
    return '\n'.join(p.read_text() for p in RESULTS.glob('*.txt'))


def _findings_files() -> list[Path]:
    return sorted(HERE.glob('FINDINGS_*.md'))


@pytest.mark.parametrize('md_path', _findings_files(), ids=lambda p: p.name)
def test_fenced_numbers_are_grounded(md_path: Path) -> None:
    """Every decimal inside a fenced block must appear in some results/*.txt."""
    corpus = _results_corpus()
    blocks = _fenced_blocks(md_path.read_text())
    ungrounded: list[str] = []
    for block in blocks:
        for num in _NUM.findall(block):
            if num in _EXEMPT:
                continue
            if num not in corpus:
                ungrounded.append(num)
    assert not ungrounded, (
        f'{md_path.name}: fenced result numbers not found in any results/*.txt '
        f'(hand-authored or stale?): {sorted(set(ungrounded))}'
    )


def test_there_are_findings_and_results() -> None:
    """Guard the guard: it must actually have files to check."""
    assert _findings_files(), 'no FINDINGS_*.md found'
    assert _results_corpus(), 'no results/*.txt found to validate against'
