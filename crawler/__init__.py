"""
Multi-Threaded Web Crawler Package.
An Operating Systems project demonstrating concurrency, synchronization, persistent state,
and website structure analysis.
"""

from .config import CrawlerConfig
from .engine import CrawlerEngine
from .storage import StorageEngine
from .structure_analyzer import StructureAnalyzer
from .sync_primitives import MetricsTracker, ThreadSafeQueue, VisitedRegistry

__all__ = [
    "CrawlerConfig",
    "CrawlerEngine",
    "ThreadSafeQueue",
    "VisitedRegistry",
    "MetricsTracker",
    "StorageEngine",
    "StructureAnalyzer",
]
