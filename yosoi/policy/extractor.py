"""Deterministic extractor strategy persistence and reuse policy.

Local extractor declarations always execute when present. This policy controls only
fingerprint reference I/O and fingerprint-proposed strategy reuse; it cannot enable
network access or LLM discovery inside an extractor.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator


class ExtractorPolicy(BaseModel):
    """Opt-in controls for extractor fingerprint references.

    ``reference_writes`` records validated, content-free strategy references.
    ``generalized_reads`` allows an otherwise unresolved extractor field to consider
    an exact stored strategy. Reads remain subject to :attr:`Policy.trust_tier`, so
    fingerprint-proposed strategies require this flag, ``trust_tier='yellow'``, and
    an exact callable reference in ``allowed_references``. Opaque strategies are
    excluded unless ``allow_opaque`` is explicitly enabled.
    """

    model_config = ConfigDict(frozen=True)

    reference_writes: bool = False
    generalized_reads: bool = False
    allowed_references: tuple[str, ...] = ()
    allow_opaque: bool = False

    @model_validator(mode='after')
    def _require_reference_allowlist(self) -> ExtractorPolicy:
        if self.generalized_reads and not self.allowed_references:
            raise ValueError('generalized_reads requires a non-empty allowed_references allowlist')
        if any(not reference.strip() or ':' not in reference for reference in self.allowed_references):
            raise ValueError('allowed_references entries must be exact non-empty module:qualname references')
        return self


__all__ = ['ExtractorPolicy']
