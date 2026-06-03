"""Append-only ledger for reuse :class:`DecisionRecord`s — the flywheel + queue.

Every advisory reuse decision (and its eventually back-filled outcome) is one
labelled row: ``(signal panel -> scope/verdict -> trust -> outcome)``. Persisting
them turns dogfooding into dataset generation for a future learned recommender
(CAS-85), at zero extra labelling cost.

The store is an **append-only artifact**, never mutated in place: a promotion or
review decision appends a *new* row with the same ``id``, and :meth:`current`
folds the log to the latest state per id (last writer wins). This keeps the file
a grep-able history while still answering "what is the state now?" and "what is
pending review?" — the substrate the review CLI acts over.

Records live under ``.yosoi/generalization/<date>.jsonl`` (one record per line,
date-partitioned). A corrupt/torn final line is skipped, not fatal.
"""

from __future__ import annotations

import logging
from pathlib import Path

from yosoi.generalization.trust import DecisionRecord, Outcome, Trust
from yosoi.utils.files import init_yosoi

logger = logging.getLogger(__name__)


class DecisionStore:
    """Append-only JSONL ledger for reuse decision records.

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

        A line that fails to parse (schema drift, a torn final write) is logged
        and skipped rather than aborting the whole load.

        Returns:
            All records, in file-then-line order (roughly chronological).
        """
        records: list[DecisionRecord] = []
        for path in sorted(self.storage_dir.glob('*.jsonl')):
            for line in path.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(DecisionRecord.model_validate_json(line))
                except ValueError:
                    logger.warning('skipping unparseable ledger line in %s', path.name)
        return records

    def current(self) -> list[DecisionRecord]:
        """Fold the append-only log to the latest record per decision id.

        A promotion/review appends a new row with the same ``id``; the last one
        wins. Rows without an id (legacy) are kept as-is, in order.

        Returns:
            One record per id (latest), in first-seen order, then any id-less
            rows.
        """
        latest: dict[str, DecisionRecord] = {}
        order: list[str] = []
        anonymous: list[DecisionRecord] = []
        for rec in self.load_all():
            if rec.id:
                if rec.id not in latest:
                    order.append(rec.id)
                latest[rec.id] = rec
            else:
                anonymous.append(rec)
        return [latest[i] for i in order] + anonymous

    def get(self, decision_id: str) -> DecisionRecord | None:
        """Return the current state of one decision by id, or None.

        Args:
            decision_id: The decision id to look up.

        Returns:
            The latest :class:`DecisionRecord` with that id, or None.
        """
        return next((r for r in self.current() if r.id == decision_id), None)

    def pending(self) -> list[DecisionRecord]:
        """Return decisions awaiting review (the queue).

        Returns:
            Current records that are flagged ``needs_review``, still QUARANTINED,
            and whose outcome is PENDING.
        """
        return [
            r
            for r in self.current()
            if r.needs_review and r.trust is Trust.QUARANTINED and r.outcome is Outcome.PENDING
        ]

    def decide(self, decision_id: str, *, confirmed: bool) -> DecisionRecord | None:
        """Promote (confirmed) or reject (refuted) a quarantined decision by id.

        Appends the resolved record (append-only); a no-op on a terminal or
        unknown decision.

        Args:
            decision_id: The decision to resolve.
            confirmed: True to confirm (VERIFIED), False to reject (REJECTED).

        Returns:
            The resolved record, or None if the id is unknown.
        """
        rec = self.get(decision_id)
        if rec is None:
            return None
        resolved = rec.promote(confirmed=confirmed)
        if resolved is not rec:
            self.append(resolved)
        return resolved

    def summary(self) -> dict[str, int]:
        """Tally current decisions by verdict, scope, trust, outcome, and queue.

        Returns:
            A flat count mapping, e.g. ``{'total': 42, 'scope:same_domain': 30,
            'trust:quarantined': 12, 'pending_review': 9, 'overrides': 3}`` — a
            quick health read of the ledger.
        """
        counts: dict[str, int] = {'total': 0, 'overrides': 0, 'pending_review': 0}
        for rec in self.current():
            counts['total'] += 1
            for key in (
                f'verdict:{rec.driver_verdict.value}',
                f'scope:{rec.scope.value}',
                f'trust:{rec.trust.value}',
                f'outcome:{rec.outcome.value}',
            ):
                counts[key] = counts.get(key, 0) + 1
            if rec.override_flag:
                counts['overrides'] += 1
            if rec.needs_review and rec.trust is Trust.QUARANTINED and rec.outcome is Outcome.PENDING:
                counts['pending_review'] += 1
        return counts
