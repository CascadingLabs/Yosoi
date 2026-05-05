"""Top-level preprocess orchestration.

Runs after :class:`yosoi.core.cleaning.cleaner.HTMLCleaner` when the
``use_experimental_preprocess`` flag is on. Returns a
:class:`PreprocessResult` carrying the transformed HTML plus the metrics
the spike's success conditions are evaluated on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lxml import etree, html

from yosoi.core.cleaning.preprocess.tier1 import (
    compact_whitespace,
    drop_comments,
    drop_link_and_meta_noise,
    drop_scripts,
    strip_framework_attrs,
    strip_layout_attrs,
)
from yosoi.core.cleaning.preprocess.tier2 import (
    cap_hydration_json,
    cap_oversized_attrs,
    hoist_jsonld,
    stub_svg_geometry,
    trim_url_tracking_params,
)
from yosoi.core.cleaning.preprocess.tokens import estimate_tokens


@dataclass(frozen=True)
class PreprocessResult:
    """Output of one preprocess pass.

    Attributes:
        html: Transformed HTML, ready for the LLM.
        tokens_in: Estimated token count of the input.
        tokens_out: Estimated token count of the output.
        tier_applied: Which tiers ran (``tier1``, ``tier1+tier2``).
        transform_count: Number of node/attr touches across all transforms.
            Useful as a "did anything happen?" sanity check in Langfuse.
        per_transform: Per-transform touch counts for granular debugging.
    """

    html: str
    tokens_in: int
    tokens_out: int
    tier_applied: str
    transform_count: int
    per_transform: dict[str, int] = field(default_factory=dict)

    @property
    def reduction_ratio(self) -> float:
        """``tokens_out / tokens_in`` (1.0 if input was empty)."""
        if self.tokens_in == 0:
            return 1.0
        return self.tokens_out / self.tokens_in


class HTMLPreprocessor:
    """Apply tier-1 + tier-2 transforms to cleaned HTML.

    Stateless besides config knobs. Safe to share across threads as long as
    callers respect the returned :class:`PreprocessResult` as immutable.
    """

    def __init__(self, *, run_tier1: bool = True, run_tier2: bool = True) -> None:
        """Configure which tiers run.

        Both tiers default to on; flipping one off is useful for A/B
        measurement (e.g. how much does tier-2 add over tier-1 alone?).
        """
        self.run_tier1 = run_tier1
        self.run_tier2 = run_tier2

    def preprocess(self, source_html: str) -> PreprocessResult:
        """Run the configured tiers and return metrics + transformed HTML.

        Args:
            source_html: Cleaned HTML (already past ``HTMLCleaner.clean_html``).

        Returns:
            :class:`PreprocessResult` with input/output token estimates and
            per-transform counts.
        """
        tokens_in = estimate_tokens(source_html)

        if not source_html.strip():
            return PreprocessResult(
                html=source_html,
                tokens_in=tokens_in,
                tokens_out=tokens_in,
                tier_applied='none',
                transform_count=0,
            )

        root = self._parse(source_html)
        per_transform: dict[str, int] = {}
        tiers: list[str] = []

        if self.run_tier1:
            tiers.append('tier1')
            per_transform['drop_scripts'] = drop_scripts(root)
            per_transform['drop_comments'] = drop_comments(root)
            per_transform['drop_link_and_meta_noise'] = drop_link_and_meta_noise(root)
            per_transform['strip_framework_attrs'] = strip_framework_attrs(root)
            per_transform['strip_layout_attrs'] = strip_layout_attrs(root)
            per_transform['compact_whitespace'] = compact_whitespace(root)

        if self.run_tier2:
            tiers.append('tier2')
            per_transform['hoist_jsonld'] = hoist_jsonld(root)
            per_transform['stub_svg_geometry'] = stub_svg_geometry(root)
            per_transform['cap_hydration_json'] = cap_hydration_json(root)
            per_transform['cap_oversized_attrs'] = cap_oversized_attrs(root)
            per_transform['trim_url_tracking_params'] = trim_url_tracking_params(root)

        out_html = self._serialize(root)
        return PreprocessResult(
            html=out_html,
            tokens_in=tokens_in,
            tokens_out=estimate_tokens(out_html),
            tier_applied='+'.join(tiers) if tiers else 'none',
            transform_count=sum(per_transform.values()),
            per_transform=per_transform,
        )

    @staticmethod
    def _parse(source_html: str) -> etree._Element:
        """Parse with lxml's HTML parser (lenient on real-world markup).

        ``html.fromstring`` returns the deepest single element that contains
        all input — that's the right level for downstream transforms.
        """
        # ``recover=True`` is implicit for the HTML parser. We supply a fresh
        # parser to avoid sharing parser state across threads.
        parser = html.HTMLParser(recover=True)
        # Wrap snippets in a synthetic root so transforms always see one element.
        wrapped = source_html if source_html.lstrip().startswith('<') else f'<div>{source_html}</div>'
        parsed: Any = html.fromstring(wrapped, parser=parser)
        return parsed

    @staticmethod
    def _serialize(root: etree._Element) -> str:
        """Serialize back to HTML, preserving doctype-free fragments."""
        rendered: bytes = etree.tostring(root, method='html', encoding='utf-8')
        return rendered.decode('utf-8')
