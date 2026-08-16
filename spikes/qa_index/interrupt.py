"""Interrupts: detect when the page you got is not the page you asked for.

VoidCrawl already owns challenge detection and the operator handoff contract
(docs/challenge-escalation.md): detect_captcha(), AntibotVerdict, attach coordinates,
and a headful container serving noVNC on :6080. This is the QA-side integration, not a
reimplementation.

WHY THIS MATTERS MORE THAN IT LOOKS. Without it, `qa look` on a captcha or a login wall
happily indexes the wall and reports it as the page — a confident, well-formed, entirely
wrong answer. Every downstream number inherits the lie. So the default is to FAIL on an
interrupt, never to return a snapshot of a wall as if it were content.

DETECTION IS DERIVED, NOT ENUMERATED. No list of login-page URLs or captcha vendors
lives here:

  * captcha / antibot — asked of VoidCrawl, which owns that corpus.
  * auth wall — a visible `input[type=password]` is the HTML specification's own marker
    for a credential field. Same class of justification as the `on*` handler prefix:
    a closed rule from the spec, not a guess about a site.
  * redirect — the requested URL and the settled URL differ in origin or path. That is
    computed from what the caller asked for, so it needs no knowledge of any site.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

# Visible credential fields and the form around them. Visibility matters: hidden password
# inputs are common in pages that are not asking anyone to log in.
AUTH_PROBE_JS = """
(() => {
  const vis = (e) => e.getClientRects().length > 0;
  const pw = [...document.querySelectorAll('input[type=password]')].filter(vis);
  if (!pw.length) return null;
  const form = pw[0].closest('form');
  const submit = form
    ? [...form.querySelectorAll('button, input[type=submit]')].map(b => (b.textContent || b.value || '').trim()).filter(Boolean)
    : [];
  return {
    password_inputs: pw.length,
    form_action: form ? (form.getAttribute('action') || '') : null,
    submit_labels: submit.slice(0, 4),
  };
})()
"""


def _diverged(requested: str, final: str) -> bool:
    a, b = urlsplit(requested), urlsplit(final)
    return (a.netloc, a.path.rstrip("/")) != (b.netloc, b.path.rstrip("/"))


async def probe(tab: Any, requested_url: str, *, antibot: Any = None) -> dict | None:
    """Return an interrupt record, or None when the page is genuinely the page."""
    kinds: list[str] = []
    evidence: dict[str, Any] = {}

    captcha = await tab.detect_captcha()
    if captcha:
        kinds.append("captcha")
        evidence["captcha"] = str(captcha)

    if antibot is not None and getattr(antibot, "challenged", False):
        kinds.append("antibot")
        evidence["antibot"] = {
            "vendor": getattr(antibot, "challenge_vendor", None),
            "evidence": getattr(antibot, "evidence", None),
        }

    auth = await tab.eval_js(AUTH_PROBE_JS)
    if auth:
        kinds.append("auth_wall")
        evidence["auth"] = auth

    final_url = await tab.url()
    if final_url and _diverged(requested_url, final_url):
        kinds.append("redirect")
        evidence["redirect"] = {"requested": requested_url, "final": final_url}

    if not kinds:
        return None

    # Attach coordinates let an operator — or a Phase-3 automated resolver — act on THIS
    # tab rather than launching a fresh browser that would not share the session.
    try:
        target_id = await tab.target_id()
    except Exception:  # reported as absent, never silently invented
        target_id = None

    return {"kinds": kinds, "evidence": evidence, "final_url": final_url, "target_id": target_id}


def handoff_text(rec: dict, *, novnc_url: str, vnc_url: str, headful: bool = False) -> str:
    lines = [
        "",
        "═" * 74,
        f"INTERRUPT  {', '.join(rec['kinds'])}",
        "═" * 74,
        f"  requested   {rec['evidence'].get('redirect', {}).get('requested', '(same)')}",
        f"  landed on   {rec['final_url']}",
    ]
    for k, v in rec["evidence"].items():
        lines.append(f"  {k:<11} {v}")
    lines += [""]
    if headful:
        lines += [
            "  A human needs to clear this. The browser is live and attachable:",
            f"    noVNC   {novnc_url}",
            f"    VNC     {vnc_url}",
            f"    target  {rec['target_id']}",
        ]
    else:
        lines += [
            "  This run was HEADLESS, so there is no browser view to hand off to.",
            "  For an operator handoff, start the headful container and re-run with --headful:",
            "    docker compose -f docker/docker-compose.headful.yml up   (in the VoidCrawl checkout)",
            f"    then open {novnc_url}",
            f"    target  {rec['target_id']}",
        ]
    lines += [
        "",
        "  Clear the wall in that view, then re-run to continue.",
        "  Nothing was indexed — a snapshot of a wall is not a snapshot of the page.",
        "═" * 74,
    ]
    return "\n".join(lines)


# The escalation ladder. Each rung gets past more walls and TELLS YOU LESS — that trade
# is the whole point, and it must never be made silently.
#
# VoidCrawl's own docs are explicit about why `normal` is the default: the losses in
# minimal mode "are silent — nothing errors, the data simply never arrives." So every
# rung here states its cost, and escalation is reported, never implicit.
TIERS = [
    {
        "name": "headless",
        "headless": True,
        "cdp_mode": None,
        "gets_past": "nothing special — cheapest and loudest to antibot",
        "loses": "nothing",
    },
    {
        "name": "headful",
        "headless": False,
        "cdp_mode": None,
        "gets_past": "walls that check for headless rendering",
        "loses": "nothing; needs a display or the headful container",
    },
    {
        "name": "stealth",
        "headless": False,
        "cdp_mode": "minimal",
        "gets_past": "Cloudflare Managed Challenge (decided by CDP loudness, not rendering)",
        "loses": (
            "CDP network capture, network-idle waits, evaluate_js_in_frame, OOPIF "
            "auto-attach. Our own network index SURVIVES because it reads Resource "
            "Timing through eval_js rather than Network.enable"
        ),
    },
]


def tier(name: str) -> dict:
    for t in TIERS:
        if t["name"] == name:
            return t
    raise SystemExit(f"unknown tier {name!r}; choose from {[t['name'] for t in TIERS]}")


def tier_banner(t: dict) -> str:
    return f"tier       {t['name']}  (gets past: {t['gets_past']}; loses: {t['loses']})"
