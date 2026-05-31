"""Append-only store for reuse :class:`DecisionRecord`s — the flywheel ledger.

Every advisory reuse decision (and its eventually back-filled outcome) is one
labelled row: ``(signal panel -> suggested/taken action -> verified outcome)``.
Persisting them turns dogfooding into dataset generation for a future learned
recommender (CAS-85), at zero extra labelling cost — the discovery agent's
semantic verification supplies the ground-truth outcome for free.

Records are written as JSON Lines under ``.yosoi/generalization/<date>.jsonl``
(one record per line, append-only, grep-able, no DB). The date partition keeps
files small and makes a day's dogfood run easy to inspect or discard.
"""

from __future__ import annotations

from pathlib import Path

from yosoi.generalization.trust import DecisionRecord
from yosoi.utils.files import init_yosoi


class DecisionStore:
    """Append-only JSONL store for reuse decision records.

    Attributes:
        storage_dir: Directory (under the Yosoi home) holding the JSONL files.
    """

    def __init__(self, storage_dir: str = 'generalization') -> None:
        """Initialize the store under ``.yosoi/<storage_dir>/``.

        Args:
            storage_dir: Sub-directory under the Yosoi home for decision files.
        """
        self.storage_dir = Path(init_yosoi(storage_dir))

    def _file_for(self, record: DecisionRecord) -> Path:
        """Return the JSONL path a record belongs in (partitioned by date)."""
        day = record.decided_at.date().isoformat()
        return self.storage_dir / f'{day}.jsonl'

    def append(self, record: DecisionRecord) -> Path:
        """Append one decision record as a JSON line.

        Args:
            record: The decision to persist.

        Returns:
            The path of the JSONL file the record was written to.
        """
        path = self._file_for(record)
        with path.open('a', encoding='utf-8') as fh:
            fh.write(record.model_dump_json() + '\n')
        return path

    def load_all(self) -> list[DecisionRecord]:
        """Load every stored decision record across all date partitions.

        Returns:
            All records, in file-then-line order (roughly chronological).
        """
        records: list[DecisionRecord] = []
        for path in sorted(self.storage_dir.glob('*.jsonl')):
            for line in path.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if line:
                    records.append(DecisionRecord.model_validate_json(line))
        return records

    def summary(self) -> dict[str, int]:
        """Tally stored records by suggested action and outcome.

        Returns:
            A flat count mapping, e.g. ``{'total': 42, 'action:try_reuse': 30,
            'outcome:pending': 12, 'overrides': 3}`` — a quick health read of the
            dogfood ledger.
        """
        counts: dict[str, int] = {'total': 0, 'overrides': 0}
        for rec in self.load_all():
            counts['total'] += 1
            counts[f'verdict:{rec.driver_verdict.value}'] = counts.get(f'verdict:{rec.driver_verdict.value}', 0) + 1
            counts[f'outcome:{rec.outcome.value}'] = counts.get(f'outcome:{rec.outcome.value}', 0) + 1
            if rec.override_flag:
                counts['overrides'] += 1
        return counts
