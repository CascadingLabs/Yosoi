"""Bounded, gold-blind joint selection of one root and flat record fields.

This is a research-only assignment primitive. It chooses one scored root proposal,
then assigns field score vectors to distinct ``(node_id, projection)`` evidence
keys beneath that root. The outer-root constraint does not infer ownership across
nested or sibling records; sibling branches inside one proposed root can still be
combined. It does not implement arbitrary nested Contract composition.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from numbers import Real
from typing import Any

METHOD = "joint_field_assignment"
MAX_FIELDS = 8
MAX_PER_FIELD_TOP_K = 10
MAX_ROOTS = 10
MAX_DP_TRANSITIONS = 2_000_000
TIE_ABS_TOLERANCE = 1e-12
TIE_REL_TOLERANCE = 1e-12

DEFAULT_BOUNDS = {
    "max_fields": MAX_FIELDS,
    "per_field_top_k": MAX_PER_FIELD_TOP_K,
    "max_roots": MAX_ROOTS,
    "max_dp_transitions": MAX_DP_TRANSITIONS,
}

METHOD_METADATA: dict[str, Any] = {
    "family": "joint_assignment",
    "comparison": "joint root-and-field assignment from supplied score vectors",
    "algorithm": "exact DP over field masks and injective evidence keys",
    "evidence_identity": "(node_id, projection); same-node projections differ",
    "root_scope": "proposed root or descendant only",
    "nested_ownership": "siblings may combine; ownership is not inferred",
    "unmatched_utility": 0.0,
    "threshold": "caller raw-score threshold, never a probability",
    "root_size_penalty": "lambda * supplied size; lambda defaults to 0",
    "declared_bounds": dict(DEFAULT_BOUNDS),
    "incomplete_policy": "root, per-field top-k, and DP truncation are explicit",
    "ambiguity": "ties choose deterministically and set ambiguous",
    "scope_limit": "flat records; not nested Contract composition",
}

_EVIDENCE_KEY = tuple[str, str]


@dataclass(frozen=True)
class _Candidate:
    candidate_id: str
    node_id: str
    projection: str
    ancestors: frozenset[str]

    @property
    def evidence_key(self) -> _EVIDENCE_KEY:
        return (self.node_id, self.projection)


@dataclass(frozen=True)
class _RootProposal:
    node_id: str
    score: float
    size: float | None


@dataclass(frozen=True)
class _Pick:
    candidate_id: str
    node_id: str
    projection: str
    score: float

    @property
    def evidence_key(self) -> _EVIDENCE_KEY:
        return (self.node_id, self.projection)


@dataclass(frozen=True)
class _State:
    utility: float
    picks: tuple[_Pick | None, ...]
    ambiguous: bool = False


@dataclass(frozen=True)
class _Solution:
    root: _RootProposal | None
    picks: tuple[_Pick | None, ...]
    field_utility: float
    total_utility: float
    root_size_penalty: float
    ambiguous: bool
    ambiguity_reasons: tuple[str, ...]


def assign_jointly(
    field_scores: Mapping[str, Sequence[Real]],
    candidates: Sequence[Mapping[str, Any]],
    root_proposals: Mapping[Any, Any] | Sequence[Mapping[str, Any]],
    required_fields: Sequence[str],
    *,
    bounds: Mapping[str, int] | None = None,
    candidate_threshold: Real | None = None,
    root_specificity_lambda: Real = 0.0,
) -> dict[str, Any]:
    """Choose a root and an injective field assignment using only scores/topology.

    ``field_scores[field]`` must align positionally with ``candidates``. Candidates
    provide ``id`` (optional), ``node_id``, ``projection`` and ``ancestors``. Root
    proposals are either ``{node_id: score}``, ``{node_id: {"score": score,
    "size": size}}``, or a sequence of ``{"node_id", "score", "size"}`` maps.

    Each root is evaluated independently. For each field, candidates outside that
    root are removed, then at most ``per_field_top_k`` are retained by score and
    deterministic evidence-key order. The DP gives each evidence key to at most one
    field. Unmatched fields contribute zero utility; a supplied candidate threshold
    filters edges below that raw threshold and is never interpreted as a
    probability. Required fields may remain unmatched and are reported explicitly.

    The objective is ``root_score + matched_field_scores - lambda * root_size``.
    Root size is a caller-supplied numeric measure and is required when lambda is
    nonzero. A no-root/all-unmatched option has utility zero. Equal-utility
    alternatives are reported as ambiguous; a deterministic representative is
    returned for inspection.

    The result is optimal over supplied inputs only when ``status`` is ``complete``
    or ``required_unmatched``. ``bounded`` means the result is optimal over the
    declared root/top-k bounds but omitted input candidates may change it.
    ``budget_exhausted`` means one or more roots were not fully solved.
    """
    normalized_bounds = _normalize_bounds(bounds)
    fields = _normalize_fields(field_scores, required_fields, normalized_bounds)
    normalized_candidates = _normalize_candidates(candidates)
    score_vectors = _normalize_score_vectors(
        field_scores, fields, len(normalized_candidates)
    )
    proposals = _normalize_root_proposals(root_proposals, root_specificity_lambda)
    threshold = (
        None
        if candidate_threshold is None
        else _finite_number(candidate_threshold, "candidate_threshold")
    )
    size_lambda = _finite_number(root_specificity_lambda, "root_specificity_lambda")
    if size_lambda < 0:
        raise ValueError("root_specificity_lambda must be nonnegative")

    ranked_roots = sorted(proposals, key=lambda root: (-root.score, root.node_id))
    retained_roots = ranked_roots[: normalized_bounds["max_roots"]]
    incomplete_paths: list[dict[str, Any]] = []
    input_truncated = False
    if len(ranked_roots) > len(retained_roots):
        input_truncated = True
        omitted = ranked_roots[len(retained_roots) :]
        incomplete_paths.append(
            {
                "reason": "max_roots",
                "omitted_count": len(omitted),
                "omitted_root_ids": [root.node_id for root in omitted[:10]],
            }
        )

    best = _no_root_solution(len(fields))
    transitions = 0
    unsolved_roots: list[str] = []
    budget_exhausted = False

    for root_index, root in enumerate(retained_roots):
        field_edges, root_truncations = _edges_for_root(
            fields,
            score_vectors,
            normalized_candidates,
            root,
            normalized_bounds["per_field_top_k"],
            threshold,
        )
        if root_truncations:
            input_truncated = True
            incomplete_paths.extend(root_truncations)
        state, root_transitions, exceeded = _assign_for_root(
            fields,
            field_edges,
            normalized_bounds["max_dp_transitions"] - transitions,
        )
        transitions += root_transitions
        if exceeded or state is None:
            budget_exhausted = True
            unsolved_roots.extend(root.node_id for root in retained_roots[root_index:])
            incomplete_paths.append(
                {
                    "reason": "max_dp_transitions",
                    "root_id": root.node_id,
                    "transitions_used": transitions,
                    "transition_budget": normalized_bounds["max_dp_transitions"],
                }
            )
            break

        penalty = size_lambda * (root.size or 0.0)
        total = math.fsum((root.score, state.utility, -penalty))
        reasons = ("equal_utility_field_assignments",) if state.ambiguous else ()
        solution = _Solution(
            root=root,
            picks=state.picks,
            field_utility=state.utility,
            total_utility=total,
            root_size_penalty=penalty,
            ambiguous=state.ambiguous,
            ambiguity_reasons=reasons,
        )
        best, root_tie = _prefer_solution(best, solution)
        if root_tie:
            best = _Solution(
                root=best.root,
                picks=best.picks,
                field_utility=best.field_utility,
                total_utility=best.total_utility,
                root_size_penalty=best.root_size_penalty,
                ambiguous=True,
                ambiguity_reasons=tuple(
                    sorted(set((*best.ambiguity_reasons, "equal_utility_root_choices")))
                ),
            )

    if unsolved_roots:
        already_listed = {
            path.get("root_id")
            for path in incomplete_paths
            if path.get("reason") == "max_dp_transitions"
        }
        remaining = [
            node_id for node_id in unsolved_roots if node_id not in already_listed
        ]
        if remaining:
            incomplete_paths.append(
                {
                    "reason": "root_not_solved_after_budget",
                    "root_ids": remaining,
                }
            )

    required_unmatched = [
        field
        for field, pick in zip(fields, best.picks, strict=True)
        if field in set(required_fields) and pick is None
    ]
    optional_unmatched = [
        field
        for field, pick in zip(fields, best.picks, strict=True)
        if field not in set(required_fields) and pick is None
    ]
    if budget_exhausted:
        status = "budget_exhausted"
        globally_optimal = False
    elif best.root is None:
        status = "no_root"
        globally_optimal = not input_truncated
    elif input_truncated:
        status = "bounded"
        globally_optimal = False
    elif required_unmatched:
        status = "required_unmatched"
        globally_optimal = True
    else:
        status = "complete"
        globally_optimal = True

    field_mapping: dict[str, dict[str, Any]] = {}
    for field, pick in zip(fields, best.picks, strict=True):
        if pick is None:
            field_mapping[field] = {
                "status": "unmatched_required"
                if field in set(required_fields)
                else "unmatched_optional",
                "utility": 0.0,
                "candidate": None,
                "evidence_key": None,
            }
        else:
            field_mapping[field] = {
                "status": "matched",
                "utility": pick.score,
                "candidate": {
                    "id": pick.candidate_id,
                    "node_id": pick.node_id,
                    "projection": pick.projection,
                },
                "evidence_key": {
                    "node_id": pick.node_id,
                    "projection": pick.projection,
                },
            }

    return {
        "method": METHOD,
        "status": status,
        "optimal_over_supplied_input": globally_optimal,
        "optimal_within_declared_bounds": not budget_exhausted,
        "selected_root": (
            None
            if best.root is None
            else {
                "node_id": best.root.node_id,
                "score": best.root.score,
                "size": best.root.size,
                "size_penalty": best.root_size_penalty,
            }
        ),
        "field_mapping": field_mapping,
        "required_unmatched": required_unmatched,
        "optional_unmatched": optional_unmatched,
        "root_score": 0.0 if best.root is None else best.root.score,
        "field_utility": best.field_utility,
        "root_size_penalty": best.root_size_penalty,
        "root_specificity_lambda": size_lambda,
        "total_utility": best.total_utility,
        "candidate_threshold": threshold,
        "candidate_threshold_is_probability": False,
        "dp_transitions": transitions,
        "bounds": dict(normalized_bounds),
        "incomplete_paths": incomplete_paths,
        "unsolved_roots": unsolved_roots,
        "ambiguous": best.ambiguous,
        "ambiguity_reasons": list(best.ambiguity_reasons),
        "ambiguity_tolerance": {
            "absolute": TIE_ABS_TOLERANCE,
            "relative": TIE_REL_TOLERANCE,
        },
        "ownership_scope": "selected candidates are under the proposed root only",
        "nested_composition_claimed": False,
    }


def _normalize_bounds(bounds: Mapping[str, int] | None) -> dict[str, int]:
    values = dict(DEFAULT_BOUNDS)
    if bounds is not None:
        if not isinstance(bounds, Mapping):
            raise ValueError("bounds must be a mapping")
        unknown = set(bounds) - set(DEFAULT_BOUNDS)
        if unknown:
            raise ValueError(f"unknown bounds: {sorted(map(str, unknown))}")
        values.update(bounds)
    hard_limits = {
        "max_fields": MAX_FIELDS,
        "per_field_top_k": MAX_PER_FIELD_TOP_K,
        "max_roots": MAX_ROOTS,
        "max_dp_transitions": MAX_DP_TRANSITIONS,
    }
    for name, maximum in hard_limits.items():
        value = values[name]
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"{name} must be a positive integer")
        if value > maximum:
            raise ValueError(f"{name} exceeds hard maximum {maximum}")
    return values


def _normalize_fields(
    field_scores: Mapping[str, Sequence[Real]],
    required_fields: Sequence[str],
    bounds: Mapping[str, int],
) -> list[str]:
    if not isinstance(field_scores, Mapping) or not field_scores:
        raise ValueError("field_scores must be a non-empty mapping")
    fields = list(field_scores)
    if any(not isinstance(field, str) or not field for field in fields):
        raise ValueError("field names must be non-empty strings")
    if len(set(fields)) != len(fields):
        raise ValueError("field names must be unique")
    if len(fields) > min(MAX_FIELDS, bounds["max_fields"]):
        raise ValueError("field count exceeds declared max_fields")
    if not isinstance(required_fields, Sequence) or isinstance(
        required_fields, (str, bytes)
    ):
        raise ValueError("required_fields must be a sequence of field names")
    required = list(required_fields)
    if any(not isinstance(field, str) or not field for field in required):
        raise ValueError("required field names must be non-empty strings")
    if len(set(required)) != len(required):
        raise ValueError("required_fields must be unique")
    unknown = set(required) - set(fields)
    if unknown:
        raise ValueError(
            f"required_fields not present in field_scores: {sorted(unknown)}"
        )
    return fields


def _normalize_candidates(
    candidates: Sequence[Mapping[str, Any]],
) -> list[_Candidate]:
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
        raise ValueError("candidates must be a sequence")
    normalized: list[_Candidate] = []
    id_to_key: dict[str, _EVIDENCE_KEY] = {}
    key_to_ancestors: dict[_EVIDENCE_KEY, frozenset[str]] = {}
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, Mapping):
            raise ValueError(f"candidate {index} must be a mapping")
        node_id = _identifier(candidate.get("node_id"), f"candidate {index} node_id")
        projection = candidate.get("projection")
        if not isinstance(projection, str) or not projection:
            raise ValueError(f"candidate {index} projection must be a non-empty string")
        raw_ancestors = candidate.get("ancestors")
        if not isinstance(raw_ancestors, Sequence) or isinstance(
            raw_ancestors, (str, bytes)
        ):
            raise ValueError(f"candidate {index} ancestors must be a sequence")
        ancestors = [
            _identifier(item, f"candidate {index} ancestor") for item in raw_ancestors
        ]
        if node_id in ancestors or len(set(ancestors)) != len(ancestors):
            raise ValueError(
                f"candidate {index} ancestors must be unique and exclude its node"
            )
        candidate_id = (
            _identifier(candidate["id"], f"candidate {index} id")
            if candidate.get("id") is not None
            else f"{node_id}\u001f{projection}"
        )
        key = (node_id, projection)
        normalized_ancestors = frozenset(ancestors)
        prior_ancestors = key_to_ancestors.get(key)
        if prior_ancestors is not None and prior_ancestors != normalized_ancestors:
            raise ValueError(f"evidence key {key!r} has inconsistent ancestor paths")
        key_to_ancestors[key] = normalized_ancestors
        prior = id_to_key.get(candidate_id)
        if prior is not None and prior != key:
            raise ValueError(
                f"candidate id {candidate_id!r} identifies multiple evidence keys"
            )
        id_to_key[candidate_id] = key
        normalized.append(
            _Candidate(
                candidate_id=candidate_id,
                node_id=node_id,
                projection=projection,
                ancestors=normalized_ancestors,
            )
        )
    return normalized


def _normalize_score_vectors(
    field_scores: Mapping[str, Sequence[Real]],
    fields: Sequence[str],
    candidate_count: int,
) -> dict[str, tuple[float, ...]]:
    result: dict[str, tuple[float, ...]] = {}
    for field in fields:
        vector = field_scores[field]
        if not isinstance(vector, Sequence) or isinstance(vector, (str, bytes)):
            raise ValueError(f"score vector for {field!r} must be a sequence")
        if len(vector) != candidate_count:
            raise ValueError(
                f"score vector for {field!r} has length {len(vector)}; "
                f"expected {candidate_count}"
            )
        result[field] = tuple(
            _finite_number(score, f"score vector {field!r}[{index}]")
            for index, score in enumerate(vector)
        )
    return result


def _normalize_root_proposals(
    root_proposals: Mapping[Any, Any] | Sequence[Mapping[str, Any]],
    root_specificity_lambda: Real,
) -> list[_RootProposal]:
    entries: list[tuple[Any, Any]]
    if isinstance(root_proposals, Mapping):
        entries = list(root_proposals.items())
        raw_proposals = []
        for root_id, value in entries:
            if isinstance(value, Mapping):
                if "node_id" in value and _identifier(
                    value["node_id"], "root proposal node_id"
                ) != _identifier(root_id, "root proposal mapping key"):
                    raise ValueError(
                        "root proposal mapping key conflicts with its node_id"
                    )
                proposal = {**value, "node_id": root_id}
            else:
                proposal = {"node_id": root_id, "score": value}
            raw_proposals.append(proposal)
    elif isinstance(root_proposals, Sequence) and not isinstance(
        root_proposals, (str, bytes)
    ):
        raw_proposals = list(root_proposals)
    else:
        raise ValueError("root_proposals must be a mapping or sequence of mappings")

    size_lambda = _finite_number(root_specificity_lambda, "root_specificity_lambda")
    if size_lambda < 0:
        raise ValueError("root_specificity_lambda must be nonnegative")
    normalized: list[_RootProposal] = []
    seen: set[str] = set()
    for index, proposal in enumerate(raw_proposals):
        if not isinstance(proposal, Mapping):
            raise ValueError(f"root proposal {index} must be a mapping")
        root_id = _identifier(proposal.get("node_id"), f"root proposal {index} node_id")
        if root_id in seen:
            raise ValueError(f"duplicate root proposal for node {root_id!r}")
        seen.add(root_id)
        score = _finite_number(
            proposal.get("score"), f"root proposal {root_id!r} score"
        )
        raw_size = proposal.get("size")
        size = (
            None
            if raw_size is None
            else _finite_number(raw_size, f"root proposal {root_id!r} size")
        )
        if size is not None and size < 0:
            raise ValueError(f"root proposal {root_id!r} size must be nonnegative")
        if size_lambda > 0 and size is None:
            raise ValueError(
                f"root proposal {root_id!r} requires size when "
                "root_specificity_lambda is nonzero"
            )
        normalized.append(_RootProposal(node_id=root_id, score=score, size=size))
    return normalized


def _edges_for_root(
    fields: Sequence[str],
    score_vectors: Mapping[str, Sequence[float]],
    candidates: Sequence[_Candidate],
    root: _RootProposal,
    top_k: int,
    threshold: float | None,
) -> tuple[dict[_EVIDENCE_KEY, dict[int, _Pick]], list[dict[str, Any]]]:
    edges: dict[_EVIDENCE_KEY, dict[int, _Pick]] = {}
    incomplete: list[dict[str, Any]] = []
    for field_index, field in enumerate(fields):
        best_by_key: dict[_EVIDENCE_KEY, _Pick] = {}
        for candidate, score in zip(candidates, score_vectors[field], strict=True):
            if (
                candidate.node_id != root.node_id
                and root.node_id not in candidate.ancestors
            ):
                continue
            if threshold is not None and score < threshold:
                continue
            pick = _Pick(
                candidate_id=candidate.candidate_id,
                node_id=candidate.node_id,
                projection=candidate.projection,
                score=score,
            )
            current = best_by_key.get(candidate.evidence_key)
            if current is None or _prefer_pick(pick, current):
                best_by_key[candidate.evidence_key] = pick
        ranked = sorted(
            best_by_key.items(),
            key=lambda item: (
                -item[1].score,
                item[0][0],
                item[0][1],
                item[1].candidate_id,
            ),
        )
        if len(ranked) > top_k:
            incomplete.append(
                {
                    "reason": "per_field_top_k",
                    "root_id": root.node_id,
                    "field": field,
                    "eligible_evidence_count": len(ranked),
                    "retained_evidence_count": top_k,
                    "omitted_evidence_count": len(ranked) - top_k,
                }
            )
            ranked = ranked[:top_k]
        for evidence_key, pick in ranked:
            edges.setdefault(evidence_key, {})[field_index] = pick
    return edges, incomplete


def _assign_for_root(
    fields: Sequence[str],
    edges: Mapping[_EVIDENCE_KEY, Mapping[int, _Pick]],
    remaining_budget: int,
) -> tuple[_State | None, int, bool]:
    empty = _State(utility=0.0, picks=(None,) * len(fields))
    states: dict[int, _State] = {0: empty}
    transitions = 0
    for evidence_key in sorted(edges):
        available = edges[evidence_key]
        next_states = dict(states)
        for field_mask, state in states.items():
            for field_index, pick in sorted(available.items()):
                field_bit = 1 << field_index
                if field_mask & field_bit:
                    continue
                if transitions >= remaining_budget:
                    return None, transitions, True
                transitions += 1
                picks = list(state.picks)
                picks[field_index] = pick
                proposed = _State(
                    utility=math.fsum((state.utility, pick.score)),
                    picks=tuple(picks),
                    ambiguous=state.ambiguous,
                )
                new_mask = field_mask | field_bit
                next_states[new_mask] = _merge_state(
                    next_states.get(new_mask), proposed
                )
        states = next_states

    best: _State | None = None
    for state in states.values():
        best = _merge_state(best, state)
    return best or empty, transitions, False


def _merge_state(existing: _State | None, proposed: _State) -> _State:
    if existing is None:
        return proposed
    if _strictly_better(proposed.utility, existing.utility):
        return proposed
    if _strictly_better(existing.utility, proposed.utility):
        return existing
    different = _picks_key(proposed.picks) != _picks_key(existing.picks)
    chosen = min((existing, proposed), key=lambda state: _picks_key(state.picks))
    return _State(
        utility=chosen.utility,
        picks=chosen.picks,
        ambiguous=existing.ambiguous or proposed.ambiguous or different,
    )


def _prefer_solution(
    existing: _Solution, proposed: _Solution
) -> tuple[_Solution, bool]:
    if _strictly_better(proposed.total_utility, existing.total_utility):
        return proposed, False
    if _strictly_better(existing.total_utility, proposed.total_utility):
        return existing, False
    different = _solution_key(existing) != _solution_key(proposed)
    chosen = min((existing, proposed), key=_solution_key)
    result = _Solution(
        root=chosen.root,
        picks=chosen.picks,
        field_utility=chosen.field_utility,
        total_utility=chosen.total_utility,
        root_size_penalty=chosen.root_size_penalty,
        ambiguous=existing.ambiguous or proposed.ambiguous or different,
        ambiguity_reasons=tuple(
            sorted(set((*existing.ambiguity_reasons, *proposed.ambiguity_reasons)))
        ),
    )
    return result, different


def _no_root_solution(field_count: int) -> _Solution:
    return _Solution(
        root=None,
        picks=(None,) * field_count,
        field_utility=0.0,
        total_utility=0.0,
        root_size_penalty=0.0,
        ambiguous=False,
        ambiguity_reasons=(),
    )


def _solution_key(solution: _Solution) -> tuple[Any, ...]:
    root_id = "" if solution.root is None else solution.root.node_id
    return (root_id, _picks_key(solution.picks))


def _picks_key(picks: Sequence[_Pick | None]) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        ("", "", "")
        if pick is None
        else (pick.node_id, pick.projection, pick.candidate_id)
        for pick in picks
    )


def _prefer_pick(proposed: _Pick, existing: _Pick) -> bool:
    if _strictly_better(proposed.score, existing.score):
        return True
    if _strictly_better(existing.score, proposed.score):
        return False
    return (proposed.candidate_id, proposed.node_id, proposed.projection) < (
        existing.candidate_id,
        existing.node_id,
        existing.projection,
    )


def _strictly_better(left: float, right: float) -> bool:
    if math.isclose(
        left,
        right,
        rel_tol=TIE_REL_TOLERANCE,
        abs_tol=TIE_ABS_TOLERANCE,
    ):
        return False
    return left > right


def _identifier(value: Any, label: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"{label} must be a string or integer")
    result = str(value)
    if not result:
        raise ValueError(f"{label} must be non-empty")
    return result


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must be a finite real number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite real number")
    return result
