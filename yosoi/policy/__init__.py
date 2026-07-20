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
        CrawlPresetName as CrawlPresetName,
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
    from yosoi.policy.extractor import (
        ExtractorPolicy as ExtractorPolicy,
    )
    from yosoi.policy.fingerprint import (
        FingerprintPolicy as FingerprintPolicy,
    )
    from yosoi.policy.page import (
        BrowserProfilePolicy as BrowserProfilePolicy,
    )
    from yosoi.policy.page import (
        PagePolicy as PagePolicy,
    )
    from yosoi.policy.page import (
        PageRuntimeConfig as PageRuntimeConfig,
    )
    from yosoi.policy.recipe import (
        RecipePolicy as RecipePolicy,
    )
    from yosoi.policy.run import (
        DiscoveryPolicy as DiscoveryPolicy,
    )
    from yosoi.policy.run import (
        DownloadPolicy as DownloadPolicy,
    )
    from yosoi.policy.run import (
        ModelPolicy as ModelPolicy,
    )
    from yosoi.policy.run import (
        OutputPolicy as OutputPolicy,
    )
    from yosoi.policy.run import (
        ResolvedRunSpec as ResolvedRunSpec,
    )
    from yosoi.policy.run import (
        SafeSearch as SafeSearch,
    )
    from yosoi.policy.run import (
        ScrapePolicy as ScrapePolicy,
    )
    from yosoi.policy.run import (
        SearchKind as SearchKind,
    )
    from yosoi.policy.run import (
        SearchPolicy as SearchPolicy,
    )
    from yosoi.policy.run import (
        SearchProvider as SearchProvider,
    )
    from yosoi.policy.run import (
        SecretRef as SecretRef,
    )
    from yosoi.policy.run import (
        TelemetryPolicy as TelemetryPolicy,
    )
    from yosoi.policy.run import (
        alibaba as alibaba,
    )
    from yosoi.policy.run import (
        anthropic as anthropic,
    )
    from yosoi.policy.run import (
        azure as azure,
    )
    from yosoi.policy.run import (
        bedrock as bedrock,
    )
    from yosoi.policy.run import (
        cerebras as cerebras,
    )
    from yosoi.policy.run import (
        claude_sdk as claude_sdk,
    )
    from yosoi.policy.run import (
        deepseek as deepseek,
    )
    from yosoi.policy.run import (
        fireworks as fireworks,
    )
    from yosoi.policy.run import (
        gemini as gemini,
    )
    from yosoi.policy.run import (
        github as github,
    )
    from yosoi.policy.run import (
        grok as grok,
    )
    from yosoi.policy.run import (
        groq as groq,
    )
    from yosoi.policy.run import (
        heroku as heroku,
    )
    from yosoi.policy.run import (
        huggingface as huggingface,
    )
    from yosoi.policy.run import (
        litellm as litellm,
    )
    from yosoi.policy.run import (
        mistral as mistral,
    )
    from yosoi.policy.run import (
        moonshotai as moonshotai,
    )
    from yosoi.policy.run import (
        nebius as nebius,
    )
    from yosoi.policy.run import (
        ollama as ollama,
    )
    from yosoi.policy.run import (
        openai as openai,
    )
    from yosoi.policy.run import (
        opencode as opencode,
    )
    from yosoi.policy.run import (
        openrouter as openrouter,
    )
    from yosoi.policy.run import (
        ovhcloud as ovhcloud,
    )
    from yosoi.policy.run import (
        provider as provider,
    )
    from yosoi.policy.run import (
        sambanova as sambanova,
    )
    from yosoi.policy.run import (
        together as together,
    )
    from yosoi.policy.run import (
        vercel as vercel,
    )
    from yosoi.policy.run import (
        vertexai as vertexai,
    )
    from yosoi.policy.run import (
        xai as xai,
    )

_LAZY = {
    'ExtractorPolicy': 'yosoi.policy.extractor',
    'FingerprintPolicy': 'yosoi.policy.fingerprint',
    'BrowserProfilePolicy': 'yosoi.policy.page',
    'PagePolicy': 'yosoi.policy.page',
    'PageRuntimeConfig': 'yosoi.policy.page',
    'DiscoveryPolicy': 'yosoi.policy.run',
    'DownloadPolicy': 'yosoi.policy.run',
    'ModelPolicy': 'yosoi.policy.run',
    'OutputPolicy': 'yosoi.policy.run',
    'ResolvedRunSpec': 'yosoi.policy.run',
    'ScrapePolicy': 'yosoi.policy.run',
    'SearchPolicy': 'yosoi.policy.run',
    'SafeSearch': 'yosoi.policy.run',
    'SearchKind': 'yosoi.policy.run',
    'SearchProvider': 'yosoi.policy.run',
    'RecipePolicy': 'yosoi.policy.recipe',
    'SecretRef': 'yosoi.policy.run',
    'TelemetryPolicy': 'yosoi.policy.run',
    'alibaba': 'yosoi.policy.run',
    'anthropic': 'yosoi.policy.run',
    'azure': 'yosoi.policy.run',
    'bedrock': 'yosoi.policy.run',
    'cerebras': 'yosoi.policy.run',
    'claude_sdk': 'yosoi.policy.run',
    'deepseek': 'yosoi.policy.run',
    'fireworks': 'yosoi.policy.run',
    'gemini': 'yosoi.policy.run',
    'github': 'yosoi.policy.run',
    'grok': 'yosoi.policy.run',
    'groq': 'yosoi.policy.run',
    'heroku': 'yosoi.policy.run',
    'huggingface': 'yosoi.policy.run',
    'litellm': 'yosoi.policy.run',
    'mistral': 'yosoi.policy.run',
    'moonshotai': 'yosoi.policy.run',
    'nebius': 'yosoi.policy.run',
    'ollama': 'yosoi.policy.run',
    'openai': 'yosoi.policy.run',
    'opencode': 'yosoi.policy.run',
    'openrouter': 'yosoi.policy.run',
    'ovhcloud': 'yosoi.policy.run',
    'provider': 'yosoi.policy.run',
    'sambanova': 'yosoi.policy.run',
    'together': 'yosoi.policy.run',
    'vercel': 'yosoi.policy.run',
    'vertexai': 'yosoi.policy.run',
    'xai': 'yosoi.policy.run',
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
    'CrawlPresetName': 'yosoi.policy.crawl',
    'CrawlRuntimeConfig': 'yosoi.policy.crawl',
    'CrawlSafety': 'yosoi.policy.crawl',
    'CrawlTarget': 'yosoi.policy.crawl',
    'EscalationPolicy': 'yosoi.policy.crawl',
    'SchedulerPolicy': 'yosoi.policy.crawl',
}
__all__ = sorted(_LAZY)
__getattr__, __dir__ = lazy_exports(__name__, globals(), _LAZY)
