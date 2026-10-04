# Map CLI

`yosoi map URL` calls the public Map SDK with this CLI version's active saved
Policy. With no active profile it uses `Policy::default()`. `--profile NAME` selects a
profile for one invocation; explicit Map flags apply after profile resolution
and never write the profile file. HTTPS is assumed for a target without a scheme.

```sh
yosoi map qscrape.dev/l1/news/
yosoi map anthropic.com --mode passive --max-hosts 2000
yosoi map qscrape.dev/l1/news/ --depth 2 --max-requests 20 > map.json
yosoi map qscrape.dev/l1/news/ | yosoi locate --json-path '$.pages[*].url' --json
yosoi map anthropic.com --mode passive --json
yosoi --profile review map qscrape.dev/l1/news/ --explain
```

No `--mode` preserves the profile's page/subdomain/scope choices. Explicit
`pages` chooses seed-host page exploration with passive discovery disabled.
`passive` chooses registrable-domain passive discovery with page exploration
disabled; it makes no target-site page requests. `combined` chooses both passive
discovery and page exploration under registrable-domain scope. Mode flags
preserve the profile's path scope, filters, robots setting, and budgets.

`--depth`, `--max-requests`, `--max-hosts`, `--max-urls`, `--max-concurrency`, `--timeout-ms`, and
`--robots ignore|respect` override those Policy values for this run. Timeout is
the absolute Map deadline; Request's independent attempt deadline still applies.
Other Map limits/filter choices live in the ordinary saved Policy. Robots
allow/disallow enforcement defaults off. `--explain` validates the same SDK
seed/scope/acquisition rules and prints the resolved Policy and identity without
network I/O. Map supports Direct HTTP response-document acquisition only.

## Shell streams

The Request command's descriptor rules are shared with Map:

| Destination | Default output |
| --- | --- |
| Terminal | Human host/tree summary, sources and consumed bounds |
| `> map.json` | Raw JSON manifest bytes |
| `| yosoi locate ...` | One `YSOIDOC1` typed JSON Document frame |

The JSON Document contains a generated Map manifest, not an acquired webpage.
Use JSONPath to locate data in it. The report contains `schema_version: 1`, CLI
version, seed, selected profile, effective Policy identity, Map Policy, termination,
consumed bounds, host verification/provenance, page depth/exploration, relationships,
tree, source/support outcomes, omissions, unfinished frontier, and request trace.
Termination uses `status: exhausted|limit|deadline|cancelled` and a limit reason
when applicable. Frontier entries use `page` and `reason`; page inventory uses
`url`. Original response bodies and executor state are omitted. Encoded output is
bounded to 16 MiB before it is emitted.

`--json` or `--raw` forces ordinary JSON even into `jq`, `cat`, or `tee`.
`--pipe-document` forces a typed frame, including into a regular file:

```sh
yosoi map qscrape.dev/l1/news/ --json | jq '.pages[].url'
yosoi map qscrape.dev/l1/news/ --pipe-document > map.ysdoc
yosoi locate --json-path '$.pages[*].url' --json < map.ysdoc
yosoi locate --file map.json --format json --json-path '$.pages[*].url' --json
```

Output flags are mutually exclusive. Descriptor inference is supported on Unix;
other platforms require an explicit non-terminal output mode. `--stats`/`-s` (also `--stat`) writes
wall time and consumed counts to stderr, leaving the selected stdout format intact.

## Outcomes

Exit 0 means the selected work exhausted successfully. Exit 3 means a bound or
deadline stopped work (including a still-pending seed), or a material failure
left useful partial results. Exit 1 means requested
discovery failed without useful results or setup failed; syntax errors return 2.
Ctrl-C forwards cancellation, waits for SDK cleanup, preserves partial results,
and returns 130. Optional metadata 404/410 absence is normal; malformed metadata
and other source failures remain visible. Inspect the JSON source outcomes and
frontier even after a successful command: public-index samples are reported separately from local truncation; no source promises every subdomain or
hidden page. A seed-only host list does not prove passive discovery succeeded.

With shell `set -o pipefail`, a downstream Locate match does not hide Map's
partial/failure exit. A regular-file redirect stores returned partial inventory
before that exit, so it remains available to inspect. Write and broken-pipe errors
are reported. There are no profile or Archive writes, active enumeration, Go CLI,
or browser mapping in this command.

Focused checks, live outcomes, source identity, and review limits are recorded in
[Map CLI verification](archive/cli-map-verification.md).

## Concurrency

`--max-concurrency` overrides `Policy.map.limits.max_concurrency`, which defaults
to two for both pages and public providers. Scheduling lives in the SDK. Map
reports page and provider concurrency peaks separately, plus unused page
prefetches. Zero unused prefetches means all admitted page responses were consumed
by inspection or redirect handling; it does not mean every inventoried URL was fetched.

At a limit, deadline, or cancellation, an already admitted batch can contain work
that will not be inspected. The extra work is bounded by the batch size, accounted,
and drained before returning. With concurrency two, a limit discovered while
inspecting the first result can leave one speculative sibling response unused.
The whole batch can be unused if cancellation happens before inspection starts.

```rust
use yosoi_sdk::prelude as ys;

let mut policy = ys::Policy::default(); // Map concurrency defaults to two.
policy.map.limits.max_concurrency = ys::policy::Budget::new(4)?;
let result = ys::map::new("https://qscrape.dev/").bind(&policy).send().await?;
```
