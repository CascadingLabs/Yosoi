# Shared learning documentation handoff

The current delivery and evidence are recorded in [the quality review](../documentation/quality-review.md). It supersedes the earlier workspace handoff and snippet counts.

The canonical workspaces are /home/andrew/Desktop/cl/Yosoi and /home/andrew/Desktop/cl/CascadingLabsFE. Both JJ workspace lists contain only default. All 18 former feature workspaces were preserved before removal; receipts and archived local files are in /home/andrew/Desktop/cl/docs-consolidation-preserved-20261011.

Learning navigation is Get Started → Cookbook → SDK → CLI → Concepts. Reference and release notes follow. Plain Markdown is authoritative; frontend output is generated. Install commands use unpinned Cargo/uv add commands in an existing project.

The current Rust reference artifact is .generated/reference-docs-e3df268213c6, pinned to e3df268213c60378ee923a838b24be05d0954233. It is an unsigned local preview. Learning edits do not regenerate it. The default frontend preview is http://127.0.0.1:4321/yosoi/quickstart/.

Browser execution and provider-dependent scenarios need separate runtime evidence. Compilation, local fixture checks, hosted CI and publication are distinct. No release or deployment is claimed by this handoff.

## 2026-10-12: Cookbook removal

Andrew explicitly requested deleting Cookbook before beginning the Concepts rewrite. Removed the 11 remaining source pages and the Cookbook navigation entry. Updated inbound links to existing Concepts or SDK pages. This supersedes the Cookbook navigation guidance above. The Concepts narrative rewrite is subsequent work.

## 2026-10-12: CLI Install simplification

Andrew approved an installation-only page with platform/method tabs, a version check and a Request a document link. Updated `cli/index.md` in the default Yosoi workspace, keeping its public URL. Linux is the first tab, followed by UV, macOS, Windows and Cargo. Replaced only the CLI navigation selector with explicit pages so the index uses its Install title rather than the frontend's directory Overview label. Existing unrelated working changes were preserved.

Source inspected at JJ working revision `8c243ea4` (dirty), parent `b53841e6`. Installer commands are retained from the existing page; checked install destinations, PATH handling and platform requirements against `scripts/install/install.sh`, `scripts/install/install.ps1` and the workspace Rust version. No installation or SDK build was run.

Validation: `node scripts/docs/validate.mjs` passed (574 Markdown pages, 4 assets, navigation and native Markdown rendering). Scoped single-thread formatting of `cli/index.md` matched the authored file. Interactive browser/static archive tab behavior was not checked and no publication was performed.

Edited page SHA-256: `74d31594dcedbb2213271ca8a8c383f9e86a3fb29edb5dfcb109d5d902ad4788`.
Navigation SHA-256: `e80fff67392be4f4b59d268b24a0584bdf4ef4fdef4a02319496f795c4f3d1b1`.

### CLI Install review corrections

Andrew requested Apple, Windows and Linux penguin SVGs matching the existing UV/Cargo tab icons. Added platform assets, tab icon recognition and CSS masks in CascadingLabsFE. He also requested removing the introductory sentence and Next step, and renaming the shared check heading to Verification with a smaller visual size. Verification remains H2 to end the tab group, styled at the H3 size by the frontend so it stays visible with every installation tab.

Validation: focused frontend code-variants browser test passed with all three platform icon elements; scoped frontend formatting and variants lint passed. Yosoi Markdown/link/navigation/native rendering validation passed again after these content changes. No installation, full build or deployment was performed. This supersedes the page and navigation hashes above for the page content; the prior navigation hash is unchanged.

## 2026-10-12: CAS-588 opening Concepts lesson

Page job: help the reader construct an HTML Document from bytes, locate the lamp name and price, and distinguish a match from satisfying both expected outputs.

Andrew selected the title **Making sense of HTML**, requested a QScrape link, a 5–10 minute lesson including execution, and a JSON navigation update. Reused the existing documents-and-evidence URL. Reading duration is an editorial target, not a measured user timing. Later lessons remain unchanged.

Workspace: /home/andrew/Desktop/cl/Yosoi, JJ change swuspkkv. Working-copy revision observed after drafting: e79811d6; pre-existing documentation/Python changes remain. This receipt describes dirty source via exact hashes, not commit-only validation. Rust default features, no browser/network acquisition during example execution.

rust Example: read the product, first rust fence: SHA-256 5d9751e238b96fda441688da84ba68fb828e3a10ad0833c7300fa3059c4f589a, 42 lines.
python Example: read the product, first python fence: SHA-256 6942bcd39ce537baa0ae88ea8ef26a8a7c83e28c882f9ea40fea447e3279a48e, 26 lines.

Both exact snippets were extracted into temporary harness files and executed. Rust: CARGO_BUILD_JOBS=1 RAYON_NUM_THREADS=1 cargo run --locked -p yosoi --example docdiff_html_first. Python: uv run --no-sync python .generated/docdiff-html-first.py in the existing project environment. Both printed name: Arc desk lamp and price: $68.00 and passed the visible checks. Existing Rust dead-code warnings remain.

Each language was also executed with the price changed to $70.00 and with the price paragraph removed. All four variations produced the expected assertion failure and the expected preceding findings. Restored exact snippets before removing temporary harness files.

Python imported /home/andrew/Desktop/cl/Yosoi/python/yosoi with version 0.2.1 and the installed native extension _native.cpython-314t-x86_64-linux-gnu.so. Native SHA-256: 2d10358dde9b9a29f18f83f041e4c36cc550eef9024f41523312dcf0068f1031. Native extension was not rebuilt; observed snippet behavior is verified against this artifact, not an assertion that it includes every current native source change.

Live product response https://qscrape.dev/eshop/html/product/obj-001/ contained the selected h1 and shop-detail-price paragraph with Arc desk lamp and $68.00. The offline excerpt preserves those elements and values, with presentation whitespace.

Scoped vp fmt (one thread) applied only to six edited public files. node scripts/docs/validate.mjs passed: 574 Markdown pages, 4 assets, navigation, native rendering. Updated first-lesson order to Overview, Making sense of HTML, Locators and findings, then Discovery and acquisition. Replaced incoming reuse-captured-input links because that material now lives in SDK Documents.

Served HTML at http://localhost:4321/yosoi/concepts/documents-and-evidence/ has the new title, opening, QScrape link, both snippets, previous Concepts and next Locators and findings. Astro server runs from /home/andrew/Desktop/cl/CascadingLabsFE. The frontend uses a separately pinned older Rust reference artifact (e3df268213c60378ee923a838b24be05d0954233); the lesson uses authored SDK links, and example execution above establishes the relevant API behavior. No reference regeneration was performed. Browser controls were unavailable in this session, so interactive tab/callout clicks and archived rendering were not independently exercised. No hosted CI, publication, or deployment is claimed.

Public page SHA-256: 9a36eb3e8947053b217124a5d8b899cbfe849d73d9354b9f6d277fc3524f4a22. Navigation SHA-256: e04bbf783c6d8a954139e981a9790978e2cac5307120151c11a3058f92af9244.

### CLI version selection

Andrew requested version-pinning instructions inside installation tabs and a shorter Cargo command. Added 0.2.1 examples for UV, shell installers, PowerShell and Cargo. Checked script version arguments against their parsers. Cargo retains `--features cli --locked`, removes the local build-worker setting and redundant `--bin yosoi` (the crate defines one binary), and pins exactly with `--version '=0.2.1'`. No installs or builds were run. Markdown/link/navigation/native rendering validation passed; scoped formatting applied only a trailing blank-line correction.

### Opening lesson follow-up: installation prerequisite

Andrew clarified that Concepts assumes Yosoi is already installed. Removed project creation and dependency installation commands from Making sense of HTML; retained the Install link, language-specific file placement, and execution commands. Code snippets are unchanged, so execution checks were not repeated.

### Opening lesson follow-up: visible results without assertions

Andrew requested a public-example rule: avoid assertions unless absolutely needed. Added the rule to docs/public/AGENTS.md and removed the opening lesson assertions and the Rust map used only by those checks. The exercise now inspects printed values; missing price remains a matched outcome and prints only the name. Both updated exact programs ran successfully with the original input. Both languages also ran with a changed price and missing paragraph; maintainer harness checks confirmed exact output and successful exit for all four variations. Temporary harness sources were removed. These results supersede the assertion-based exercise above.

Updated snippet SHA-256:
rust: 36e9b9dbecfe9a12c5bd2fd08745ceac7de928b38f827f4666741a1ac2ed5771
python: 6b62980de3e59963c36bf803ca4cfcc97682bde527238fcc3035162e674a80cd

### Opening lesson follow-up: Plan declaration and evaluation

Andrew requested removing the Python matched-status guard and explaining why Plan construction and locate are separate. Removed the guard, added a shared explanation of describing reusable outputs versus evaluating a specific Document, and added short callouts to those operations in both languages. Python prose now describes direct finding iteration and retained outcome status/diagnostics. The exact updated Python snippet ran through uv run --no-sync python and produced the two expected lines. Rust executable code is unchanged; only callout comments were added, so Rust execution was not repeated.

### Opening lesson follow-up: defer Rust outcome and value handling

Andrew requested removing the ProjectedValue import and the LocateOutcome match block. Rust now prints the locate outcome with pretty debug formatting, without branching on outcome or value variants. The language-specific explanation directs readers to the name and price findings; shared exercises refer to findings rather than identical console formatting. Exact Rust snippet executed with one Cargo worker and no browser features; output contained Matched, Arc desk lamp, and $68.00. Temporary harness removed. Python code is unchanged. SDK design friction: Rust currently offers findings within the Matched variant, so simple direct finding iteration requires outcome handling; public API changes are outside this documentation scope.

### Opening lesson follow-up: text projection and separate declaration/execution

Confirmed from implementation: QuerySpec::text declares an OutputPlan with DescendantText for CSS; HTML evaluation emits ProjectedValue::Text from descendant text. Strict UTF-8 decoding happens in HTML parsing/evaluation, not when the text builder is called. Python Query.text similarly declares projection="text". Replaced the line-by-line builder explanation with the reader goal and placed the reason for separating CSS/Plan declaration from locate execution beneath both language snippets, as Andrew requested. Executable code is unchanged. Source evidence: internal/documents/query_output.rs:5–10,44–49; html.rs:265–280; html/evaluation.rs:310–326; python/yosoi/locators.py:401–410.

### Opening lesson follow-up: worked changes instead of homework

Andrew requested showing the input variations in code rather than assigning an exercise. Replaced the numbered Change the input instructions with paired continuation snippets that evaluate a $70.00 product and a product without a price using the original Plan. Each snippet identifies its exact placement in the preceding complete program. Both combined programs executed successfully; maintainer checks confirmed the changed price and retained name without a price finding. Kept the shared explanation of matching some evidence versus filling every output and text versus validated money. Temporary harnesses removed.

### Opening lesson: final editorial pass

Polished Making sense of HTML after Andrew's review. Trimmed repeated Plan explanation from shared prose while preserving the requested explanation beneath each language block. Shortened the bytes/Document introduction, kept worked variations and the Plan payoff callouts, and replaced the recap with a direct next-lesson link. Preserved offline wording, the lamp identity, installed-project assumption, no asserted values, no Python status guard, no Rust outcome/value handling, no reading-time directive, no homework, and no API-reference links.

Compared all four language snippets before/after, excluding callout comments: executable code is unchanged, so passing execution checks were not repeated. Scoped formatting and node scripts/docs/validate.mjs passed (575 Markdown pages, 4 assets, navigation, native rendering). Served HTML was checked for the edited introduction and both language explanations/callouts. Browser interaction, archived rendering, hosted CI, and deployment remain unverified. The broader CAS-588 rewrite is ongoing; this completes the first lesson draft.

Final page SHA-256: fdf809302abe45216f53097faf113c10d5e2284086939a5d23fbe522e1b6ed27
Final snippet SHA-256:
1. rust: 5e7c543fc3dbfa2faf0b8aeb2d807b81bf909d3813da88414fddefecfc9710e1
2. python: 406586d0efdb6ca64970fc427a2d98378ebd92ae17b3755b2404e1afe6031b8b
3. rust: 318bc789a4bab8c234a3b19b4b6c65c532c263692e8d8a14b9038a71e369bcb7
4. python: 525365545c91e9da03b6153e66bb3390557fa5549fe316b9f062f24c815a63ec

Final-polish correction: Andrew requested removing Matched terminology from the opening lesson. Removed the status-oriented explanation and described the findings directly. Rust still uses its existing debug output; executable snippets are unchanged.

### CAS-588: extend Making sense of HTML with catalog link selection

Andrew chose to keep deeper locator teaching on the original page and authorized implementation. Extended it with two controlled catalog cards, then selected the lamp heading link by product ID and read both its text and href. The complete new programs use the same fixture, preserve simple printing without assertions or outcome branches, explain Plan declaration versus locate execution beneath each language block, and retain per-language explanations. Rust clones the query declaration to create two projections; Python creates both from its query directly. Findings are explained briefly through their source identity/location, and relative href is distinguished from visiting a page.

Verified deployed HTML catalog contained both selected product IDs/names and the heading-link markup. The offline excerpt omits surrounding shop layout but keeps those relationships and attribute values. Exact new snippets executed with CARGO_BUILD_JOBS=1 RAYON_NUM_THREADS=1 cargo run --locked -p yosoi --example docdiff_catalog_link, and uv run --no-sync python .generated/docdiff-catalog-link.py. Both found Arc desk lamp and /eshop/html/product/obj-001/; neither returned the mug. Rust default features, existing Python environment/native artifact, no native reinstall. Temporary harness sources removed. Earlier snippets were unchanged and were not rerun.

Navigation now explicitly lists Concepts pages so locators.md is omitted from the sidebar; its published URL remains available. No new page was created. The HTML lesson now ends by introducing the next HTTP acquisition lesson. Scoped formatting and node scripts/docs/validate.mjs passed: 575 pages, 4 assets, navigation/native rendering. Local served HTML inspection covers the new sections, both examples, and sidebar order; interactive browser checks, archived rendering, hosted CI, and deployment are not claimed.

Working revision before this slice: 7b422d70 (JJ swuspkkv), with existing dirty docs/Python work preserved. Final page SHA-256: b1a0c2f9ab42d5a3c607b4e5ae1793b675ec7fcd05f887058d05b530ea5991de. Navigation SHA-256: 459e0bd3cea0cad83454e7afad843aead0102bc2d448ae6d343d756d5a57565e.
New snippet hashes:
rust: 7d09a998fae88d23f32bf3266982987339d9d4176f3b9db6e547309451ae3e88
python: 657285626ffb1250814248f7a64ab41c571e8d9d845ff7da96a7bc892cb706ec

### CAS-588: Fetching our first page

Page job: replace embedded HTML with a live Direct HTTP acquisition, inspect its Response, and reuse the existing catalog Plan. Rewrote discovery-and-acquisition.md at its existing URL with title Fetching our first page. Updated the preceding HTML lesson link and the explicit navigation label; redirected two older discovery-oriented inbound links to existing Map/Responses guidance so they do not promise removed Map/Search teaching.

Source revision before drafting: 064fbc8e, JJ swuspkkv, default Yosoi workspace with unrelated docs/Python work preserved. Source evidence: policy/policy/page.rs Page::default selects one DirectHttp acquisition; policy/policy/limits.rs MaximumElapsed::default is 10 seconds; request/authoring.rs new does no I/O and send uses default Policy; request/outcomes.rs retains optional produced/partial Documents; Python request.py exposes corresponding attempt/document outcomes. Both accessors used by the examples can return partial Documents, and shared prose explains that boundary.

Exact Rust and Python snippets extracted to temporary harnesses. CARGO_BUILD_JOBS=1 RAYON_NUM_THREADS=1 cargo run --locked -p yosoi --example docdiff_http_first and uv run --no-sync python .generated/docdiff-http-first.py both completed against https://qscrape.dev/eshop/html/: observed HTTP 200, 8,187 retained HTML bytes, Arc desk lamp, and /eshop/html/product/obj-001/. Rust default features; Tokio current-thread runtime. Existing Python environment/native extension, no rebuild or new virtual environment. Existing Rust dead-code warnings remain. Byte counts are recorded observations, not fixture expectations in public prose. Maintainer checks verified status, nonzero bytes, and both extracted values outside public code.

One additional Python run changed only the URL to https://qscrape.dev/eshop/javascript/ to validate the transition to browser evidence. Observed HTTP 200, 7,265 retained bytes, and no name/href findings. This verifies the pure HTTP limitation for the inspected site, not browser execution or challenge behavior. Removed both temporary harnesses. Earlier HTML snippets were unchanged and not rerun.

Scoped formatting and node scripts/docs/validate.mjs passed: 575 Markdown pages, 4 assets, navigation/native rendering. Local served HTML at http://localhost:4321/yosoi/concepts/discovery-and-acquisition/ has the new title, complete examples, and preceding HTML lesson link; the navigation label resolves to Fetching our first page. No interactive browser, archived rendering, hosted CI, publication, or deployment is claimed. Existing separate older Rust reference artifact was not rebuilt; this lesson contains no API-reference links.

Page SHA-256: 61751e5f06d69d6410b7321ed68a266779920688b598c0a244915486d630dc36. Navigation SHA-256: c62e5b536d1afc551cb0e02bb0bc8f79fa649d7e00fcb65ba0af033a62f14500.
Snippet SHA-256:
rust: de41624f592e3c9b93947f94bb31098b02dec5e63cb8d645b7c6082a47b1d3be
python: 2e7bf62f15a36181c728e1453d3a3d44bff6942f1c2ee5a192737c617f2b6e16

## 2026-10-12: CAS-589 CLI self maintenance for 0.3.0

Andrew authorized planning, implementation and documentation in the default workspace, then explicitly approved a draft PR with native CI. Canonical commands are `yosoi self update` and `yosoi self uninstall`. Update uses a yes/no prompt defaulting to yes; uninstall defaults to no. Both support `--yes`; non-interactive sessions require it. Explicit update selection uses `--target-version` because global `--version` reports CLI identity.

Scope: standalone installers write `.yosoi-install.json` with method, schema, version, executable SHA-256 and Windows PATH ownership. Package-manager metadata takes precedence over the receipt; UV and Cargo operations print their manager commands, including custom directories, without mutation. Unknown/stale ownership refuses maintenance. Standalone updates use bounded HTTPS download, manifest checksum, a single regular ustar member, candidate version verification and staged replacement/receipt commit with recovery backup preservation. Windows uses an acknowledged after-exit helper, a 60-second parent wait, shared maintenance lock and a persistent pending/success/failed JSON result. Uninstall preserves configuration/evidence and shared directories; Windows PATH cleanup is conditional on recorded ownership and an otherwise empty directory.

Public page job: teach users to update or remove the executable owned by their selected installation method. Page: `cli/self.md`; default-tree Install links to it and default-tree CLI navigation includes it. The feature PR excludes prior CLI Install/sidebar edits and unrelated docs/SDK work.

JJ feature change `swuspkkv`, commit `3fd5bea351167f4f61a44cbd68669bc65c570f27`, parent `b53841e6a1379381ecf93b0f470277cc0ed8a415`. Default workspace continues as child `tyxzxyrv`. Splitting the 16 feature files preserved SHA-256 fingerprints for all 134 recorded working-tree paths. Draft PR: https://github.com/CascadingLabs/Yosoi/pull/161. Issue: https://linear.app/cascadinglabs/issue/CAS-589/cli-self-update-and-uninstall-across-standalone-uv-and-cargo, in project P-CAS-53 under initiative I-6.

Local validation: 14 maintenance unit tests on the final feature source; broader focused CLI suite passed 73 tests. Clippy with CLI/bin/test targets passed. Six disposable built-executable Linux tests passed (real prompt defaults, non-interactive refusal, uninstall preservation, stale receipts, Cargo custom roots and UV exports). Six offline POSIX installer tests passed with one optional real-executable fixture initially skipped. PowerShell 7.6.6 syntax parsing of all four scripts passed. Deferred replacement and invalid-update preservation ran using PowerShell on Linux and passed after correcting File.Replace null arguments with `[NullString]::Value`; this is not native Windows proof. Workflow lint and shellcheck passed. `vpr check` passed in the default tree and an exact-commit export (581 Markdown pages, 4 assets, 24 tooling tests and 2 native rendering tests in that export).

Native PR-triggered workflow 38317509310 is running on Windows 2025, Apple Silicon macOS 15 and Intel macOS 15. It tests compiled CLI behavior, disposable installation ownership, a real UV wheel/tool installation, native installers and Windows deferred replacement. Release CD repeats focused/installed-artifact checks on the native release matrix. Native completion, whole-PR green, merge, 0.3.0 publication and deployment are not claimed while CI/review remain pending.

### HTTP lesson follow-up: simpler Python presentation

Andrew found the nested attempt/document/status/printing logic too heavy and recalled Alpha's clean .print helper. Current public Python/Rust request and locator facades have no print helper. Simplified Python with the existing response.documents convenience property and locate(plan).values(), reducing presentation to a document loop and one built-in print call. Updated its explanation and expected list output. The convenience property includes retained partial Documents and omits unavailable ones; shared prose keeps that boundary and points out retained acquisition outcomes. Exact revised Python snippet ran successfully through uv run --no-sync python, printing the expected lamp name and relative href list. Rust code is unchanged and was not rerun. Temporary harness removed.

SDK design question: a public readable print/display helper could present request attempts, document completeness, and locator results without requiring tutorial code to hand-format them. Alpha precedent comes from Andrew's recollection; no historical implementation was verified here. Restoring such a helper would be SDK work, separate from the authorized documentation change.

### HTTP lesson follow-up: simplify Rust presentation too

Andrew requested the same presentation simplification for Rust. Replaced nested printing/status/optional-document branches with an iterator over retained Documents using flat_map and filter_map, followed by one locate-result print. Rust currently has no Response::documents convenience method, so the existing public attempt/document accessors provide this path. Updated Rust explanation/expected output and shared prose to stop implying HTTP status/byte counts are printed. Exact Rust snippet ran with one Cargo worker and found Arc desk lamp and the expected href. Python code is unchanged and was not rerun. Removed the temporary harness.

### CAS-588: Using a browser

Page job: introduce browser acquisition, explicit rendered-DOM selection, headless/headful modes, and the capture-timing boundary without promising asynchronous catalog readiness. Created using-a-browser.md after the HTTP lesson, added it to explicit navigation, and linked the preceding page to it. The original lamp selector/Plan and simple presentation are retained in both languages. No SDK, browser flags, sandbox/isolation, site, or system browser changes were made.

Source before drafting: 95915bc3, JJ tyxzxyrv. Existing work preserved. Inspected policy Acquisition/DocumentRequest APIs, standard.rs navigation completion and settlement settings, browser distribution admission, and public request/document facades. Rendered-DOM-only acquisition uses DomContentLoaded; standard settlement is disabled. This cannot guarantee async product hydration. Inspected supported Until/Flow APIs to confirm the next lesson can teach an evidence-based wait; no sleep or retry was used to make this lesson pass.

Initial browser probe with system Chromium 152.0.7977.82 returned browser_failure/unavailable. Current source Stable admission excludes M152. Located existing cached regular Google Chrome 154.0.8037.97 at .generated/pr121-browser/opt/google/chrome/chrome; executable SHA-256 6c792041b07547a662e1b17974d1dc34a3db630379b45d9d89ddd7e3e68cc587. Read the baseline from b53841e6:docs/chromium-cdp-baseline.md because the working copy no longer contains that file. M154 remains admitted by the current source review. CHROME was set only for validation commands; system defaults were not changed, and no testing-only browser was used. Admission is not full browser-stack certification.

Exact primary Python snippet: CHROME=/home/andrew/Desktop/cl/Yosoi/.generated/pr121-browser/opt/google/chrome/chrome uv run --no-sync python .generated/docdiff-browser-first.py. Exact primary Rust snippet: same CHROME, CARGO_BUILD_JOBS=1 RAYON_NUM_THREADS=1 cargo run --locked -p yosoi --features browser --example docdiff_browser_first. Rust focused feature build took 1m19s, one worker. Both acquired retained DOM and reported no product findings: Python [], Rust NoMatch with captured Document identity.

Both shown headful configuration fragments were substituted into the corresponding complete program and executed sequentially against the same site with a display available. Python again printed []; Rust again printed a no-match outcome with a retained Document identity. Headful requests exited successfully; manual visual window inspection was not performed. All temporary harness sources removed.

A focused Python capture inspection resolved whether the empty result was a loading shell or a page error: selected outcome produced, document class rendered_dom, captured bytes contained Loading shop, and no obj-001 card was present. This is the observation underlying the timing explanation. It does not prove that browser mode changes challenge outcomes.

Scoped formatting and node scripts/docs/validate.mjs passed: 576 pages, 4 assets, navigation/native rendering. Served http://localhost:4321/yosoi/concepts/using-a-browser/ has the new title, both mode examples, DomContentLoaded explanation, prior HTTP lesson, and next Flow discussion. Interactive documentation tab/callout and archived rendering checks remain unavailable; no hosted CI, publication, or deployment is claimed. Existing older reference artifact was not regenerated.

SDK design question: a simple browser Request does not expose an application-readiness condition. JS eShop requires the next Flow/Until lesson for dependable product evidence. Kept that distinction honest in public prose rather than claiming a successful browser Request necessarily obtains catalog values.

Page SHA-256: 852adc33dd200f566e05c50dc246a6e7023a5fb45b096b7e0e687f728a85b353. Navigation SHA-256: 9fd6aa7015821e591e5d94cec2eec1d984e67c33345cdbad6d49c2614b80f0a7.
Snippet SHA-256:
1. rust: 442498f55d24aaf80c8e546077e9cbf2a2150485eba2cf716706aec70fc4fedd
2. python: 1db6943d3bb81a95868ec795643d8f3e4056b1e460a865900fbd8379e7e18c80
3. rust: 44be74104dfd463cec893e5ce35baadb740198bacb7a571f677033ef07fe7f73
4. python: e9fc51ca1fe5b787b1534024d20bd52adca21ee5f846eb20cfa60230bb6eda27

## CAS-588: complete Concepts series rewrite

Andrew authorized writing the remaining series after the proposed ordering. Preserve the three reviewed opening pages. Remaining scope: readiness/first Flow; typed product/catalog records; accessibility and cart interaction; JSON plus XML/text; nested recipes and script/file/module execution; retained Sessions/Work; controlled Turnstile access; Map/Search; budgets, failure/cancellation/uncertainty; tab/capacity/Watchers; saved Documents and Rust Archive/AutomationRecord/View. Overview and navigation must match the completed series. Maintain paired passages where supported; no Cookbook, setup boilerplate, homework, reading-time directives, speculative APIs, or unnecessary assertions. SDK gaps stay private. Exact snippet execution and served-text checks are required before completion. Source before full rewrite: tyxzxyrv 4a126be9, with existing user/other-run changes preserved.

### CAS-589 final native verification and merge gate

Final feature source: `b06d24a39c8c8e160a91a5eafff920571ca23d7a`, base `b53841e6a1379381ecf93b0f470277cc0ed8a415`. Native PR run 38321839513 succeeded on Windows 2025, Apple Silicon macOS 15 and Intel macOS 15. All other PR checks passed on the same head. Final Windows helper uses simplified paths for Windows PowerShell, direct console readiness, bounded startup diagnostics with early JSON error preservation, `[NullString]::Value` for File.Replace, and streaming .NET SHA-256 rather than a PowerShell module hash function. The inherited module environment is retained after a removal attempt caused a startup regression. The POSIX PTY test retains its parent slave descriptor until final output is drained and terminates on empty EOF reads. CI uses the Windows runner's available grep for textual assertions.

Andrew authorized merging after native validation. Marked PR #161 ready and attempted a normal squash merge with the exact head guard. GitHub rejected it because main requires independent approval (REVIEW_REQUIRED). Queued protected auto-merge with SQUASH; it is awaiting review. No admin override, merge, release or deployment is claimed. Asked Andrew whether to wait for that independent review or explicitly authorize an administrator override.

Before landing, captured 147 current working-tree changes in .generated/cas-589/pre-land-tree.json. Other documentation work continues in default; use a fresh snapshot at actual integration rather than restoring old fingerprints. Preserve the newer Concepts/navigation and SDK/docs edits. CAS-589 is Final Boss with exact-source/native evidence and the protected merge gate recorded in Linear.

### CAS-589 review correction: implicit update ordering

The automated review of b06d24a39c identified that GitHub latest excludes prereleases, which could implicitly replace a newer RC with an older stable version. Fixed in feature source `8eae07abccb49b4df0d0c3bc70b93066c5978153`: validated numeric minor/patch and RC ordering; final releases follow RCs of the same version; implicit updates require a strictly newer target. Explicit --target-version retains deliberate downgrade selection. Added one table-driven regression test covering stable/RC and numeric ordering. All 15 maintenance tests and test-target Clippy passed; exact-commit exported docs gate passed (581 pages, 4 assets, 24 tooling tests plus native rendering tests). A concurrently edited default-tree Concepts page has unrelated formatting drift and was not changed.

Disabled auto-merge before updating the protected PR, then pushed the corrected feature only. Native run 38324483865 is testing the updated source. All-platform results from b06d24a39c do not certify this new head. Independent approval/admin-override authorization remains pending; no merge is claimed.

### CAS-588 final series validation (2026-10-12)

Completed the 14-lesson Concepts series, overview, explicit JSON navigation, sequential next links and legacy locator/outcome handoffs. Preserved reviewed opening examples and other concurrent changes. All 50 newly authored Rust/Python snippets executed as complete programs or in their explicitly stated continuation context. Current snippet hashes and output paths are recorded in .generated/docdiff-series/final-snippet-ledger.json. After formatting changed JavaScript fixture punctuation, both file/module variants were rerun in both languages and passed.

Python now pairs the final Rust browser-evidence example with a complete serialized FlowOutcome save/restore program: saved operations 2, retained HTML reads Arc desk lamp twice. No Archive/View parity is claimed. Portable Plans use compiled()/from_compiled(); module evaluation reads exported values without invoking exported functions; AutomationRecord uses the root public module. Cart examples check product, quantity and total through task-level typed assertions.

Focused docs validation passed: 583 Markdown pages, 4 assets, navigation and native Markdown rendering. Docs tooling tests passed: 25 tests in 5 files, plus 2 native rendering tests. Initial root vp run test invocation failed because the root is not a workspace package; rerunning from scripts/docs passed. Local preview returned HTTP 200 with current titles for overview and all 14 navigation lessons. Browser examples used the previously recorded regular Chrome 154 with single-worker Cargo and the existing UV environment. Own temporary Rust harnesses and project-root saved artifacts removed.

Expected negative cases were executed, including byte limit, missing prerequisite and precancellation. Live Turnstile remained pending; that example stopped and skipped two later actions, rather than proving challenge completion. Respecting current QScrape robots yielded zero Map captures; explicit controlled ignore variant retained four with an eight-request bound. Search candidates are not guaranteed relevant. No full SDK suite, hosted CI, deployed publication, Docker performance comparison, successful Turnstile pass, or manual interactive documentation/archived frontend inspection is claimed.

### Concepts audit and code spacing (2026-10-12)

Scope: read-only narrative/API audit of all 17 Concepts sources, with Andrew's follow-up authorizing code-spacing edits. Workspace /home/andrew/Desktop/cl/Yosoi; initial JJ tyxzxyrv 31c58fcc. Existing broad dirty tree preserved. Reviewed current anchors, navigation, public-doc contract, current Python extraction/assertion models, Rust Contract/assertion facades and derive plan, browser acquisition timing/projection, and QScrape Turnstile/robots implementation.

Spacing improved in 14 pages and checked across 62 language blocks: Ruff format with isolated 88-column settings; rustfmt with 88-column settings and import/module ordering disabled; fragments formatted in a temporary main-body context. Added blank lines between declarations, invocation and evidence inspection. Python ASTs remained identical for all 31 blocks; Rust literal contents and token sequences remained identical for all 31 blocks apart from optional trailing separators. Per-block before/after hashes and verification are recorded in .generated/docdiff-spacing/verification.json. Earlier runtime evidence remains linked through formatting equivalence; browser/network examples were not rerun for whitespace-only edits. No SDK changes or narrative rewrites.

Audit findings: sharing-browser-capacity.md configures slots/queues/yielding but runs sequentially, so it does not demonstrate contention or yielded capacity. Recommend a later focused two-caller Rust demonstration, explicitly preserving Python's narrower public surface. contracts-and-validation.md explains a zero default minimum but gives no executable minimum-count variation. Recommend a small empty-input/required-record example. actions-and-flows.md spans nesting, screenshots, inline/file/module scripts and network expectations; this broad scope is an editorial consideration, not a runtime defect. No new blocking API mismatch established by this audit.

Focused structural validation passed: 583 Markdown pages, 4 assets, navigation and native rendering. All 17 Concepts routes returned HTTP 200 in the local preview. No new manual tab/callout interaction test, archived frontend test, hosted CI, deployment, or full SDK build claimed.

### Separate yielding lesson and minimum-count variation (2026-10-12)

Andrew authorized a separate yielding concept and a substantially small minimum-record-count variant. Page jobs: yielding-while-waiting.md demonstrates another tab using a single execution slot while a condition wait retains Work; contracts-and-validation.md adds five-line variations showing an empty catalog below the task minimum. Navigation/overview and capacity Next include the new lesson; evidence order moves to 15. Existing user and concurrent changes preserved.

Source at completion: tyxzxyrv andberg9@gmail.com 2026-10-12 20:36:50 46c58e8d (no description set)
Public implementation traced: session.rs Work::wait_until installs a condition observer, tracks parked execution, and calls completion without capacity when yield_on_wait is true; internal/engine/execution.rs distinguishes parked and waiting counters. Rust ContractOutcome::require_all accepts NoMatch as an empty vector; Python ExtractionPolicy.minimum_records and report.meets_minimum_records/require_all establish the acceptance boundary.

Final formatted Rust yielding program executed with --features browser and one Cargo worker. Output Other tab: Observed; Still parked: 1; Missing marker: Rejected. Earlier compile failure from borrowing a temporary Condition was fixed with a named binding before publication. Final Python program executed with existing UV environment: Yielded: True; Missing marker: rejected. Python has no public tab creation or execution_snapshot, so prose explicitly limits its variant to the receipt decision, not independently observed contention. Both minimum variants ran in the stated catalog context and printed Minimum met false/False. Exact new snippet hashes and outputs: .generated/docdiff-yield/validation.json.

Structural validation passed: 584 pages, 4 assets, navigation and native rendering. Local preview contains the new lesson, minimum variation, capacity next link and overview entry. No hosted CI/deployment or interactive/archived frontend claim. Removed only own docdiff_yield.rs and docdiff_minimum.rs harnesses.

### Full runnable recheck, yielding motivation, Docker docs and CDP ticket (2026-10-12)

Andrew requested a fresh execution recheck of every Concepts example, then added Docker concept/setup scope and explicitly requested a CDP-attachment issue in SDK Hardening. All 66 current Rust/Python blocks were extracted from Markdown and executed sequentially, with fragments composed exactly in their stated surrounding programs. File/module JavaScript fixtures also came from the current Markdown. Every final snippet hash matches its executed input. Results, commands, outputs and harness hashes: .generated/docdiff-recheck/final-results.json. Three initial live browser checks failed (Python headful Request, Rust readiness Flow, Python accessibility Request); focused exact-code reruns passed. Cause of those initial failures is not established, and they are retained in the record. Expected failure/cancellation/limit/Turnstile-pending cases remain distinguished from successful task completion.

Rust used the current workspace with --features browser, one Cargo worker and regular cached Chrome 154. Python used UV --no-sync, source Python package 0.2.1 and the loaded cpython-314t native extension on free-threading Python 3.14.7 (hash in delivery.json). No full SDK suite or native rebuild. Added explicit yielding-under-load motivation: two tabs show mechanism, not large-scale performance proof.

New page jobs: getting-started/docker.md installs/starts the published Chromium/CDP browser runtime in headless or headful mode with requirements; concepts/browser-windows-in-docker.md shows the lamp on an internal virtual display and optional viewer. Navigation, Install and sequence links updated; evidence now order 16. Current public SessionPolicy rejects a non-None remote endpoint, so neither page invents Yosoi attachment. Images are browser services without the SDK/application. Linux Engine workflow only is runtime-verified; Docker Desktop, ARM64 and hardware GPU behavior are not claimed. Official Docker installation/network/security docs consulted and linked.

Verified anonymous published 0.2.1 manifests: headless Linux AMD64/ARM64; headful AMD64. Pulled and tested the actual published AMD64 images. Headless manifest digest 8c4dbd7e5500cda543f7053c9e3b3c50df639905f11cdb29fa71360d4526346b; headful digest 8ad2bf6a6ef322bd4c568631f89529be3b9899ffa51dce86b9841e47636b248b. Release seccomp profile download matches current source SHA-256 7df54f14f794a8870d8182a3653085ffc716d30a2fec9e722776c3f8c862f063. Exact start commands ran with one browser, CPU/memory/PID/shared-memory bounds, dropped capabilities and no-new-privileges. Both became healthy as UID 10001 and CDP evaluation read Arc desk lamp after creating the documented tab. Headful viewer opened, HTTP 200 served, then viewer closed. No manual visual/RFB interaction or full browser certification is claimed. Container results and image IDs in docker-results.json; both own test containers removed.

Created and independently read back CAS-591 in 0.3.0 SDK Hardening / Backlog: https://linear.app/cascadinglabs/issue/CAS-591/add-public-rust-and-python-cdp-attachment-for-existing-and-hosted . Native Plain English callout, current limitation, scope, ownership/authentication/trust boundaries and Docker/Kernel/AgentCore interoperability targets were retained. Provider docs were consulted; no live hosted-provider or SDK implementation is claimed.

Structural checks passed: 586 Markdown pages, 4 assets, navigation/native rendering. Focused docs tooling tests passed. Local preview contains both new Docker pages, overview entry and yielding-under-load section. No hosted CI, publication or deployment claimed. Source and selected page hashes at completion: .generated/docdiff-recheck/delivery.json.

### Archive bridge ticket and Docker setup corrections (2026-10-12)

Created and independently read back CAS-592 in 0.3.0 SDK Hardening / Backlog: https://linear.app/cascadinglabs/issue/CAS-592/add-python-archive-support-and-rewrite-keeping-the-evidence-around . Ticket has native Plain English callout, Python Archive/AutomationRecord/bounded-inspection scope and the requested Keeping the evidence rewrite sequence: smallest supported Document Archive round trip; real Flow record after browser cleanup; bounded saved observation inspection; paired current APIs; removal of manual JSON substitutes after bindings are verified. No SDK implementation or speculative public calls added.

Andrew corrected Docker setup to assume Docker already installed/running, and requested the container name yosoi-browser. Removed the Install Docker section and host installation links/commands, corrected description, and consistently renamed references in both Docker pages. Browser runtime setup commands otherwise unchanged.

Andrew asked whether the seccomp profile could be bundled in the image. Official Docker docs establish that the CLI reads the profile from the client host and sends it to the daemon before container startup. A focused run of published headless-0.2.1 under Docker default seccomp, with existing cap-drop/no-new-privileges and sandbox intact, exited 134: failed to move to new namespace, Operation not permitted. Automatic --rm removed own yosoi-seccomp-check container. This preserves the existing profile requirement; did not add privileged, unconfined or no-sandbox alternatives. Public setup now explains why the file is host-side and uses readable curl flags. Compose/launcher distribution is a possible packaging improvement, not implemented by this docs edit.
