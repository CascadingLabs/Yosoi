---
name: yosoi-research-frontier
description: Use when doing exploratory web/data research with Yosoi primitives before building a deterministic scraper or always-on pipeline. Triggers include research frontier, data frontier, local Perplexity, competitor analysis, web stats, source mapping, candidate contracts, evidence packets, MVP data plan, no API cost research, budgeted API research, and turning research into a Yosoi pipeline.
---

# Yosoi Research Frontier

Use this skill to answer: "What can we know from the web, at what cost, with what limits, and what should become a Yosoi pipeline?"

This is a dogfood workflow, not a core Yosoi command. Keep ambiguity in the frontier packet. Promote only proven data shapes into Yosoi contracts and only after scrape/discovery validation.

## Principles

- The frontier run explores. The production pipeline repeats.
- Prefer `$0` public-web/local-index work first unless the user gives a budget.
- Use Yosoi primitives for acquisition and extraction: `yosoi search`, `yosoi crawl`, `yosoi scrape`, policies, flat files, selector discovery, and cached replay.
- Do not invent exact data availability. Show limitations, paid-provider candidates, and confidence.
- Candidate contracts are hypotheses until validated on multiple representative pages.
- The final frontier answer must include a pipeline plan that removes LLM/API work from the 24/7 path wherever possible.

## Start A Packet

Create a packet before doing research:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python .agents/skills/yosoi-research-frontier/scripts/init_frontier_packet.py "research topic"
```

The script prints the packet path. Use that path for all artifacts.

For a budgeted pass:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python .agents/skills/yosoi-research-frontier/scripts/init_frontier_packet.py "research topic" --llm-budget-usd 40 --api-budget-usd 60
```

## Core Loop

1. Restate the target decision in `brief.md`.
2. Run discovery searches and save raw JSON:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run yosoi search "QUERY" --limit 10 --json > PACKET/sources/search-001.json
```

3. Build `source-map.json` manually from search/crawl results: source, URL, likely fields, cost, blocker, and next action.
4. Crawl promising domains or seed pages:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run yosoi crawl "https://example.com" --limit 20 --json --policy PACKET/policy.yaml > PACKET/sources/crawl-example.json
```

5. Draft minimal candidate contracts only after seeing repeated evidence shapes. Save them in `candidate-contracts/`.
6. Validate candidate contracts with `yosoi scrape --json`; record success/failure in `observations.jsonl`.
7. Write `limitations.md`, `mvp-plan.md`, and `pipeline-plan.md`.
8. In the final answer, separate what is available now from what needs paid data or dedicated pipeline work.

## Contract Promotion Rules

Promote a candidate contract only when:

- It extracts the same semantic fields across at least two representative source pages or one official source with stable page shape.
- Required fields are actually visible at scrape time.
- The result has source URL and enough provenance to support claims.
- The failure mode is understood: blocked, missing, JS-only, historical-only, paid-only, or not extractable.

Keep a candidate as provisional when it works on one page only, depends on vague snippets, or mixes multiple source types into one shape.

## Output Shape

The final response should include:

- Frontier verdict: viable, viable with paid source, partial, or not viable.
- `$0 path`: public/local data available without paid APIs.
- Budgeted path: what improves with the given budget.
- Candidate contracts: promoted, provisional, rejected.
- MVP plan: the smallest useful product/report.
- Production pipeline plan: deterministic 24/7 path with Yosoi primitives.
- Open risks: legal/robots, anti-bot, source drift, missing history, paid data quality.

## When To Touch Core Yosoi

Do not add core code for one-off frontier work. Consider core changes only when daily dogfooding repeats the same pain:

- a provider boundary is missing, such as Common Crawl beside DDGS;
- packet files need a stable model because multiple skills/scripts read them;
- cost/budget tracking must be enforced instead of manually noted;
- candidate contract promotion needs first-class storage;
- crawl/search/scrape handoff requires a reusable operation model.
