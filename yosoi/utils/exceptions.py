"""Custom exceptions for Yosoi."""


class YosoiError(Exception):
    """Base class for all Yosoi exceptions."""

    pass


class BotDetectionError(YosoiError):
    """Raised when bot detection is triggered."""

    def __init__(self, url: str, status_code: int, indicators: list[str]):
        """Initialize bot detection error.

        Args:
            url: URL where bot detection was triggered
            status_code: HTTP status code received
            indicators: List of bot detection indicators found

        """
        self.url = url
        self.status_code = status_code
        self.indicators = indicators
        super().__init__(f'Bot detection triggered on {url} (status={status_code}): {", ".join(indicators)}')


class LLMGenerationError(YosoiError):
    """Raised when LLM generation fails."""

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
