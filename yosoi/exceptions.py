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

    pass
