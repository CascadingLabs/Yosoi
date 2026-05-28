"""ReplayPlan execution runtime — A3Node primitives driven against a live page.

Promoted from ``examples/opencode_voidcrawl/replay_runtime.py`` so the package
can run LLM-discovered action plans (load-more / pagination / interaction) as
part of the fetch lifecycle. The runtime is deliberately duck-typed against
the voidcrawl ``Page`` interface — no hard import dependency on voidcrawl,
which keeps this module loadable in environments that only need ReplayPlan
modelling without the browser stack.
"""

from yosoi.core.replay.runtime import execute_plan, run_node

__all__ = ['execute_plan', 'run_node']
