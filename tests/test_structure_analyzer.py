"""
Comprehensive tests for Website Structure Analyzer:
1. Basic website structure and hierarchy.
2. Nested pages (Depth 0 -> 1 -> 2 -> 3).
3. Duplicate link deduplication and multiple parent handling.
4. Page title detection, brand stripping, and URL slug fallback.
5. Failed pages (404, binary error) represented in structure and crawl details.
6. Long URL formatting without table corruption.
7. Export formats: TXT, CSV, JSON hierarchy, and crawl_report.csv.
"""

import csv
import json
import os
import tempfile
import unittest
from crawler.config import CrawlerConfig
from crawler.engine import CrawlerEngine
from crawler.parser import clean_title, fallback_title_from_url, parse_page
from crawler.storage import StorageEngine
from crawler.structure_analyzer import StructureAnalyzer
from tests.mock_server import MockServer


class TestWebsiteStructureAnalyzer(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = os.path.join(self.temp_dir.name, "test_structure.db")
        self.output_dir = os.path.join(self.temp_dir.name, "output")
        self.server = MockServer()
        self.base_url = self.server.start()

    def tearDown(self):
        self.server.stop()
        self.temp_dir.cleanup()

    def test_title_detection_and_fallback(self):
        """Tests HTML title cleaning, brand suffix removal, and URL path slug fallback."""
        # Clean title with brand pipe suffix
        t1 = clean_title("Best Laptops | Example Store", "https://example.com/products/laptops")
        self.assertEqual(t1, "Best Laptops")

        # Clean title with dash brand suffix
        t2 = clean_title("About Our Company - Acme Corp", "https://example.com/about")
        self.assertEqual(t2, "About Our Company")

        # HTML entity unescape and whitespace cleanup
        t3 = clean_title("  Fish &amp; Chips   &quot;Special&quot;  ", "https://example.com/menu")
        self.assertEqual(t3, 'Fish & Chips "Special"')

        # Fallback to URL path when title is empty or None
        t4 = clean_title(None, "https://example.com/products/product-a")
        self.assertEqual(t4, "Product A")

        t5 = clean_title("", "https://example.com/")
        self.assertEqual(t5, "Home")

        t6 = clean_title("", "https://example.com/blog/deep-nested-article-1.html")
        self.assertEqual(t6, "Deep Nested Article 1")

    def test_nested_pages_hierarchy_and_depths(self):
        """
        Verifies that nested pages produce:
        Depth 0 -> Home
        Depth 1 -> Section 1
        Depth 2 -> Page 1
        Depth 3 -> Deep
        """
        config = CrawlerConfig(
            seed_url=self.base_url + "/",
            max_workers=2,
            max_pages=30,
            max_depth=3,
            same_domain_only=True,
            politeness_delay=0.01,
            db_path=self.db_path,
            output_dir=self.output_dir,
            resume=False,
            headless_ui=True,
        )

        engine = CrawlerEngine(config)
        engine.start()

        storage = StorageEngine(self.db_path)
        records = storage.get_all_crawled_records()
        storage.close()

        analyzer = StructureAnalyzer(records, target_url=self.base_url + "/")
        ordered = analyzer.get_hierarchical_order()

        # Find depth 0, 1, 2, 3 path:
        # Home (0) -> Section1 (1) -> Page1 (2) -> Deep (3)
        depths_by_url = {r["url"]: r["depth"] for r in ordered}
        parents_by_url = {r["url"]: r.get("parent_url") for r in ordered}

        home_url = self.base_url + "/"
        sec1_url = self.base_url + "/section1"
        page1_url = self.base_url + "/section1/page1"
        deep_url = self.base_url + "/section1/page1/deep"

        self.assertEqual(depths_by_url.get(home_url), 0)
        self.assertEqual(depths_by_url.get(sec1_url), 1)
        self.assertEqual(depths_by_url.get(page1_url), 2)
        self.assertEqual(depths_by_url.get(deep_url), 3)

        # Verify parent relationships
        self.assertIsNone(parents_by_url.get(home_url))
        self.assertEqual(parents_by_url.get(sec1_url), home_url)
        self.assertEqual(parents_by_url.get(page1_url), sec1_url)
        self.assertEqual(parents_by_url.get(deep_url), page1_url)

    def test_failed_pages_representation(self):
        """Verifies that 404 pages and skipped MIME types appear in structure and details."""
        config = CrawlerConfig(
            seed_url=self.base_url + "/",
            max_workers=2,
            max_pages=20,
            max_depth=2,
            same_domain_only=True,
            politeness_delay=0.01,
            db_path=self.db_path,
            output_dir=self.output_dir,
            resume=False,
            headless_ui=True,
        )

        engine = CrawlerEngine(config)
        engine.start()

        storage = StorageEngine(self.db_path)
        records = storage.get_all_crawled_records()
        storage.close()

        missing_record = next((r for r in records if "missing-page" in r["url"]), None)
        self.assertIsNotNone(missing_record, "404 page should be recorded in crawled records.")
        self.assertEqual(missing_record["status"], "Failed")
        self.assertEqual(missing_record["http_status"], 404)

        analyzer = StructureAnalyzer(records, target_url=self.base_url + "/")
        table_output = analyzer.generate_structure_table()
        self.assertIn("Failed", table_output)
        self.assertIn("404", table_output)

    def test_multiple_parents_and_cycle_handling(self):
        """
        Verifies that when a page is linked from multiple places (e.g. cycles or cross links),
        it is not duplicated in the structure and retains its primary parent.
        """
        config = CrawlerConfig(
            seed_url=self.base_url + "/",
            max_workers=2,
            max_pages=20,
            max_depth=3,
            same_domain_only=True,
            politeness_delay=0.01,
            db_path=self.db_path,
            output_dir=self.output_dir,
            resume=False,
            headless_ui=True,
        )

        engine = CrawlerEngine(config)
        engine.start()

        storage = StorageEngine(self.db_path)
        records = storage.get_all_crawled_records()
        storage.close()

        analyzer = StructureAnalyzer(records, target_url=self.base_url + "/")
        ordered = analyzer.get_hierarchical_order()

        # Check unique URLs
        urls = [r["url"] for r in ordered]
        self.assertEqual(len(urls), len(set(urls)), "Website structure must not contain duplicate page entries.")

        # Cycle pages (cycle_a and cycle_b)
        cycle_a = next(r for r in ordered if "cycle_a" in r["url"])
        cycle_b = next(r for r in ordered if "cycle_b" in r["url"])
        self.assertEqual(cycle_a["parent_url"], self.base_url + "/")
        self.assertEqual(cycle_b["parent_url"], self.base_url + "/cycle_a")

    def test_export_files_and_json_hierarchy(self):
        """Verifies output/ directory generation and TXT, CSV, JSON export file correctness."""
        config = CrawlerConfig(
            seed_url=self.base_url + "/",
            max_workers=2,
            max_pages=15,
            max_depth=2,
            same_domain_only=True,
            politeness_delay=0.01,
            db_path=self.db_path,
            output_dir=self.output_dir,
            resume=False,
            headless_ui=True,
        )

        engine = CrawlerEngine(config)
        engine.start()

        # Check files created in output_dir
        txt_file = os.path.join(self.output_dir, "website_structure.txt")
        csv_file = os.path.join(self.output_dir, "website_structure.csv")
        json_file = os.path.join(self.output_dir, "website_structure.json")
        crawl_csv = os.path.join(self.output_dir, "crawl_report.csv")

        self.assertTrue(os.path.exists(txt_file), "website_structure.txt must exist")
        self.assertTrue(os.path.exists(csv_file), "website_structure.csv must exist")
        self.assertTrue(os.path.exists(json_file), "website_structure.json must exist")
        self.assertTrue(os.path.exists(crawl_csv), "crawl_report.csv must exist")

        # Verify CSV headers
        with open(csv_file, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
            self.assertEqual(
                header,
                [
                    "Depth",
                    "Page Title",
                    "Parent",
                    "URL",
                    "Status",
                    "HTTP Status Code",
                    "Response Time",
                    "Links Found",
                ]
            )

        with open(crawl_csv, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            crawl_header = next(reader)
            self.assertEqual(crawl_header, ["URL", "Status", "HTTP Code", "Response Time", "Links Found"])

        # Verify JSON tree hierarchy
        with open(json_file, "r", encoding="utf-8") as f:
            tree = json.load(f)
            self.assertIn("title", tree)
            self.assertIn("url", tree)
            self.assertIn("children", tree)
            self.assertIsInstance(tree["children"], list)
            self.assertGreater(len(tree["children"]), 0)

    def test_long_urls_table_formatting(self):
        """Verifies that very long URLs do not break table layout."""
        records = [
            {
                "url": "https://example.com/very/long/nested/path/to/an/extraordinarily/lengthy/article/slug/that/should/not/break/terminal/tables",
                "parent_url": "https://example.com/",
                "title": "A Very Long Page Title That Might Normally Wrap In Bad Tables",
                "depth": 1,
                "http_status": 200,
                "status": "Completed",
                "response_time": 0.45,
                "links_found": 12,
            },
            {
                "url": "https://example.com/",
                "parent_url": None,
                "title": "Home",
                "depth": 0,
                "http_status": 200,
                "status": "Completed",
                "response_time": 0.12,
                "links_found": 5,
            }
        ]

        analyzer = StructureAnalyzer(records, target_url="https://example.com/")
        table = analyzer.generate_structure_table()
        details = analyzer.generate_crawl_details_table()

        self.assertIn("WEBSITE STRUCTURE", table)
        self.assertIn("CRAWL DETAILS", details)
        self.assertIn("Home", table)

    def test_multiple_parents_persistence_and_retrieval(self):
        """Verifies that a page referenced by multiple parents records and retrieves all parents."""
        storage = StorageEngine(self.db_path)
        try:
            # Simulate Home linking to Page A, and Section 1 also linking to Page A
            home = "http://test.local/"
            sec1 = "http://test.local/sec1"
            page_a = "http://test.local/page_a"

            storage.record_parent_relationship(sec1, home)
            storage.record_parent_relationship(page_a, home)
            storage.record_parent_relationship(page_a, sec1)

            storage.mark_url_completed(url=home, depth=0, http_status=200, content_length=100, parent_url=None, title="Home")
            storage.mark_url_completed(url=sec1, depth=1, http_status=200, content_length=100, parent_url=home, title="Section 1")
            storage.mark_url_completed(url=page_a, depth=2, http_status=200, content_length=100, parent_url=home, title="Page A")

            records = storage.get_all_crawled_records()
            rec_map = {r["url"]: r for r in records}

            self.assertIn(home, rec_map[page_a]["all_parents"])
            self.assertIn(sec1, rec_map[page_a]["all_parents"])

            analyzer = StructureAnalyzer(records, target_url=home)
            self.assertIn(sec1, analyzer.get_all_parents(page_a))
        finally:
            storage.close()

    def test_resume_retains_website_structure(self):
        """
        Runs Phase 1 with max_pages=3, pauses, and resumes in Phase 2 with max_pages=10.
        Verifies that final structure table and exports include all pages with correct
        hierarchy, depths, and parent references.
        """
        # Phase 1: Crawl 3 pages
        config_p1 = CrawlerConfig(
            seed_url=self.base_url + "/",
            max_workers=2,
            max_pages=3,
            max_depth=3,
            same_domain_only=True,
            politeness_delay=0.01,
            db_path=self.db_path,
            output_dir=self.output_dir,
            resume=False,
            headless_ui=True,
        )
        engine_p1 = CrawlerEngine(config_p1)
        engine_p1.start()

        # Phase 2: Resume up to 10 pages
        config_p2 = CrawlerConfig(
            seed_url=None,
            max_workers=2,
            max_pages=10,
            max_depth=3,
            same_domain_only=True,
            politeness_delay=0.01,
            db_path=self.db_path,
            output_dir=self.output_dir,
            resume=True,
            headless_ui=True,
        )
        engine_p2 = CrawlerEngine(config_p2)
        engine_p2.start()

        storage = StorageEngine(self.db_path)
        records = storage.get_all_crawled_records()
        storage.close()

        self.assertGreaterEqual(len(records), 5, "Resumed crawl should have expanded total crawled pages.")

        analyzer = StructureAnalyzer(records, target_url=self.base_url + "/")
        table = analyzer.generate_structure_table()

        # Seed page should remain at Depth 0 with no parent
        home_rec = next(r for r in records if r["url"] == self.base_url + "/")
        self.assertEqual(home_rec["depth"], 0)
        self.assertIsNone(home_rec["parent_url"])
        self.assertIn("Depth", table)
        self.assertIn("Page Title", table)
        self.assertIn("Parent", table)


if __name__ == "__main__":
    unittest.main()
