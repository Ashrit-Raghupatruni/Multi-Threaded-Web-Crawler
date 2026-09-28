"""
Crawler Engine Orchestrator.
Manages thread pool lifecycle, synchronization primitives, termination detection,
signal handling (Ctrl+C), persistent state recovery, and website structure analysis.
"""

import signal
import sys
import threading
import time
from typing import List, Optional

from .config import CrawlerConfig
from .storage import StorageEngine
from .structure_analyzer import StructureAnalyzer
from .sync_primitives import MetricsTracker, ThreadSafeQueue, VisitedRegistry
from .ui import TerminalDashboard
from .worker import WorkerThread


class CrawlerEngine:
    """
    Coordinates multi-threaded crawl execution, thread pool synchronization,
    state persistence, and post-crawl website structure analysis.
    """

    def __init__(self, config: CrawlerConfig):
        self.config = config
        self.queue = ThreadSafeQueue()
        self.visited = VisitedRegistry()
        self.storage = StorageEngine(config.db_path)
        self.metrics = MetricsTracker()
        self.stop_event = threading.Event()
        self.workers: List[WorkerThread] = []
        self._interrupted = False
        self._start_time = 0.0

        self.ui = (
            TerminalDashboard(
                target_url=config.seed_url or "Resuming Previous Session",
                total_workers=config.max_workers,
                max_pages=config.max_pages,
            )
            if not config.headless_ui
            else None
        )

    def _setup_signal_handler(self) -> None:
        """Configures SIGINT (Ctrl+C) handler for graceful pausing and state save."""
        def sigint_handler(signum, frame):
            sys.stdout.write("\nGracefully pausing crawler... saving execution state to disk.\n")
            sys.stdout.flush()
            self._interrupted = True
            self.stop()

        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, sigint_handler)

    def _initialize_frontier(self) -> None:
        """Prepares frontier queue and visited registry from seed or saved state."""
        if self.config.resume:
            recovered_in_progress = self.storage.reset_in_progress_tasks()
            past_visited = self.storage.load_visited_urls()
            self.visited.add_bulk(past_visited)

            # Hydrate parent-child relationships into memory registry
            all_parents = self.storage.load_all_parents()
            for child_url, p_list in all_parents.items():
                for p in p_list:
                    self.visited.record_parent(child_url, p)

            pending_items = self.storage.load_pending_urls()
            for item in pending_items:
                if len(item) == 2:
                    url, depth = item
                    parent_url = None
                else:
                    url, depth, parent_url = item
                if parent_url:
                    self.visited.record_parent(url, parent_url)
                self.queue.put((url, depth, parent_url))

            crawled_count, pending_count = self.storage.get_stats()
            self.metrics._pages_crawled = crawled_count

            if not pending_items and not past_visited:
                raise ValueError(
                    f"No previous crawl state found in '{self.config.db_path}' to resume from."
                )

            # Try to infer seed URL from root records in storage if config.seed_url is None
            if not self.config.seed_url:
                records = self.storage.get_all_crawled_records()
                if records:
                    self.config.seed_url = records[0]["url"]

            if self.ui and pending_items:
                self.ui.target_url = f"Resumed ({len(past_visited)} visited, {len(pending_items)} pending)"

        else:
            if not self.config.seed_url:
                raise ValueError("seed_url is required for a new crawl session.")

            self.visited.check_and_add(self.config.seed_url, parent_url=None)
            self.storage.enqueue_frontier_urls([(self.config.seed_url, 0, None)])
            self.queue.put((self.config.seed_url, 0, None))

    def start(self) -> None:
        """Starts worker pool and runs the main monitoring loop."""
        self._setup_signal_handler()
        self._initialize_frontier()
        self._start_time = time.time()

        # Spawn worker threads
        for i in range(self.config.max_workers):
            worker_id = f"Worker-{i+1}"
            worker = WorkerThread(
                worker_id=worker_id,
                config=self.config,
                queue=self.queue,
                visited=self.visited,
                storage=self.storage,
                metrics=self.metrics,
                stop_event=self.stop_event,
            )
            self.workers.append(worker)
            worker.start()

        # Coordinator loop
        try:
            while not self.stop_event.is_set():
                qsize = self.queue.qsize()
                snapshot = self.metrics.get_snapshot(queue_size=qsize)

                # Render real-time telemetry dashboard
                if self.ui:
                    self.ui.render(snapshot)

                # Termination condition 1: Page limit reached
                if snapshot.pages_crawled >= self.config.max_pages:
                    break

                # Termination condition 2: Frontier is empty and all workers are idle
                if qsize == 0 and snapshot.active_workers == 0 and self.queue.unfinished_tasks() == 0:
                    time.sleep(0.1)
                    if self.queue.qsize() == 0 and self.queue.unfinished_tasks() == 0:
                        break

                time.sleep(0.05)

        except KeyboardInterrupt:
            self._interrupted = True
        finally:
            self.stop()

    def stop(self) -> None:
        """Coordinates clean termination of all threads, flushes state, and analyzes structure."""
        if self.stop_event.is_set():
            return
        self.stop_event.set()

        # Unblock any workers waiting on queue condition variables
        self.queue.shutdown()

        # Wait for all worker threads to safely finish in-flight requests (Thread joining)
        for worker in self.workers:
            if worker.is_alive():
                worker.join(timeout=2.0)

        # Reset any interrupted in-flight URLs back to QUEUED for next resume
        self.storage.reset_in_progress_tasks()

        # Final UI report
        snapshot = self.metrics.get_snapshot(queue_size=self.queue.qsize())
        if self.ui:
            self.ui.render(snapshot, is_final=True)
            self.ui.print_final_summary(snapshot, paused=self._interrupted)

        # Post-Crawl Website Structure Analysis and Report Generation
        self._analyze_and_report(snapshot)

        # Close database connection
        self.storage.close()

    def _analyze_and_report(self, snapshot) -> None:
        """Runs the Website Structure Analyzer and outputs reports."""
        records = self.storage.get_all_crawled_records()
        if not records:
            return

        target = self.config.seed_url or (records[0]["url"] if records else "Unknown Website")
        analyzer = StructureAnalyzer(records, target_url=target)

        # 1. Print Website Structure Table
        structure_table = analyzer.generate_structure_table()
        print("\n" + structure_table)

        # 2. Print Crawl Details Table
        crawl_details = analyzer.generate_crawl_details_table()
        print("\n" + crawl_details)

        # 3. Print Crawl Summary
        total_discovered = self.visited.size() + self.queue.qsize()
        summary = analyzer.generate_crawl_summary(
            threads_used=self.config.max_workers,
            max_depth_config=self.config.max_depth,
            crawl_time_seconds=snapshot.elapsed_seconds,
            internal_links_total=snapshot.internal_links,
            external_links_total=snapshot.external_links,
            discovered_total=total_discovered,
        )
        print("\n" + summary)

        # 4. Export TXT, CSV, and JSON reports
        exported = analyzer.export_reports(self.config.output_dir)
        print("\n" + "=" * 50)
        print("  REPORTS EXPORTED SUCCESSFULLY")
        print("=" * 50)
        print(f"  • Structure (TXT)  : {exported.get('txt')}")
        print(f"  • Structure (CSV)  : {exported.get('structure_csv')}")
        print(f"  • Structure (JSON) : {exported.get('json')}")
        print(f"  • Crawl Log (CSV)  : {exported.get('crawl_report_csv')}")
        print("=" * 50 + "\n")
