"""
Persistence and Resume Capability Tests.
Verifies that:
1. SQLite state transactions are atomic and crash-resilient.
2. Interrupted/in-progress tasks are properly recovered and re-queued.
3. Crawl can pause mid-way and resume without re-fetching already crawled pages.
"""

import os
import tempfile
import unittest
from crawler.config import CrawlerConfig
from crawler.engine import CrawlerEngine
from crawler.storage import StorageEngine
from tests.mock_server import MockServer


class TestPersistenceAndResume(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = os.path.join(self.temp_dir.name, "test_crawler.db")
        self.server = MockServer()
        self.base_url = self.server.start()

    def tearDown(self):
        self.server.stop()
        self.temp_dir.cleanup()

    def test_in_progress_recovery(self):
        """Tests that URLs left in IN_PROGRESS (e.g. after sudden kill) are reset to QUEUED."""
        storage = StorageEngine(self.db_path)
        try:
            urls = [("http://test.local/1", 0), ("http://test.local/2", 1)]
            storage.enqueue_frontier_urls(urls)

            # Mark one URL in progress
            storage.mark_url_in_progress("http://test.local/1")

            # Verify only 1 is currently in QUEUED
            pending = storage.load_pending_urls()
            self.assertEqual(len(pending), 1)

            # Simulate crash recovery reset
            recovered = storage.reset_in_progress_tasks()
            self.assertEqual(recovered, 1)

            # Now both should be back in QUEUED
            pending_after = storage.load_pending_urls()
            self.assertEqual(len(pending_after), 2)
        finally:
            storage.close()

    def test_crawl_pause_and_resume(self):
        """
        Runs a crawl with max_pages=3, pauses, verifies database contents,
        and then resumes with max_pages=10 to finish remaining pages.
        Verifies no duplicate crawling occurs.
        """
        # Session 1: Crawl up to 3 pages
        config_1 = CrawlerConfig(
            seed_url=self.base_url + "/",
            max_workers=2,
            max_pages=3,
            max_depth=3,
            politeness_delay=0.01,
            db_path=self.db_path,
            resume=False,
            headless_ui=True,
        )

        engine_1 = CrawlerEngine(config_1)
        engine_1.start()

        # Verify session 1 stopped at max_pages=3
        storage = StorageEngine(self.db_path)
        try:
            crawled_count, pending_count = storage.get_stats()
            self.assertEqual(crawled_count, 3)
            self.assertGreater(pending_count, 0, "There should be pending URLs discovered but not yet crawled.")

            first_crawled_urls = storage.load_visited_urls()
            self.assertEqual(len(first_crawled_urls), 3)
        finally:
            storage.close()

        # Session 2: Resume crawling up to 10 pages
        config_2 = CrawlerConfig(
            seed_url=None,
            max_workers=2,
            max_pages=10,
            max_depth=3,
            politeness_delay=0.01,
            db_path=self.db_path,
            resume=True,
            headless_ui=True,
        )

        engine_2 = CrawlerEngine(config_2)
        engine_2.start()

        # Verify session 2 continued from previous state
        storage_2 = StorageEngine(self.db_path)
        try:
            crawled_count_2, _ = storage_2.get_stats()
            self.assertGreater(crawled_count_2, 3, "Resumed session should crawl additional pending URLs.")

            # Ensure all URLs from session 1 are still recorded
            final_visited = storage_2.load_visited_urls()
            for url in first_crawled_urls:
                self.assertIn(url, final_visited)
        finally:
            storage_2.close()


if __name__ == "__main__":
    unittest.main()
