"""
DOM Extractors Module.
Exports all 4 representations for Experiment 02.
"""

from .base import BaseDOMExtractor
from .raw_html import RawHTMLExtractor
from .axtree import AXTreeExtractor
from .cleaned_markdown import CleanedMarkdownExtractor
from .indexed_json import IndexedJSONExtractor
from .context_aware_json import ContextAwareJSONExtractor

__all__ = [
    "BaseDOMExtractor",
    "RawHTMLExtractor",
    "AXTreeExtractor",
    "CleanedMarkdownExtractor",
    "IndexedJSONExtractor",
    "ContextAwareJSONExtractor"
]
