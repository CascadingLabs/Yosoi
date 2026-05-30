"""Prompt templates and deps for JS action script discovery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

# ---------------------------------------------------------------------------
# Pre-probe eval — collects live DOM context before the LLM call
# ---------------------------------------------------------------------------

PRE_PROBE_JS: Final = """
(() => ({
  script_srcs:  [...document.querySelectorAll('script[src]')].map(e => e.src),
  iframe_srcs:  [...document.querySelectorAll('iframe[src]')].map(e => e.src),
  window_keys:  Object.keys(window).filter(k =>
    /chat|bot|widget|agent|alita|intercom|drift|zendesk|tidio|freshchat|hubspot|ada|tawk|crisp|livechat|liveagent|olark|brevo|chaport|helpcrunch|userlike|gorgias|support|help|message|notify/i.test(k)
  ),
  cookie_names: document.cookie.split(';').map(c => c.trim().split('=')[0]).filter(Boolean),
  meta_names:   [...document.querySelectorAll('meta[name],meta[property]')]
                  .map(e => e.name || e.getAttribute('property')),
}))()
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

### 1 — Script src detection
Field: "is alita-embed.js loaded"
Context: script_srcs contains "https://cdn.alitahealth.ai/alita-embed.js"
JS: (() => [...document.querySelectorAll('script[src]')].some(e => e.src.includes('alita-embed')))()

### 2 — Window global detection
Field: "is Intercom widget initialized"
Context: window_keys contains ["Intercom", "intercomSettings"]
JS: (() => ('Intercom' in window && typeof window.Intercom === 'function'))()

### 3 — iframe attribute extraction
Field: "alita org ID from iframe"
Context: iframe_srcs contains "https://hub.alitahealth.ai/agent/?uuid=abc&org=xyz"
JS: (() => { const f = document.querySelector('iframe[src*="hub.alitahealth.ai"]'); return f ? new URL(f.src).searchParams.get('org') : null; })()

### 4 — DOM presence and visibility
Field: "is chat widget visible"
Context: window_keys contains ["$zopim", "zE"]
JS: (() => { const el = document.querySelector('#chat-widget,[data-widget="chat"],.zopim'); return !!el && el.offsetParent !== null; })()

### 5 — Performance resource list
Field: "third-party script URLs loaded at runtime"
Context: window_keys contains ["ga", "gtag"]
JS: (() => performance.getEntriesByType('resource').filter(e => e.initiatorType === 'script').map(e => e.name))()

### 6 — Structured data extraction
Field: "structured data type from JSON-LD"
Context: page has <script type="application/ld+json">
JS: (() => { try { const s = document.querySelector('script[type="application/ld+json"]'); return s ? JSON.parse(s.textContent)['@type'] : null; } catch(e) { return null; } })()

### 7 — Competitor detection returning names
Field: "competitor chat widgets present"
Context: script_srcs contains "https://widget.intercom.io/widget/abc"
JS: (() => { const srcs = [...document.querySelectorAll('script[src],iframe[src]')].map(e=>e.src||e.getAttribute('src')||''); const found=[]; if(srcs.some(s=>s.includes('intercom'))) found.push('Intercom'); if(srcs.some(s=>s.includes('drift.com'))) found.push('Drift'); if(srcs.some(s=>s.includes('zendesk'))) found.push('Zendesk'); return found; })()
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
