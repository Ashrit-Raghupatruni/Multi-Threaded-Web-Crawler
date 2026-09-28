"""
Worker Thread Implementation.
Implements the concurrent Producer-Consumer worker execution loop.
Demonstrates thread lifecycle, mutex synchronization, condition variable waiting,
page title detection, parent-child relationship tracking, and coordinated task completion.
"""

import threading
from typing import Optional, Tuple

from .config import CrawlerConfig
from .fetcher import PageFetcher
from .parser import clean_title, parse_page
from .storage import StorageEngine
from .sync_primitives import MetricsTracker, ThreadSafeQueue, VisitedRegistry


class WorkerThread(threading.Thread):
    """
    Worker thread that retrieves pending URLs from the shared queue,
    downloads content, extracts page titles and hyperlinks,
    tracks parent-child relationships, and registers new URLs.
    """

    def __init__(
        self,
        worker_id: str,
        config: CrawlerConfig,
        queue: ThreadSafeQueue,
        visited: VisitedRegistry,
        storage: StorageEngine,
        metrics: MetricsTracker,
        stop_event: threading.Event,
    ):
        super().__init__(name=worker_id, daemon=True)
        self.worker_id = worker_id
        self.config = config
        self.queue = queue
        self.visited = visited
        self.storage = storage
        self.metrics = metrics
        self.stop_event = stop_event
        self.fetcher = PageFetcher(
            timeout=config.request_timeout,
            user_agent=config.user_agent,
            politeness_delay=config.politeness_delay,
        )

        self.metrics.register_worker(self.worker_id)

    def run(self) -> None:
        """Main worker execution loop."""
        while not self.stop_event.is_set():
            self.metrics.update_worker_status(self.worker_id, "IDLE")

            # Consumer step: Retrieve task from shared synchronized queue
            # Use small timeout to periodically check stop_event
            task = self.queue.get(timeout=0.5)
            if task is None:
                if self.stop_event.is_set():
                    break
                continue

            # Support both (url, depth) and (url, depth, parent_url)
            if len(task) == 2:
                url, depth = task
                parent_url = None
            else:
                url, depth, parent_url = task

            # Atomically reserve a crawl slot (counting semaphore against max_pages)
            if not self.metrics.try_reserve_page_slot(self.config.max_pages):
                # Max pages limit reached; leave URL in SQLite for future resume
                self.queue.task_done()
                break

            try:
                # Mark as active in persistence store and metrics
                self.storage.mark_url_in_progress(url)
                self.metrics.update_worker_status(self.worker_id, "FETCHING", url, depth)

                # Blocking I/O operation: Network download with response time tracking
                html_content, status_code, content_length, response_time, error_msg = self.fetcher.fetch(url)

                if error_msg or not html_content:
                    page_title = clean_title(None, url)
                    status_str = "Failed"
                    self.storage.mark_url_completed(
                        url=url,
                        depth=depth,
                        http_status=status_code,
                        content_length=content_length,
                        error=error_msg or "Empty response",
                        parent_url=parent_url,
                        title=page_title,
                        status=status_str,
                        response_time=response_time,
                        links_found=0,
                    )
                    self.metrics.record_error(self.worker_id, depth=depth)
                    continue

                # Producer step: Parse HTML for title, internal links, and external links
                self.metrics.update_worker_status(self.worker_id, "PARSING", url, depth)

                page_title, internal_links, external_links = parse_page(html_content, url)
                status_str = "Completed" if status_code < 400 else "Failed"

                new_tasks = []
                # Only crawl deeper if we have not reached max_depth
                if depth < self.config.max_depth:
                    links_to_crawl = internal_links if self.config.same_domain_only else internal_links.union(external_links)

                    for child_url in links_to_crawl:
                        # Atomic Check-Then-Act to eliminate race conditions and track parent
                        if self.visited.check_and_add(child_url, parent_url=url):
                            new_tasks.append((child_url, depth + 1, url))

                    if new_tasks:
                        # Persist newly discovered URLs with parent relationships
                        self.storage.enqueue_frontier_urls(new_tasks)

                        # Enqueue into the shared frontier
                        for task_tuple in new_tasks:
                            self.queue.put(task_tuple)

                total_links_found = len(internal_links) + len(external_links)

                # Mark URL completed in storage and update metrics
                self.storage.mark_url_completed(
                    url=url,
                    depth=depth,
                    http_status=status_code,
                    content_length=content_length,
                    error=None,
                    parent_url=parent_url,
                    title=page_title,
                    status=status_str,
                    response_time=response_time,
                    links_found=total_links_found,
                )
                self.metrics.record_page_success(
                    worker_id=self.worker_id,
                    status_code=status_code,
                    bytes_count=content_length,
                    new_links=len(new_tasks),
                    internal_links=len(internal_links),
                    external_links=len(external_links),
                    depth=depth,
                )

            except Exception as e:
                page_title = clean_title(None, url)
                self.storage.mark_url_completed(
                    url=url,
                    depth=depth,
                    http_status=0,
                    content_length=0,
                    error=f"Worker exception: {str(e)}",
                    parent_url=parent_url,
                    title=page_title,
                    status="Failed",
                    response_time=0.0,
                    links_found=0,
                )
                self.metrics.record_error(self.worker_id, depth=depth)
            finally:
                # Mark task done in queue to decrement unfinished task count
                self.queue.task_done()

        self.metrics.update_worker_status(self.worker_id, "DONE")
