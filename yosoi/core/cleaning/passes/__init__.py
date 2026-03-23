"""Composable HTML cleaning passes.

Each pass is a function ``BeautifulSoup -> BeautifulSoup`` that mutates
the tree in-place and returns the same object.
"""

from yosoi.core.cleaning.passes.budget import enforce_budget
from yosoi.core.cleaning.passes.classes import strip_utility_classes
from yosoi.core.cleaning.passes.compress import compress_html
from yosoi.core.cleaning.passes.content import extract_content
from yosoi.core.cleaning.passes.dedup import deduplicate_siblings
from yosoi.core.cleaning.passes.density import prune_by_density
from yosoi.core.cleaning.passes.flatten import flatten_wrappers
from yosoi.core.cleaning.passes.noise import remove_noise

__all__ = [
    'compress_html',
    'deduplicate_siblings',
    'enforce_budget',
    'extract_content',
    'flatten_wrappers',
    'prune_by_density',
    'remove_noise',
    'strip_utility_classes',
]
