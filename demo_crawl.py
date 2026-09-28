#!/usr/bin/env python3
"""
Interactive / Self-Contained Demonstration Script.
Launches the local mock server, runs a multi-threaded crawl,
simulates pausing, and demonstrates resuming seamlessly from the SQLite database.
"""

import os
import sys
import time

from crawler.config import CrawlerConfig
from crawler.engine import CrawlerEngine
from crawler.storage import StorageEngine
from tests.mock_server import MockServer


def main():
    print("=================================================================")
    print("  MULTI-THREADED WEB CRAWLER: LIVE OS DEMONSTRATION")
    print("=================================================================")
    print("1. Starting local multi-threaded test HTTP server...")
    server = MockServer()
    base_url = server.start()
    db_file = "demo_crawler_state.db"

    # Remove any existing demo db
    if os.path.exists(db_file):
        try:
            os.remove(db_file)
        except Exception:
            pass

    try:
        print(f"   Mock Web Server running at: {base_url}")
        print("\n2. [PHASE 1] Launching crawl with 4 Worker Threads (Target: 4 pages)...")
        time.sleep(1)

        config_phase1 = CrawlerConfig(
            seed_url=base_url + "/",
            max_workers=4,
            max_pages=4,
            max_depth=3,
            politeness_delay=0.1,
            db_path=db_file,
            resume=False,
            headless_ui=False,
        )

        engine1 = CrawlerEngine(config_phase1)
        engine1.start()

        print("\n3. Phase 1 concluded. Inspecting persisted SQLite database...")
        storage = StorageEngine(db_file)
        crawled, pending = storage.get_stats()
        storage.close()
        print(f"   -> Crawled URLs saved on disk: {crawled}")
        print(f"   -> Pending URLs queued on disk: {pending}")

        print("\n4. [PHASE 2] Resuming crawl from saved SQLite state (Target: 15 pages)...")
        time.sleep(1.5)

        config_phase2 = CrawlerConfig(
            seed_url=None,
            max_workers=4,
            max_pages=15,
            max_depth=3,
            politeness_delay=0.1,
            db_path=db_file,
            resume=True,
            headless_ui=False,
        )

        engine2 = CrawlerEngine(config_phase2)
        engine2.start()

        print("\n5. Crawl completed!")
        storage = StorageEngine(db_file)
        crawled_final, pending_final = storage.get_stats()
        visited = storage.load_visited_urls()
        storage.close()

        print("=================================================================")
        print(f"FINAL PERSISTENCE STATE:")
        print(f"   Total Pages Crawled: {crawled_final}")
        print(f"   Remaining in Queue:  {pending_final}")
        print("   Crawled Paths:")
        for u in sorted(visited):
            print(f"     - {u}")
        print("=================================================================")

    finally:
        server.stop()
        print("Mock server shut down.")


if __name__ == "__main__":
    main()
