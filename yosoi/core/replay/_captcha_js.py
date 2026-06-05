"""Pure-JS captcha primitives for the deterministic replay hot path (W1).

The replay hot path acquires a ``PooledTab``, which (unlike ``Page``) has NO
``detect_captcha`` / ``capture_captcha`` / ``inject_captcha_token`` binding —
only ``eval_js`` and the ``dispatch_*`` input primitives (see ``voidcrawl/_ext.pyi``).
So the recovery leaves run pure JS through ``eval_js``.

These two constants are a deliberate, narrow port of VoidCrawl's Rust captcha
suite (``crates/core/src/captcha.rs``: ``CAPTURE_JS`` and the ``inject_captcha_token``
template). They are a KNOWN maintenance fork that will drift from the Rust source —
``tests/unit/core/replay/test_captcha_js_shim.py`` pins their shape so drift is loud.

FOLLOW-UP (VoidCrawl wrapper gap, not a blocker): bind ``capture_captcha`` /
``inject_captcha_token`` / ``solve_captcha`` onto ``PooledTab`` (they already take
``&Page``, and ``PooledTab`` wraps a ``Page``) so this shim can be deleted and the
humanized-click geometry (RECT_JS + jitter) is reused rather than re-ported. Until
then the shim stays minimal: detection + token injection only. The actual SOLVE
(humanized click / external solver) is PLANE-B work and never lands here (CAS-87).
"""

from __future__ import annotations

# Detection: classify the wall and pull sitekey / response-field selector /
# widget_rect into one object, or return null when no rendered wall is present.
# ``widget_rendered`` distinguishes a runtime-loaded-but-unmounted Turnstile
# (Ahrefs lazy mount) from a real rendered widget — the trigger must only fire on
# a rendered wall to avoid false-positive recoveries.
CAPTURE_JS = r"""
(function () {
  try {
    const page_url = (typeof location !== 'undefined') ? location.href : '';
    function rectOf(el) {
      if (!el || !el.getBoundingClientRect) return null;
      const r = el.getBoundingClientRect();
      if (r.width < 1 && r.height < 1) return null;
      return { x: r.left, y: r.top, width: r.width, height: r.height };
    }
    function readHidden(sel) {
      const el = document.querySelector(sel);
      if (!el) return '';
      return el.value || el.textContent || '';
    }
    const ts_iframe = document.querySelector('iframe[src*="challenges.cloudflare.com/turnstile"]');
    const ts_container = document.querySelector('.cf-turnstile, [data-sitekey][class*="turnstile" i]');
    const ts_runtime = !!document.querySelector('script[src*="challenges.cloudflare.com/turnstile"]')
                    || (typeof window.turnstile === 'object');
    if (ts_iframe || ts_container || ts_runtime) {
      const sk = document.querySelector('.cf-turnstile[data-sitekey], [data-sitekey]');
      return {
        kind: 'turnstile',
        sitekey: sk ? sk.getAttribute('data-sitekey') : null,
        widget_rect: rectOf(ts_iframe || ts_container),
        widget_rendered: !!(ts_iframe || ts_container),
        response_field_selector: 'input[name="cf-turnstile-response"]',
        existing_token: readHidden('input[name="cf-turnstile-response"], textarea[name="cf-turnstile-response"]'),
        page_url,
      };
    }
    const rc_iframe = document.querySelector('iframe[src*="google.com/recaptcha"], iframe[src*="recaptcha/api2"]');
    const rc_container = document.querySelector('.g-recaptcha, #g-recaptcha');
    if (rc_iframe || rc_container) {
      const sk = document.querySelector('.g-recaptcha[data-sitekey], [data-sitekey]');
      let sitekey = sk ? sk.getAttribute('data-sitekey') : null;
      if (!sitekey && rc_iframe) {
        const m = rc_iframe.src.match(/[?&]k=([^&]+)/);
        if (m) sitekey = decodeURIComponent(m[1]);
      }
      return {
        kind: 'recaptcha',
        sitekey,
        widget_rect: rectOf(rc_iframe || rc_container),
        widget_rendered: true,
        response_field_selector: 'textarea[name="g-recaptcha-response"]',
        existing_token: readHidden('textarea[name="g-recaptcha-response"], #g-recaptcha-response'),
        page_url,
      };
    }
    const hc_iframe = document.querySelector('iframe[src*="hcaptcha.com"]');
    const hc_container = document.querySelector('.h-captcha, [data-hcaptcha-widget-id]');
    if (hc_iframe || hc_container) {
      const sk = document.querySelector('[data-sitekey]');
      let sitekey = sk ? sk.getAttribute('data-sitekey') : null;
      if (!sitekey && hc_iframe) {
        const m = hc_iframe.src.match(/[?&]sitekey=([^&]+)/);
        if (m) sitekey = decodeURIComponent(m[1]);
      }
      return {
        kind: 'hcaptcha',
        sitekey,
        widget_rect: rectOf(hc_iframe || hc_container),
        widget_rendered: true,
        response_field_selector: 'textarea[name="h-captcha-response"]',
        existing_token: readHidden('textarea[name="h-captcha-response"], [name="h-captcha-response"]'),
        page_url,
      };
    }
    return null;
  } catch (e) {
    return null;
  }
})()
"""

# Token injection: write a PRE-RESOLVED token (obtained off the hot path) into the
# response field and fire input/change so the page's widget accepts it. This NEVER
# fetches a token — it only writes one the PLANE-B resolver already produced.
_INJECT_TEMPLATE = r"""
(function (kind, token) {{
  const selectors = {{
    turnstile: ['input[name="cf-turnstile-response"]', 'textarea[name="cf-turnstile-response"]'],
    recaptcha: ['textarea[name="g-recaptcha-response"]', '#g-recaptcha-response'],
    hcaptcha:  ['textarea[name="h-captcha-response"]', '[name="h-captcha-response"]'],
  }};
  const list = selectors[kind] || [];
  let written = 0;
  for (const sel of list) {{
    for (const el of document.querySelectorAll(sel)) {{
      const proto = el.tagName === 'TEXTAREA'
        ? window.HTMLTextAreaElement.prototype
        : window.HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
      setter.call(el, token);
      el.dispatchEvent(new Event('input', {{ bubbles: true }}));
      el.dispatchEvent(new Event('change', {{ bubbles: true }}));
      written += 1;
    }}
  }}
  if (kind === 'turnstile') {{
    const cb = document.querySelector('[data-callback]');
    const fn = cb ? cb.getAttribute('data-callback') : null;
    if (fn && typeof window[fn] === 'function') {{
      try {{ window[fn](token); }} catch (e) {{}}
    }}
  }}
  return written;
}})("{kind}", "{token}")
"""


def _js_string_escape(value: str) -> str:
    r"""Escape a value for pasting into a JS double-quoted string literal.

    Mirrors VoidCrawl's ``inject_captcha_token`` escaping: backslash and double
    quote only, which is sufficient for a JSON-ish token / kind tag.
    """
    return value.replace('\\', '\\\\').replace('"', '\\"')


def inject_token_js(kind: str, token: str) -> str:
    """Build the token-injection script for *kind* with a pre-resolved *token*."""
    return _INJECT_TEMPLATE.format(kind=_js_string_escape(kind), token=_js_string_escape(token))
