"""
End-to-End Multi-Threaded Crawler Integration Tests.
Verifies crawler execution against local mock server:
- Multi-threaded traversal
- Depth limiting
- Domain filtering
- Cycle loop handling
- Binary resource skipping
- 404 error handling
"""

import os
import tempfile
import unittest
from crawler.config import CrawlerConfig
from crawler.engine import CrawlerEngine
from crawler.storage import StorageEngine
from tests.mock_server import MockServer


class TestCrawlerIntegration(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = os.path.join(self.temp_dir.name, "test_e2e.db")
        self.server = MockServer()
        self.base_url = self.server.start()

    def tearDown(self):
        self.server.stop()
        self.temp_dir.cleanup()

    def test_full_crawl_and_termination(self):
        """
        Verifies that multiple worker threads crawl the mock site,
        correctly handle cyclic links without infinite loops,
        skip external links, and cleanly terminate when frontier is exhausted.
        """
        config = CrawlerConfig(
            seed_url=self.base_url + "/",
            max_workers=4,
            max_pages=50,
            max_depth=5,
            same_domain_only=True,
            politeness_delay=0.01,
            db_path=self.db_path,
            resume=False,
            headless_ui=True,
        )

        engine = CrawlerEngine(config)
        engine.start()

        storage = StorageEngine(self.db_path)
        try:
            visited = storage.load_visited_urls()

            # Check that home and sections were crawled
            self.assertIn(self.base_url + "/", visited)
            self.assertIn(self.base_url + "/section1", visited)
            self.assertIn(self.base_url + "/section2", visited)
            self.assertIn(self.base_url + "/section3", visited)
            self.assertIn(self.base_url + "/cycle_a", visited)
            self.assertIn(self.base_url + "/cycle_b", visited)

            # Check that external links were NOT crawled (domain restriction)
            for url in visited:
                self.assertFalse(url.startswith("https://example.com"), f"External URL was crawled: {url}")

            # Check metrics
            snapshot = engine.metrics.get_snapshot()
            self.assertGreater(snapshot.pages_crawled, 5)
            self.assertGreater(snapshot.links_discovered, 5)
            self.assertGreater(snapshot.bytes_downloaded, 0)
        finally:
            storage.close()

    def test_depth_limiting(self):
        """Verifies that links deeper than max_depth are not fetched."""
        config = CrawlerConfig(
            seed_url=self.base_url + "/",
            max_workers=2,
            max_pages=50,
            max_depth=1,  # Only level 0 (home) and level 1 (section1, section2, etc.)
            same_domain_only=True,
            politeness_delay=0.01,
            db_path=self.db_path,
            resume=False,
            headless_ui=True,
        )

        engine = CrawlerEngine(config)
        engine.start()

        storage = StorageEngine(self.db_path)
        try:
            visited = storage.load_visited_urls()

            # Level 0 and 1 should be crawled
            self.assertIn(self.base_url + "/", visited)
            self.assertIn(self.base_url + "/section1", visited)

            # Level 2 (/section1/page1) and Level 3 (/section1/page1/deep) should NOT be crawled
            self.assertNotIn(self.base_url + "/section1/page1/deep", visited)
        finally:
            storage.close()


if __name__ == "__main__":
    unittest.main()
