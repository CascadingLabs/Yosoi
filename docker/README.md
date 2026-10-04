# Local Docker profiles

| Directory | Purpose | Build entry point |
| --- | --- | --- |
| `browser/` | Hardened browser benchmarks and frame-isolation checks | `scripts/browser/run-container.sh` |
| `browser-stealth/` | Browser stealth measurements on the reviewed browser image | `scripts/browser/run-cas-374-browser-stealth.sh` |

The runners prepare a source context with a `YosoiOxide/` directory and verify
the expected local runtime image. These are local validation profiles; use the
runners rather than building a Dockerfile directly from the repository root.
Browser versions, sandbox rules, image labels and evidence formats retain their
existing identities. Context preparation excludes local recovery and generated
output directories.
