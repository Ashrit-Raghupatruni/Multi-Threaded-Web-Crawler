"""
Configuration module for the Multi-Threaded Web Crawler.
Encapsulates all runtime parameters for concurrency, networking, persistence, and reports.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class CrawlerConfig:
    """Configuration settings for the crawler execution."""
    seed_url: Optional[str] = None
    max_workers: int = 4
    max_pages: int = 100
    max_depth: int = 3
    same_domain_only: bool = True
    politeness_delay: float = 0.05       # Delay in seconds between requests per worker
    request_timeout: float = 5.0        # Network socket timeout in seconds
    user_agent: str = "OS-MultiThreadedCrawler/1.0 (+http://os-project.local)"
    db_path: str = "crawler_state.db"
    output_dir: str = "output"          # Directory for generated reports (txt, csv, json)
    resume: bool = False
    headless_ui: bool = False           # If True, suppresses live ANSI dashboard (for tests/logs)
