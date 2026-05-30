"""Prompt templates and deps for JS action script discovery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

# ---------------------------------------------------------------------------
# Pre-probe eval — collects live DOM context before the LLM call
# ---------------------------------------------------------------------------

PRE_PROBE_JS: Final = """
(() => {
  // Non-standard window globals: strip built-in browser APIs so the LLM sees
  // only third-party injections.  No vendor allowlist — the LLM already knows
  // what Intercom, $zopim, __alita__, tawk_API, drift, etc. are.
  const _builtinRe = /^(on[a-z]|webkit|moz|ms[A-Z]|_|document|window|location|navigator|history|screen|performance|crypto|indexedDB|sessionStorage|localStorage|caches|console|fetch|alert|atob|btoa|blur|close|confirm|focus|open|print|prompt|scroll|stop|clearTimeout|clearInterval|setTimeout|setInterval|requestAnimationFrame|cancelAnimationFrame|queueMicrotask|structuredClone|postMessage|getComputedStyle|getSelection|matchMedia|createImageBitmap|addEventListener|removeEventListener|dispatchEvent)$/;
  const window_keys = Object.keys(window).filter(k => !_builtinRe.test(k));
  return {
    script_srcs:  [...document.querySelectorAll('script[src]')].map(e => e.src),
    iframe_srcs:  [...document.querySelectorAll('iframe[src]')].map(e => e.src),
    window_keys,
    cookie_names: document.cookie.split(';').map(c => c.trim().split('=')[0]).filter(Boolean),
    meta_names:   [...document.querySelectorAll('meta[name],meta[property]')]
                    .map(e => e.name || e.getAttribute('property')),
  };
})()
""".strip()

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_BASE: Final = """\
You are a JavaScript extraction expert for web scraping pipelines.
Your task is to write a single JavaScript IIFE (Immediately Invoked Function Expression)
that extracts a specific piece of data from a web page's live DOM.

Rules:
- Return ONLY the JS expression — no markdown, no explanation, no code fences.
- The expression must be a self-contained IIFE: (() => { ... })()
- It must return a JSON-serialisable value (string, number, boolean, array, or plain object).
- Return null if the data is not present on this page.
- Never throw — use try/catch internally if needed.
- Do not use async/await — the expression is evaluated synchronously.
- Target the live rendered DOM, not static HTML attributes alone.
"""

_PATTERNS: Final = """\
## Canonical extraction patterns (few-shot examples)

These examples teach the *shape* of each technique, not which vendors to look
for. Read the field name + live DOM context, then pick the matching shape and
fill it with the actual values you see in the context — do not copy the
placeholder names or hosts below.

### 1 — Script src detection
Field: "is <some library> loaded"
Context: script_srcs contains a URL ending in "<name>.js"
JS: (() => [...document.querySelectorAll('script[src]')].some(e => e.src.includes('<name>')))()

### 2 — Window global detection
Field: "is <some widget> initialized"
Context: window_keys contains "<GlobalName>"
JS: (() => ('<GlobalName>' in window && typeof window['<GlobalName>'] === 'function'))()

### 3 — iframe attribute / URL-param extraction
Field: "<param> from embedded iframe"
Context: iframe_srcs contains a URL like "https://host.example.com/embed?<param>=xyz"
JS: (() => { const f = document.querySelector('iframe[src*="host.example.com"]'); return f ? new URL(f.src).searchParams.get('<param>') : null; })()

### 4 — DOM presence and visibility
Field: "is <some element> visible"
Context: a candidate selector for it (derive the selector from the live DOM)
JS: (() => { const el = document.querySelector('<selector>'); return !!el && el.offsetParent !== null; })()

### 5 — Performance resource list
Field: "third-party script URLs loaded at runtime"
JS: (() => performance.getEntriesByType('resource').filter(e => e.initiatorType === 'script').map(e => e.name))()

### 6 — Structured data extraction
Field: "structured data type from JSON-LD"
Context: page has <script type="application/ld+json">
JS: (() => { try { const s = document.querySelector('script[type="application/ld+json"]'); return s ? JSON.parse(s.textContent)['@type'] : null; } catch(e) { return null; } })()

### 7 — Enumerate matches by host, returning names
Field: "which third-party <category> are present"
Context: script_srcs / iframe_srcs contain several third-party URLs
JS: (() => { const srcs = [...document.querySelectorAll('script[src],iframe[src]')].map(e=>e.src||e.getAttribute('src')||''); const host = u => { try { return new URL(u).hostname.replace(/^www\\.|\\.(com|net|io|ai|co)$/g,''); } catch(e) { return ''; } }; return [...new Set(srcs.map(host).filter(Boolean))]; })()
"""

_ITERATION_NOTE: Final = """\
## Iteration context
If a previous attempt is shown below, the script ran but the result was wrong or null.
Analyse the failure and write an improved version. Common fixes:
- Use a broader or different selector
- Check window globals directly instead of script src
- Try performance.getEntriesByType('resource') for dynamically loaded scripts
- Wrap risky operations in try/catch returning null
"""

SYSTEM_PROMPT: Final = f'{_BASE}\n\n{_PATTERNS}'

# ---------------------------------------------------------------------------
# Deps dataclass — injected per LLM run
# ---------------------------------------------------------------------------


@dataclass
class JsDiscoveryDeps:
    """Per-field context injected into the JS discovery LLM agent."""

    field_name: str
    field_description: str
    dom_context: dict[str, Any]
    previous_attempt: str | None = None
    previous_result: str | None = None


def build_user_prompt(deps: JsDiscoveryDeps) -> str:
    """Build the user-turn message for one JS discovery attempt."""
    ctx = deps.dom_context
    lines = [
        f'Field name: {deps.field_name}',
        f'Field description: {deps.field_description}',
        '',
        '## Live DOM context (from pre-probe eval)',
        f'script_srcs:  {ctx.get("script_srcs", [])}',
        f'iframe_srcs:  {ctx.get("iframe_srcs", [])}',
        f'window_keys:  {ctx.get("window_keys", [])}',
        f'cookie_names: {ctx.get("cookie_names", [])}',
        f'meta_names:   {ctx.get("meta_names", [])}',
    ]
    if deps.previous_attempt:
        lines += [
            '',
            '## Previous attempt (failed or returned null — write a better version)',
            f'Script tried: {deps.previous_attempt}',
            f'Result:       {deps.previous_result or "null / undefined"}',
            '',
            _ITERATION_NOTE,
        ]
    lines += ['', 'Write the JS IIFE for this field:']
    return '\n'.join(lines)
