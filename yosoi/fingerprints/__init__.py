"""Long-term fingerprint cache and audit-trail support.

This package is plural (``fingerprints``) to avoid clobbering the public
``yosoi.fingerprint(...)`` function exported from :mod:`yosoi.api`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from yosoi._lazy import lazy_exports

if TYPE_CHECKING:
    from yosoi.fingerprints.generalization import (
        compare_field_reference as compare_field_reference,
    )
    from yosoi.fingerprints.generalization import (
        root_scope as root_scope,
    )
    from yosoi.fingerprints.generalization import (
        route_template as route_template,
    )
    from yosoi.fingerprints.models import (
        FieldGeneralizationSimilarity as FieldGeneralizationSimilarity,
    )
    from yosoi.fingerprints.models import (
        FingerprintClassificationRecord as FingerprintClassificationRecord,
    )
    from yosoi.fingerprints.models import (
        FingerprintFieldReferenceRecord as FingerprintFieldReferenceRecord,
    )
    from yosoi.fingerprints.models import (
        FingerprintPageRecord as FingerprintPageRecord,
    )
    from yosoi.fingerprints.models import (
        FingerprintReferenceRecord as FingerprintReferenceRecord,
    )
    from yosoi.fingerprints.models import (
        RootScopeRecord as RootScopeRecord,
    )
    from yosoi.fingerprints.store import FingerprintStore as FingerprintStore

_LAZY = {
    'FieldGeneralizationSimilarity': 'yosoi.fingerprints.models',
    'FingerprintClassificationRecord': 'yosoi.fingerprints.models',
    'FingerprintFieldReferenceRecord': 'yosoi.fingerprints.models',
    'FingerprintPageRecord': 'yosoi.fingerprints.models',
    'FingerprintReferenceRecord': 'yosoi.fingerprints.models',
    'FingerprintStore': 'yosoi.fingerprints.store',
    'RootScopeRecord': 'yosoi.fingerprints.models',
    'compare_field_reference': 'yosoi.fingerprints.generalization',
    'root_scope': 'yosoi.fingerprints.generalization',
    'route_template': 'yosoi.fingerprints.generalization',
}

__all__ = sorted(_LAZY)
__getattr__, __dir__ = lazy_exports(__name__, globals(), _LAZY)
