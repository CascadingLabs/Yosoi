# Exa research packet for YoSoi stress-test positioning

## Objective (as concrete deliverables)
1. Determine Exa pricing model and major listed costs.
2. Determine where Exa likely gets data (ownership/build approach + partner/provider model).
3. Explain YoSoi-local advantage and where it can compete.
4. Propose concrete pricing/workflow strategies to compete smartly with lower capex+OPEX.
5. Verify evidence with direct commands/files before calling the objective done.

## Evidence checklist (prompt-to-artifact audit)

| Requirement | Evidence artifact | Command / file | Evidence found |
|---|---|---|---|
| Exa pricing page capture | `docs/research` packet data | `UV_CACHE_DIR=/tmp/uv-cache uv run yosoi crawl https://exa.ai/pricing --max-pages 1 --max-depth 0 --compact --json` |  `summary` confirms successful crawl of 1 page + raw page saved in `/tmp/exa_pricing.json` (non-empty `html_chars:55325`). |
| Endpoint pricing numbers | `docs/research/exa-research-positioning.md` (section below) + `/tmp/exa_pricing.json` | Parsed table rows from `/tmp/exa_pricing.json`:  Base price per 1k requests: Search $7, Deep Search $12, Deep-Reasoning Search $15, Contents $1/page, Monitors $15, Answer $5; Additional result above 10: $1 (Search/Deep/Deep-Reasoning), Contents '-', Monitors $1, Answer $1; AI page summaries: $1 per 1k pages each listed endpoint. | Confirmed via BeautifulSoup row extraction. |
| Agent/effort pricing visibility | `/tmp/exa_pricing.json` via text extraction | CLI output from parse script | Usage components visible: ACU `$0.10`, search `$0.005/search`, email `$0.02`, phone `$0.07`; effort tiers visible (`Minimal $0.012`, `Low $0.025`, `Medium $0.10`, `High $0.50`, `X-high $1.00` request).
| Exa Connect positioning | `curl`/`read` of `/tmp/exa_connect.html` and `/tmp/exa_connect_overview.html` | `curl -L -s 'https://exa.ai/connect'` and `curl -L -s 'https://exa.ai/docs/reference/agent-api/connect/overview'` | Meta description states: “connect your agents to the world’s public and private data; access thousands of data providers through one request.” Additional partner note says beyond self-serve are available upon request.
| Exa Connect provider catalog + on-demand additions | `/tmp/exa_connect_overview.html` + `/tmp/exa_additional_partners.html` | `curl -L -s 'https://exa.ai/docs/reference/agent-api/connect/overview'` and `curl -L -s 'https://exa.ai/docs/reference/agent-api/connect/additional-partners'` | Self-serve cards captured include Fiber.ai, Similarweb, Baselayer, Affiliate.com, Particle, Financial Datasets, Jinko (6–7 visible cards). Additional partners page contains explicit “available upon request” + contact sales flow.
| Exa MCP/Agent auth + data source constraints | `/tmp/exa_mcp.html` and `/tmp/exa_agent_api_guide.html` | `curl -L -s 'https://exa.ai/docs/reference/exa-mcp'` and `curl -L -s 'https://exa.ai/docs/reference/agent-api-guide'` | `dataSources` can attach Exa Connect providers, up to 5; Agent runs are usage-based and require authentication (OAuth or API key); Exa Agent is an async multi-step workflow endpoint.
| Exa procurement architecture | `curl` capture of Exa blog post | `curl -L -s 'https://exa.ai/blog/zdr-search-engine'` | Blog text says most providers rely on subprocessing Google and cannot give true ZDR; Exa says it built its own search engine and crawls/organizes web data; states query data is deleted after search.
| YoSoi local/OSS differentiator evidence | Repo docs | `README.md`, `LICENSE.md` | License badge references Apache-2.0 and full Apache license exists in `LICENSE.md`; README describes Open Source/voidcrawl tooling and usage flow, indicating local execution model and source visibility.

## Key findings

### What Exa is
Exa is an AI-native, API-driven retrieval/research stack (search + deep search + deep reasoning + contents + monitors + answer) plus **Exa Agent** orchestration and **Exa Connect** partner integrations.

### How Exa likely procures data
- **Proprietary crawl/index layer** is claimed via Exa’s own blog and ZDR materials.
- **Partner-provider layer (Exa Connect)** provides specialized datasets on top of web search.
- Additional partner activation appears sales-assisted (“available upon request”).

### Where YoSoi’s advantage likely is
- **Cost model advantage**: Exa is heavily metered by requests/uses/units/add-ons. YoSoi can target a fixed OPEX model (infra + optional support) for users with bounded domains.
- **Open-source control**: local deployment, inspectable behavior, no external SaaS gatekeeping for core extraction logic.
- **Specialization edge**: YoSoi can be good where extraction domains are known/repeatable and where selector stability improves over time.

## Strategy you can execute (conservative, smart, local-first)

1. **Position** YoSoi as “batteries-included for your target sites,” not full global web replacement.
2. **Introduce a bounded tier model** (good first pass):
   - Free local: limited pages/month + community sources.
   - Local Pro: higher frontier + cache size + optional async workers.
   - Managed/enterprise: SRE, private deployment, priority features.
3. **Use partner APIs only as adapters** (do not recreate paid sources): user passes keys; YoSoi orchestrates extraction/fallbacks against those sources.
4. **Shift competitive value to predictability & privacy**: no per-API-call price shock, deterministic logs, no central lock-in.
5. **Pitch speed tradeoff explicitly**: “slightly slower than full global API, but often cheaper and more controlled.”

## Uncertainty / verification gaps
- Exa’s exact partner roster and contract terms can change; this packet uses publicly visible docs at crawl time.
- Full Exa enterprise terms/API caps not fully enumerated from these captures.
- Patent status is **not confirmed** by public evidence here: exact assignee searches on Google Patents returned no results for `"EXA LABS INC"`, `"EXA LABS"`, and `"Exa Labs, Inc."`.
- If needed, collect one more pass directly from official pricing API/openapi schemas or a dedicated patent database export for contractual clarity.

## Legal/patent scan notes
- Exa Terms of Service contain generic IP language and feedback assignment, but no public patent list.
- Public Exa pages found in this pass also surface privacy/terms links and data-processing style clauses, which matter for a local/open-source competitor more than patents do.
- Best next legal follow-up: a formal assignee lookup in a patent database (USPTO ODP / Lens / Google Patents) plus corporate-name variants and founder/inventor names.
