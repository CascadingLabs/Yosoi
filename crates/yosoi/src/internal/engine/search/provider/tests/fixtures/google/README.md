# Google captured row

Captured 2026-10-26 through public Yosoi Requests, regular Chrome Stable 155.0.8059.39, headless, sandbox and site isolation enabled. Query: `rust programming language`. HTTP 200; ResponseDocument was a JavaScript retry shell, RenderedDom contained web result cards.

Source SDK example revision c81a25d2c2d6b4e1ec2c5ba7e2ae35008052c9ef; binary SHA-256 a307e1eab9d35e0ecc50f3a343e81b2f074e843f2b5597d994c0efaf0ee25b21. Capture 25c94c31-5ff5-4fc5-97fa-2ba8192c39a3. Raw rendered document SHA-256: `81231851e73a3f8f3ca5d655bb914eefaa0b8547e3cd301c41cca96e31efbd8e`.

This fixture retains one observed `.tF2Cxc` card's element/child/class structure. All other attributes were removed; the direct destination was replaced with `https://example.com/rust`, and text was redacted. It is sanitized captured structure, not proof of relevance or provider-wide reliability. Other cards used opaque `/goto` URLs; no destination may be invented from display text.

The second browser acquisition returned HTTP 429 and an unusual-traffic CAPTCHA; rendered capture ID d9e4eeb4-efe4-4078-8a9e-c4a39f8cba0a, raw DOM SHA-256 `6ea29fca30682d7ff24fcd1f62fe013c994373c13cfe2e2ed0a13b989be2d7a6`. `google-challenge-dom.json` is a minimized sanitized reconstruction retaining the observed form ID and marker text. All IP, query, token, and other content is omitted. HTTP 429 remains rate-limited at the response layer; the parser fixture checks recognition if the same marker appears in a successful-status page.
