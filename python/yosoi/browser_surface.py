"""Browser-specific Surface facade, also exposed as ``yosoi.browser.surface``."""

from .surface import BrowserObservation as BrowserObservation
from .surface import BrowserRepresentation as BrowserRepresentation
from .surface import BrowserSurface as BrowserSurface
from .surface import consume_session as consume_session

__all__ = [
    "BrowserObservation",
    "BrowserRepresentation",
    "BrowserSurface",
    "consume_session",
]
