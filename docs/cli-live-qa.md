# CLI live URL validation (2026-10-03)

This is focused CLI QA on live public URLs, not promotion of a new Yosoi
browser/controller/CDP compatibility tuple. The complete browser matrix and
monthly decision remain with CAS-376 and
[the Chromium/CDP baseline](chromium-cdp-baseline.md).

## Exact inputs

| Identity | Observed value |
| --- | --- |
| Yosoi source before this report-only edit | JJ `knxtqyxu`, commit `c19338a63671` in the default workspace |
| Dev executable | `target/debug/yosoi`, SHA-256 `11bc528ab8751a6b0e0a5c6fba9b9ba836c056d3466a369c57f59c2d7522a64c` |
| Browser package | Google's regular `google-chrome-stable_154.0.8037.97-1_amd64.deb` |
| Browser package SHA-256 | `a4edbe95e9b01db6c9b97d7a1323121eda18362b5620df06abac1b59bee80053` from Google's Debian Stable package index and verified after download |
| Browser executable SHA-256 | `6c792041b07547a662e1b17974d1dc34a3db630379b45d9d89ddd7e3e68cc587` |
| Controller and generated CDP | vendored Chromiumoxide 0.9.1 with Yosoi's local patches; `chromiumoxide_cdp` `0.10.0-yosoi.m153.1`, schema revision `r1681091` |
| Native host | Linux x86_64, kernel `7.2.5-3-omarchy`, Rust `1.98.0` |
| Headful display | event-ready Xvfb, `1920x1080x24`, executable SHA-256 `567a9b39284e303522fdc178059fe60d0e9917b811bd5066fb63260fd198a97c` |

[Google's October 1 Stable release](https://chromereleases.googleblog.com/2026/10/stable-channel-update-for-desktop.html)
names 154.0.8037.97 for Linux. The package came from Google's regular Debian
Stable repository, not Chrome for Testing. It was extracted under `/tmp` rather
than installed over the host browser. CLI runs set `CHROME` to that verified
executable and `CHROME_NO_SANDBOX=0`; no sandbox-disabling launch option was
requested. The host's older Chromium 152 was not used for these live runs.

## Live CLI results

Each row used the default Policy with one explicit `--acquisition`, a 20-second
attempt bound, and JSON output from the default workspace's dev binary.
Headful runs used the isolated Xvfb display. CLI stderr was empty.

| URL | Direct HTTP | Browser headless | Browser headful |
| --- | --- | --- | --- |
| `https://example.org/` | HTTP 200, produced 577 bytes | HTTP 200, produced 577 bytes | HTTP 200, produced 577 bytes |
| `https://httpbin.org/html` | HTTP 200, produced 3,741 bytes | HTTP 200, produced 3,746 bytes | HTTP 200, produced 3,746 bytes |

For `https://httpbin.org/html`, the isolated merge candidate also passed
Direct HTTP, headless, and headful `request --pipe-document | locate --css h1`
pipelines. Each matched `Herman Melville - Moby-Dick` with both processes
returning zero. The default dev binary repeated the headless typed pipeline
successfully. No extracted Chrome or task-owned Xvfb process remained after
the runs.

The exact browser-enabled merge passed 27 CLI unit tests, 41 CLI process tests,
48 focused Direct HTTP library unit tests, package Clippy with warnings denied,
format/diff checks, and the repository dependency gate. The vendored CDP crate
emitted an existing Clippy MSRV warning; the CLI package passed. Repository-wide
source-size failures outside the CLI and hosted CI remain separate release
gaps. These live examples do not replace full browser security, CDP, cleanup,
isolation, benchmark, or current-Stable promotion certification.

## Flag-free shell stream review

The later default-workspace UX revision `mylykkqm` (`19e1bc2e`) keeps the
browser acquisition behavior above and changes CLI stream routing. Its rebuilt
dev binary SHA-256 is
`cbdc34fe1bf6c3528fc7c4fd5fcd103fd680364c70ade83f53c84f1e779e31d8`.
With no output or input mode flags, a live headless request for
`https://httpbin.org/html` piped into `yosoi locate --css h1` matched
`Herman Melville - Moby-Dick` and both processes exited zero. A Direct HTTP
request redirected with `>` wrote 3,741 raw HTML bytes, starting with
`<!DOCTYPE html>`. An isolated pseudo-terminal run showed the human request
summary. Focused process tests also cover regular-file raw redirection,
flag-free typed piping, raw stdin with `--format`, and explicit-mode overrides.
On Unix this routing uses the stdout descriptor type: arbitrary pipe consumers
receive the typed frame unless `--raw` is specified.

## HTTPS shorthand and request stats review

The isolated CLI revision `qxqwxvvn` (`2b0274e4`) used binary
`/tmp/cas454-target/debug/yosoi`, SHA-256
`dc97bbf5d5dd8d72ac496aeb5dc0fdeca107a40d99ee9f7ba39e816c81dc0b20`.
With the default Policy and `-a http --json --stat`, the scheme-less target
`httpbin.org/html` returned HTTP 200 and a complete 3,741-byte response
Document. With `-a headless --json --stat` and the regular Stable Chrome above,
it returned HTTP 200 and a complete 3,746-byte response Document. The JSON
stdout parsed independently, while stderr contained wall time, termination,
acquisition, HTTP status, and byte count. The flag-free headless
`request httpbin.org/html -a headless -s | locate --css h1 --json` pipeline
matched successfully; the request stats remained on stderr. The complete CLI
package tests and package Clippy with warnings denied passed after the change.
