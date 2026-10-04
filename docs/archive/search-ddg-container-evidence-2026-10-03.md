# DuckDuckGo current-Stable container capability, 2026-10-03

Historical evidence: the CAS-520 probe example, container profile, and Search
runner scripts were retired during scripts cleanup on 2026-10-04. The results
below describe the recorded experiment, not a supported current entry point.

Scope: one local, identity-bound Yosoi Search SDK query through Requests
`Browser(Headless)` with ResponseDocument and RenderedDom. This is a positive
capability probe, not a provider-default or repository browser-baseline
certification. No Google request, hidden retry, fallback, or Chrome for Testing
was used.

## Browser, controller, and source identity

| Layer | Observed identity |
| --- | --- |
| Regular Stable browser package | `google-chrome-stable_154.0.8037.97-1_amd64.deb`, SHA-256 `a4edbe95e9b01db6c9b97d7a1323121eda18362b5620df06abac1b59bee80053`; resolved from Google's signed Stable apt index |
| Browser executable | `/opt/google/chrome/chrome`, `Google Chrome 154.0.8037.97`, SHA-256 `6c792041b07547a662e1b17974d1dc34a3db630379b45d9d89ddd7e3e68cc587` |
| Controller | Vendored Chromiumoxide 0.9.1, upstream base `a7e2bb835b9643410f9e3dc044f0d947e96cbfa4` plus local patches 1–10 in `vendor/chromiumoxide/VENDORING.md`; Yosoi VoidCrawl controller integration |
| Generated CDP | Vendored `chromiumoxide_cdp` `0.10.0-yosoi.m153.1`, Chromium schema `r1681091`; distinct from the M154 browser executable |
| Runtime base | `voidcrawl-headful:local`, image ID `sha256:9f89ca6fcbe3ed40f9c3847edaecf9de98b997e57dd65395a990916cd68dd82a` |
| Builder | Rust 1.98 Linux/amd64 image `sha256:af753e6e729c839de28010e323abc550eceaa9572bdaa765429d4f585e2e43dc` |
| Corrected probe image | `sha256:828747506bca958a56ddce15b1bfa3aebf66f4daab52499f44a7181003b3813d` |
| Yosoi source | JJ change `yrrwonqsmlslyzkkrzowkwvysorwxkrt`, snapshot `9b1b3a71d18d1c282a9b084e80a6dca4987b48b2`; filtered build context SHA-256 `4490a5116eb4591ef77a8a59ff18d52a71e78765ecc111a1f4db2599d69c5a80` |
| Platform and launch | Linux/amd64; regular Stable Chrome; Headless; standard Normal instrumentation; main response completion |

The image inherited the reviewed runtime base layers. The container ran as
UID/GID 10001, with read-only root, a disposable 1 GiB `/tmp` tmpfs, 1 GiB
shared memory, 2 CPUs, 2 GiB memory/swap cap, 512 PID cap, all capabilities
dropped, no new privileges, and the repository Chrome seccomp profile SHA-256
`7df54f14f794a8870d8182a3653085ffc716d30a2fec9e722776c3f8c862f063`.
The entrypoint required `CHROME_NO_SANDBOX=0` and verified the browser version
and executable digest before launching Search. Network mode was a Docker bridge
for the one public DDG query. The Request deadline was 20 seconds, Search
deadline 25 seconds, and external container wait limit 90 seconds. One browser
Request ran with a five-hit and 512 KiB retained-content bound. The named
container and filtered source context were independently observed absent after
the run.

## Outcome and parser correction

The first one-shot build (`be750fe1` source; image
`sha256:c2469cab7670ce4e0a9c8c78f4cf04dee4064d72f7315a6b16f9bccb70198a57`)
returned HTTP 200 and five distinct valid hits in 3,964 ms, but web coverage
was Partial with two row issues. The saved CAS-502 RenderedDom (SHA-256
`14b522250b20df13ffb2aaf7831f0ca67da070350bb20def6845892fef652293`)
replayed offline with the same two rejected placements. Both legitimate
organic cards had a fifth direct section after the fourth-section snippet;
the parser had incorrectly required exactly four. A sanitized fifth-section
fixture and hash-checked replay now assert 10 organic hits, zero issues, and
complete web coverage without network access.

The corrected current-Stable run returned HTTP 200, one completed browser
attempt, retained source extent 25,659 bytes, and Search termination
`Completed` in 3,942 ms. It returned five distinct validated HTTP(S) hits,
organic ranks 1–5 at placements 2–6 after an ad placement, title and snippet
present on each hit, zero row issues, web coverage `Complete`, rich-feature
coverage `NotCollected`, and monetary charge `Unknown`. Result URLs, query
response bodies, cookies, and opaque tokens were not put in the committed
evidence. The local probe identity and content-free log are under
`/tmp/cas520-ddg-result.mA9x6k/` on this workstation.

## Three-provider CLI preview on current Stable

A later image baked the read-only, version-keyed
`docs/search-container-preview-policies.json` profile and the `yosoi` CLI. It
used JJ source snapshot `fe3cc6f4f566eb4c4126b4991c91432dc6763a13`, filtered
source SHA-256 `4e97ef727c3a9f321684cd108277e4749248a265b18eb51e9ee8c086f5425d1a`,
and image ID
`sha256:130844e9350fabce49047907b82f3612e578b7d414550a655fee31689867dbe1`.
The runtime base, Chrome 154.0.8037.97 package and executable hashes,
seccomp profile, user, sandbox, resource limits, and bridge network matched
the corrected SDK probe above. The runtime image upgraded only the pinned
Chrome package; an earlier probe image had also upgraded eight unrelated
Debian Sid packages. The builder's apt dependencies are still unpinned, so
this is an identity-bound local preview, not a reproducible release build.

The first CLI image set `XDG_CONFIG_HOME` to a read-only path for the baked
Policy file. Brave and Bing returned ten complete hits each, but DDG failed
before an observed HTTP status, including when selected alone. The SDK example
had succeeded in the same browser family. The entrypoint now copies the baked
Policy file into a writable tmpfs XDG config path before launching the CLI;
Search also exposes a secret-safe Requests failure diagnostic and classifies
pre-response browser capture failure as transport failure. The corrected CLI
image was built without a provider request, then exercised through the
hardened one-query CLI wrapper.

The corrected **DDG-only CLI** call returned HTTP 200, ten validated organic
hits, complete web coverage, zero row issues, and exit 0; retained source
extent was 26,565 bytes. The corrected **three-provider CLI** call used one
query with two provider Requests in flight and one browser slot. It returned
ordered Brave, Bing, and DuckDuckGo slots with HTTP 200, ten validated hits
and complete web coverage in each, zero issues, and exit 0. Exact retained
source extents were 303,287, 116,570, and 25,610 bytes respectively. Charge
remained Unknown and rich features were NotCollected. No query response body,
result URL, cookie, or opaque token was committed. The local content-free
results are under `/tmp/cas520-ddg-result.gryKbj/`. No named CLI container or
filtered context remained after either run.

## Observed HTTP-200 empty page

A bounded headless Yosoi Request for an impossible `site:example.invalid`
query captured one complete RenderedDom under `/tmp` with HTTP 200. The DOM was
163,271 bytes, SHA-256
`0f8051c4fad514aa55841fbd12c7e9a15f71ccb6c0c786e8e999b91c132e8b59`.
It had no `article[data-testid=result]` or ad rows and contained the visible
"No results found for" marker inside `section[data-testid=mainline]`, with no
observed CAPTCHA/challenge text. This is evidence for that English-language
empty layout, not a general zero-row inference. The committed fixture keeps
only the mainline structure and marker; the raw DOM and query remain under
`/tmp/cas520-ddg-result.gryKbj/`.

The adapter now checks that scoped marker only when its result-row locator has
no match. A different zero-row page remains `MalformedResponse`. The
hash-checked raw DOM replay returns `Empty`, and an identity-bound live CLI
regression on JJ snapshot `bc081ba4882f0215819129386a1e41b8208b05f0`
returned HTTP 200, zero hits, zero issues, `Empty`, and exit 0 in 4,171 ms
measured around the container CLI command. Its retained source extent was
25,399 bytes. The regular-Stable image ID was
`sha256:528117102d18f027d704c63591cc14d4653cd8c02d8c4c28c4adc99f87fd7408`,
with filtered source SHA-256
`4404c4ad05a59ad921a2b121fa5b17f35180e892592691b69f316e9fe6d72ea0`.
The Chrome package, executable, base, seccomp, UID, and sandbox identities
matched the earlier corrected container runs.

A synthetic RenderedDom control carrying the provider-owned
`div.anomaly-modal__title` text from the saved DuckDuckGo HTTP 202 challenge
returns typed `Failed(Challenge)`. No browser challenge page with that marker
has been observed, so this control does not certify browser challenge drift.
Unknown zero-row pages still fail closed as malformed.

## Decision and open gates

**Positive and observed empty capability pass.** The normal headless browser
profile delivered useful DDG organic results and recognized one genuine
English-language empty layout through Yosoi Requests and the Rust-owned Search
parser on this exact current-Stable tuple. These bounded queries do not
establish general selector stability, reliable browser 200-challenge
recognition, 429 behavior, localized empty layouts, or rate-state behavior. Current
DuckDuckGo provider defaults remain **Unavailable**. The repository-wide
Chromium baseline is not promoted by this probe; its separate regression,
security, native/container, and benchmark review remains authoritative in
[chromium-cdp-baseline.md](../chromium-cdp-baseline.md).

The next gate is an additional serial corpus for drift and rate-state
repeatability, plus an observed browser challenge/429 capture with exact status
and completion facts and a sanitized structural fixture. Stop a
provider on challenge or 429. Do not infer a quota or switch to headful,
minimal CDP, HTTP form POST, or another provider silently.

## Final local CLI review revision

The single-parent Search review revision `nlpposyuntnnmpkrwnxnonollqusorks`
(snapshot `e39f68a646f14b121a009334130301c82368e5d1`) built the SDK
probe and CLI into regular-Stable image
`sha256:63a635ddfc1654ab13f9d25794262a9db88341d5611b5a2c0d218bec9bcf9c7d`.
The filtered source SHA-256 was
`4306cdb96e896906e6324c8c430cb34f434983f35adb7524a89428023a55b10e`.
The runtime base, Chrome package and executable hashes, seccomp profile,
sandbox requirement, UID, and resource limits matched the earlier container
runs. This image includes the version-5 effective Policy identity projection
and archived version-4 pre-robots compatibility fix.

One bounded three-provider `yosoi search` call through that image returned
JSON schema 1, termination `completed`, and exit 0. The ordered Brave, Bing,
and DuckDuckGo slots each had HTTP 200, ten validated organic hits, complete
web coverage, and zero row issues. Retained source extents were 308,432,
118,848, and 25,636 bytes respectively. Monetary charge remained Unknown and
rich-feature coverage NotCollected. The run used the explicit Exact profiles
in `search-container-preview-policies.json`; no Current provider default was
promoted. Its local output is `/tmp/cas-search-final-three-provider.json` and
its build identity is `/tmp/cas520-ddg-result.s6DPAv/identity.txt`. Query
responses, result URLs, cookies, and opaque tokens are not committed.

## Final local regression boundary

After the exact-source CLI smoke, lint-only Search and Archive edits produced
JJ snapshot `d2317569d3f51a30bd30de6f0696082afaf7e7c8`. The serial applicable
regression `cargo test -p yosoi-policy -p yosoi-archive -p yosoi -p yosoi-cli
--offline -j1 -- --test-threads=1` passed 448 tests across 73 suites, with
17 intentionally ignored. Warnings-denied Clippy passed for the Search SDK
library, `search_sdk_contract`, and the DuckDuckGo probe; Policy library and
Search identity tests; Archive library and Policy/RequestRun tests; and all
CLI targets. `cargo fmt --all --check`, `git diff --check`, and CAS-520 shell
syntax checks passed.

Repository-wide `--all-targets -D warnings` did not pass because concurrent
Map-only targets (`map_live_stress`, `map_end_to_end`, and `map_policy`) have
lint findings outside the Search change. The full regression above still ran
those tests successfully. The live image remains tied to its earlier exact
`e39f68a6` source snapshot; the post-lint source has local regression and
static-check evidence, not a second live container run.

## Default-workspace five-per-provider CLI preview

The default workspace's new Search JJ change `rsllxxuqzuvlsonwqzpxrlmwknrvywso`
(snapshot `beebc6b65d571536610c03344ef82be3cbbeecc5`) built image
`sha256:53b6cf8e12f5632e357711454dd1b5946077d00fa2910f7711e6327c08826c2c`
from filtered source SHA-256
`3e90719c5307b3eaa0beb2e0ff3ebd366268afc9e27fc0ff54aa8ec17a11efc2`.
The build used the same regular Stable Chrome package, browser executable,
base image, seccomp profile, sandbox requirement, UID, and container bounds
listed above. The source-context helper excluded generated `target-*` directories
after a first attempt exhausted `/tmp` while copying unrelated build output;
that failed attempt did not reach Docker compilation or a provider request.

One bounded `yosoi search "rust programming language" --output json --stats`
call used no active saved Policy profile. Its versioned Current preview defaults
selected Brave and Bing Direct HTTP plus DuckDuckGo headless Browser Requests,
with a five-hit limit per provider. JSON schema 1 reported termination
`completed`, effective Policy identity v5, ordered provider slots, and exit 0.
Each provider returned HTTP 200, five validated organic hits, complete web
coverage, and zero row issues. Measured retained source extents were 309,193,
120,644, and 26,581 bytes. Stderr stats reported 3.659 seconds wall time,
three providers, 15 hits, three Request attempts, and 456,418 known retained
source bytes. Charge and rich-feature coverage remained Unknown and
NotCollected. The content-bearing JSON is retained only at
`/tmp/yosoi-search-default-live.json`; the source identity and content-free
build facts are at `/tmp/cas520-ddg-result.171wnB/identity.txt`.
This single success demonstrates the local default and CLI wiring, not
provider certification or repeatability under challenge/rate pressure.

After that exact-source live run, the review pass added provider-default status to
Search outcome profile facts and CLI human/JSON output. The CLI now labels the
versioned local routes `preview` separately from their defaults version;
Exact, certified, and unavailable routes have distinct labels. This is an
output/provenance change only. The final default-workspace regression passed
468 tests across 74 suites (17 ignored), and focused warnings-denied Clippy,
format, and whitespace checks passed. The status field has local fixture and
SDK test evidence; the earlier live image does not contain this later field.
