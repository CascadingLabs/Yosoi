# CAS-383 OOPIF profile

Primary evidence is the hardened container run against regular Stable Google
Chrome 154.0.8037.57. The image is `sha256:355aa95235603948f766f946efbfc4f4f2a54c923d161abdb7adca4d34596537`,
the browser package SHA-256 is
`66c0645f6a19871bab2844b8537c11a0db2e7d3bea8ef85a1c7cb52a54e65a3e`,
and the executable SHA-256 is
`4d2512ae84986bf987e6ea8ef14ca1af555ae574fbaff5b5a8c78a8dd73fa36f`.
The run used JJ change `qrxtrrxwtvrk`, snapshot `67de9e6139ed`, source SHA-256
`33a8692fe2eb0cee66ab3e32dd9585e1c76b0360a09534c4690ae086abaf2937`,
Chromiumoxide source SHA-256
`8a8676968808b1190ed3b2cf72012889119d54bebf75bb2aae321c9137b26b6b`,
and generated CDP revision `r1681091`.

The container ran rootless, networkless, read-only, capability-dropped,
no-new-privileges, seccomp-confined, and with the Chrome sandbox and default
site isolation enabled. Setup, image build, browser launch, and fixture
readiness are excluded from operation latency.

Each case completed 10 warm-up iterations followed by 100 measured iterations:

| Case | Operation | p50 | p95 | max |
| --- | --- | ---: | ---: | ---: |
| Same-origin | evaluate | 244 us | 366 us | 538 us |
| OOPIF | evaluate | 253 us | 333 us | 425 us |
| Same-origin | accessibility | 1,122 us | 1,763 us | 1,972 us |
| OOPIF | accessibility | 1,287 us | 1,656 us | 1,729 us |
| Same-origin | geometry | 1,036 us | 1,615 us | 1,667 us |
| OOPIF | geometry | 1,104 us | 1,449 us | 20,903 us |

All 600 measured operations succeeded. The same run also passed nested-frame
evaluation, trusted OOPIF input, cross-site to same-site to cross-site process
swaps, and same-document navigation. These distributions are descriptive;
they do not establish a causal performance improvement or regression.
`chrome-154-container-profile.jsonl` retains every sample and exact identity.

`chromium-152-profile.jsonl` is the earlier native rollback-browser comparison.
It is retained for diagnosis only and is not the acceptance or promotion run.
