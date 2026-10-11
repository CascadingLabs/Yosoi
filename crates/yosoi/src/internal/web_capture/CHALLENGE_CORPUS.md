# Browser challenge classification corpus

Yosoi owns the response-signature corpus in
[`browser_challenge/corpus.json`](browser_challenge/corpus.json). The private
browser provider only collects bounded response signals; Web Capture classifies
vendors without turning challenge observations into failures.

The vendor vocabulary and presence-versus-active-challenge split were initially
modeled on `albinstman/antibot-print` (MIT), then reduced to signatures observed
and maintained by Cascading Labs. Patterns use Rust's linear-time `regex`
engine and run only over admitted, bounded header facts and at most 64 KiB of
retained main-document body evidence.

Every corpus edit must:

1. bump `BROWSER_CHALLENGE_CORPUS_VERSION`;
2. add or update a labeled case in `integration_tests/browser_challenge_evaluation.rs`;
3. preserve the distinction between vendor presence and an active challenge;
4. keep supporting facts free of raw header values and response bytes; and
5. run `cargo test -p yosoi --lib internal::web_capture::integration_tests::browser_challenge_evaluation`.

The evaluation gate requires at least 0.95 vendor precision, vendor recall, and
active-challenge accuracy on the held-out deterministic set. Live sites may be
used as passive evidence, but they are not stable acceptance fixtures.
