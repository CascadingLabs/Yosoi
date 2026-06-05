"""Custom exceptions for Yosoi."""


class YosoiError(Exception):
    """Base class for all Yosoi exceptions."""

    pass


class BotDetectionError(YosoiError):
    """Raised when bot detection is triggered.

    Block attribution (W2): the optional ``identity_id`` and ``captcha_kind``
    kwargs let the profile-cascade attribute a block to the *identity* that
    earned it (which profile / proxy / fingerprint), so rotation has something
    to rotate on. These are intentionally distinct signals:

    * ``indicators`` — the HTML-marker heuristic (a 200 response whose body
      carries Cloudflare / captcha markers). A *soft* block.
    * ``captcha_kind`` — the result of a live DOM captcha probe
      (``Page.detect_captcha``). May be ``None`` even on a marker-triggered
      block, in which case the block is "soft-marker, no named captcha" — its
      own attribution bucket. Never conflate the two.
    """

    def __init__(
        self,
        url: str,
        status_code: int,
        indicators: list[str],
        identity_id: str | None = None,
        captcha_kind: str | None = None,
    ):
        """Initialize bot detection error.

        Args:
            url: URL where bot detection was triggered
            status_code: HTTP status code received
            indicators: List of bot detection indicators found (HTML-marker heuristic)
            identity_id: Optional id of the browser identity (profile/proxy) that
                was blocked. ``None`` when the block is not identity-attributed.
            captcha_kind: Optional captcha kind from a live DOM probe
                (``Page.detect_captcha``). ``None`` when no named captcha was
                detected — distinct from the marker heuristic in ``indicators``.

        """
        self.url = url
        self.status_code = status_code
        self.indicators = indicators
        self.identity_id = identity_id
        self.captcha_kind = captcha_kind
        suffix = ''
        if identity_id is not None:
            suffix += f' [identity={identity_id}]'
        if captcha_kind is not None:
            suffix += f' [captcha={captcha_kind}]'
        super().__init__(f'Bot detection triggered on {url} (status={status_code}): {", ".join(indicators)}{suffix}')


class LLMGenerationError(YosoiError):
    """Raised when LLM generation fails."""

    pass


class DownloadError(YosoiError):
    """Raised when a ``ys.File`` download fails or is rejected.

    Fail-fast (per the project's no-fallback stance): a download that times out,
    exceeds ``max_bytes``, targets an unsafe URL, or whose bytes don't match the
    field's ``allowed_types`` raises this rather than yielding an untrusted/partial
    value. The quarantined bytes are purged before raising on a type mismatch.
    """

    def __init__(self, field: str, reason: str):
        """Initialize with the offending field name and a human-readable reason."""
        self.field = field
        self.reason = reason
        super().__init__(f'download failed for field {field!r}: {reason}')


class MCPUnavailableError(YosoiError):
    """Raised when MCP discovery is requested but the MCP server cannot be reached.

    Honors ``DiscoveryConfig.mcp_unavailable='fail'`` — Yosoi's fail-fast stance.
    We do not silently fall back to static discovery, because that would hide a
    misconfigured environment behind a slower, blind discovery path.
    """

    pass


class SelectorError(YosoiError):
    """Raised when selector operations fail."""

    def __init__(
        self,
        field_name: str,
        selectors_tried: list[tuple[str, str]],
        failure_reasons: list[tuple[str, str]],
    ):
        """Initialize selector error with detailed failure info.

        Args:
            field_name: Name of the field whose selectors failed
            selectors_tried: List of (level, selector) tuples that were attempted
            failure_reasons: List of (level, reason) tuples explaining failures

        """
        self.field_name = field_name
        self.selectors_tried = selectors_tried
        self.failure_reasons = failure_reasons

        reasons_str = ', '.join(f'{level}: {reason}' for level, reason in failure_reasons)
        super().__init__(f"Selector verification failed for '{field_name}': {reasons_str}")
