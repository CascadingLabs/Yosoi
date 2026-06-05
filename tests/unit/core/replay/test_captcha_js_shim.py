"""Pin the captcha-JS shim's shape so drift from VoidCrawl's Rust source is loud (W1).

The shim (``yosoi/core/replay/_captcha_js.py``) is a deliberate maintenance fork of
``crates/core/src/captcha.rs`` (CAPTURE_JS + inject_captcha_token). These tests do
NOT diff against the Rust file (it lives in a separate repo) — they pin the
*contract* the recovery leaves rely on, so an accidental edit that breaks detection
or token injection fails here instead of silently at replay time.
"""

from __future__ import annotations

from yosoi.core.replay._captcha_js import CAPTURE_JS, inject_token_js


def test_capture_js_classifies_all_three_wall_families():
    for needle in ('turnstile', 'recaptcha', 'hcaptcha'):
        assert needle in CAPTURE_JS


def test_capture_js_distinguishes_rendered_from_runtime_loaded():
    # widget_rendered is the lazy-mount discriminator (Ahrefs Turnstile case).
    assert 'widget_rendered' in CAPTURE_JS
    assert 'widget_rect' in CAPTURE_JS


def test_inject_token_js_escapes_and_embeds_payload():
    js = inject_token_js('recaptcha', 'abc"def\\ghi')
    # kind tag and token are embedded as escaped JS string literals.
    assert '"recaptcha"' in js
    assert '\\"' in js  # the embedded double-quote was escaped
    assert '\\\\' in js  # the embedded backslash was escaped
    # It writes to the response field and fires events (page accepts the token).
    assert 'g-recaptcha-response' in js
    assert "new Event('input'" in js


def test_inject_token_js_handles_each_kind():
    for kind in ('turnstile', 'recaptcha', 'hcaptcha'):
        js = inject_token_js(kind, 'tok')
        assert f'"{kind}"' in js
