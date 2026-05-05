"""DOM content loader — public interface.

Import DOMLoader and LoadResult from here. Internal modules
(probes, actions, catalogues) are implementation details.
"""

from yosoi.core.fetcher.dom.loader import DOMLoader, LoadResult
from yosoi.core.fetcher.dom.probes import TriggerKind

__all__ = ['DOMLoader', 'LoadResult', 'TriggerKind']
