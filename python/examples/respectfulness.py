"""Author and validate traffic policy without making an outbound request."""

import yosoi as ys

group = ys.policy.RespectfulnessGroup(
    id="qscrape",
    patterns=[r"^https://(?:[a-z0-9-]+\.)*qscrape\.dev/"],
    concurrency=1,
    spacing_ms=2000,
    budgets=[ys.policy.RateBudget(requests=10, window_ms=60_000)],
    cooldown=ys.policy.RespectfulnessCooldown(statuses=[429, 503], fallback_ms=30_000),
)
policy = ys.Policy(respectfulness=ys.policy.Respectfulness(groups=[group]))
registry = ys.registry.Registry()
bound = ys.request.new("https://qscrape.dev/").bind(policy).with_registry(registry)
bound.check()
print(policy.to_json())
