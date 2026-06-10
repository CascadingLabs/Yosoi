"""``ys.policy`` — pipeline-affecting configuration as resolved, immutable values.

One frozen :class:`~yosoi.policy.core.Policy` value object (``core``) over a shared trust/validation
base (``_base``), with each pipeline *stack* its own module (``crawl`` today; new stacks — e.g.
``scrape`` — drop in beside it). Resolved once at the edge and threaded through the pure core (the
CAS-119 purity contract). Re-exported lazily (PEP 562) so ``import yosoi`` stays cheap.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from yosoi._lazy import lazy_exports

if TYPE_CHECKING:  # static typing only — no runtime cost
    from yosoi.policy._base import (
        QUARANTINED_SOURCES as QUARANTINED_SOURCES,
    )
    from yosoi.policy._base import (
        TRUSTED_SOURCES as TRUSTED_SOURCES,
    )
    from yosoi.policy._base import (
        Outcome as Outcome,
    )
    from yosoi.policy._base import (
        Trust as Trust,
    )
    from yosoi.policy._base import (
        policy_arn as policy_arn,
    )
    from yosoi.policy._base import (
        promote_trust as promote_trust,
    )
    from yosoi.policy.core import (
        Policy as Policy,
    )
    from yosoi.policy.core import (
        PolicyCheck as PolicyCheck,
    )
    from yosoi.policy.core import (
        check_policy as check_policy,
    )
    from yosoi.policy.core import (
        resolve_crawl_policy as resolve_crawl_policy,
    )
    from yosoi.policy.crawl import (
        CrawlBudget as CrawlBudget,
    )
    from yosoi.policy.crawl import (
        CrawlPolicy as CrawlPolicy,
    )
    from yosoi.policy.crawl import (
        CrawlRuntimeConfig as CrawlRuntimeConfig,
    )
    from yosoi.policy.crawl import (
        CrawlSafety as CrawlSafety,
    )
    from yosoi.policy.crawl import (
        CrawlTarget as CrawlTarget,
    )
    from yosoi.policy.crawl import (
        EscalationPolicy as EscalationPolicy,
    )
    from yosoi.policy.crawl import (
        SchedulerPolicy as SchedulerPolicy,
    )

_LAZY = {
    'QUARANTINED_SOURCES': 'yosoi.policy._base',
    'TRUSTED_SOURCES': 'yosoi.policy._base',
    'Outcome': 'yosoi.policy._base',
    'Trust': 'yosoi.policy._base',
    'policy_arn': 'yosoi.policy._base',
    'promote_trust': 'yosoi.policy._base',
    'Policy': 'yosoi.policy.core',
    'PolicyCheck': 'yosoi.policy.core',
    'check_policy': 'yosoi.policy.core',
    'resolve_crawl_policy': 'yosoi.policy.core',
    'CrawlBudget': 'yosoi.policy.crawl',
    'CrawlPolicy': 'yosoi.policy.crawl',
    'CrawlRuntimeConfig': 'yosoi.policy.crawl',
    'CrawlSafety': 'yosoi.policy.crawl',
    'CrawlTarget': 'yosoi.policy.crawl',
    'EscalationPolicy': 'yosoi.policy.crawl',
    'SchedulerPolicy': 'yosoi.policy.crawl',
}
__all__ = sorted(_LAZY)
__getattr__, __dir__ = lazy_exports(__name__, globals(), _LAZY)
