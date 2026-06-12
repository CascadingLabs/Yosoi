"""Structured, extensible storage key for selector snapshots.

Today the key is (domain, contract_sig). The page_shape slot is wired in now
but always None until the HTML fingerprint is reliably threadable through the
storage layer. When that lands, populate page_shape and the filename/lookup
change automatically — no other code needs to touch this.

Filename format:
  v1 (domain only, legacy):        selectors_example_com.json
  v2 (domain + contract_sig):      selectors_example_com__v3_abc123.json
  v3 (+ page_shape, future):       selectors_example_com__v3_abc123__s1_4e9f8fa8.json
"""

from __future__ import annotations

from dataclasses import dataclass

from yosoi.utils.files import safe_domain


@dataclass(frozen=True)
class SelectorKey:
    """Content-addressed key for a selector snapshot file.

    Attributes:
        domain: Bare domain string (e.g. ``'example.com'``).
        contract_sig: Contract signature from
            :func:`~yosoi.utils.signatures.contract_signature`. Always set.
        page_shape: Page-shape fingerprint from
            :func:`~yosoi.generalization.fingerprint.page_shape_fp`.
            ``None`` until the fingerprint is threaded through the pipeline —
            the slot exists now so callers never need to change their key
            construction code when fingerprinting lands.
    """

    domain: str
    contract_sig: str
    page_shape: str | None = None

    def to_filename_stem(self) -> str:
        """Return the filename stem (no extension, no directory).

        Examples::

            SelectorKey("example.com", "v3:abc123").to_filename_stem()
            # → "selectors_example_com__v3_abc123"

            SelectorKey("example.com", "v3:abc123", "s1:4e9f8fa8").to_filename_stem()
            # → "selectors_example_com__v3_abc123__s1_4e9f8fa8"
        """
        safe_sig = _safe_seg(self.contract_sig)
        parts = [safe_domain(self.domain), safe_sig]
        if self.page_shape:
            parts.append(_safe_seg(self.page_shape))
        return 'selectors_' + '__'.join(parts)

    def to_filename(self) -> str:
        """Return the full JSON filename."""
        return self.to_filename_stem() + '.json'

    @classmethod
    def from_domain(cls, domain: str, contract_sig: str, page_shape: str | None = None) -> SelectorKey:
        """Convenience constructor — mirrors the old (domain, contract_sig) call sites."""
        return cls(domain=domain, contract_sig=contract_sig, page_shape=page_shape)

    @classmethod
    def parse_filename(cls, filename: str) -> SelectorKey | None:
        """Attempt to parse a selector filename back into a SelectorKey.

        Returns ``None`` when the filename does not match the expected pattern.
        Useful for ``list_domains`` and migration tooling.

        Handles legacy filenames (no contract_sig segment) by returning a key
        with an empty ``contract_sig`` so callers can detect and migrate them.
        """
        if not filename.startswith('selectors_') or not filename.endswith('.json'):
            return None
        stem = filename[len('selectors_') : -len('.json')]
        parts = stem.split('__')
        if len(parts) == 1:
            # Legacy: selectors_example_com.json — no contract_sig
            return cls(domain=_unsafe_seg(parts[0]), contract_sig='', page_shape=None)
        if len(parts) == 2:
            return cls(domain=_unsafe_seg(parts[0]), contract_sig=_unsafe_seg(parts[1]), page_shape=None)
        if len(parts) == 3:
            return cls(
                domain=_unsafe_seg(parts[0]),
                contract_sig=_unsafe_seg(parts[1]),
                page_shape=_unsafe_seg(parts[2]),
            )
        return None

    @property
    def is_legacy(self) -> bool:
        """True when this key has no contract_sig (parsed from a legacy file)."""
        return not self.contract_sig

    @property
    def has_page_shape(self) -> bool:
        """True when the page_shape slot is populated."""
        return self.page_shape is not None


def _safe_seg(s: str) -> str:
    """Make a string safe for use as a filename segment.

    Replaces ``:`` and ``/`` with ``_``. Keeps alphanumerics and hyphens.
    ``v3:abc123`` → ``v3_abc123``, ``s1:4e9f8fa8`` → ``s1_4e9f8fa8``.
    """
    return s.replace(':', '_').replace('/', '_')


def _unsafe_seg(s: str) -> str:
    """Reverse of _safe_seg — best-effort reconstruction for parse_filename.

    We can only reconstruct the domain dots (``_`` → ``_`` is ambiguous for
    contract sigs, so we leave those as-is — parse_filename is for tooling
    not round-trip identity).
    """
    return s
