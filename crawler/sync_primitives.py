"""
Operating Systems Synchronization Primitives for Web Crawler.
Demonstrates:
- Mutual Exclusion (Mutex Locks)
- Condition Variables (wait, notify, notify_all)
- Thread-safe Producer-Consumer Bounded / Unbounded Queue
- Atomic Check-and-Set Visited Registry with Parent-Child Hierarchy Tracking
- Counting Semaphore / Atomic Page Slot Reservation
- Thread-safe Metrics and Worker State Tracking
"""

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


class ThreadSafeQueue:
    """
    A custom synchronized queue implemented using raw OS primitives:
    - Mutex (threading.Lock)
    - Condition Variable (threading.Condition)

    Demonstrates the classic Producer-Consumer synchronization problem.
    Worker threads act as both consumers (dequeueing URLs) and producers
    (enqueueing newly extracted child links).
    """

    def __init__(self, maxsize: int = 0):
        self._maxsize = maxsize
        self._queue: deque = deque()
        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)
        self._not_full = threading.Condition(self._lock)
        self._all_tasks_done = threading.Condition(self._lock)
        self._unfinished_tasks = 0
        self._shutdown = False

    def put(self, item: Any, block: bool = True, timeout: Optional[float] = None) -> bool:
        """
        Producer operation: Inserts an item into the queue.
        Blocks if bounded queue is full. Notifies waiting consumers.
        """
        with self._lock:
            if self._shutdown:
                return False

            if self._maxsize > 0:
                end_time = time.monotonic() + timeout if timeout else None
                while len(self._queue) >= self._maxsize:
                    if self._shutdown:
                        return False
                    if not block:
                        return False
                    if timeout is not None:
                        remaining = end_time - time.monotonic()
                        if remaining <= 0:
                            return False
                        self._not_full.wait(remaining)
                    else:
                        self._not_full.wait()

            self._queue.append(item)
            self._unfinished_tasks += 1
            # Signal waiting consumer threads that a new task is available
            self._not_empty.notify()
            return True

    def get(self, timeout: Optional[float] = None) -> Optional[Any]:
        """
        Consumer operation: Retrieves and removes an item from the queue.
        Blocks while queue is empty, waiting on Condition Variable.
        Returns None if queue is shutdown or on timeout.
        """
        with self._lock:
            end_time = time.monotonic() + timeout if timeout else None
            while not self._queue and not self._shutdown:
                if timeout is not None:
                    remaining = end_time - time.monotonic()
                    if remaining <= 0:
                        return None
                    self._not_empty.wait(remaining)
                else:
                    self._not_empty.wait()

            if self._queue:
                item = self._queue.popleft()
                # Signal waiting producers that space is now available
                self._not_full.notify()
                return item
            return None

    def task_done(self) -> None:
        """
        Signals that a previously dequeued task is complete.
        When unfinished tasks drop to zero, notifies any waiting joiners.
        """
        with self._lock:
            unfinished = self._unfinished_tasks - 1
            if unfinished < 0:
                raise ValueError("task_done() called too many times")
            if unfinished == 0:
                self._all_tasks_done.notify_all()
            self._unfinished_tasks = unfinished

    def qsize(self) -> int:
        """Returns the immediate number of items currently in the queue."""
        with self._lock:
            return len(self._queue)

    def unfinished_tasks(self) -> int:
        """Returns total tasks in-flight + in-queue."""
        with self._lock:
            return self._unfinished_tasks

    def is_empty(self) -> bool:
        """Returns True if the queue currently has no pending items."""
        with self._lock:
            return len(self._queue) == 0

    def shutdown(self) -> None:
        """
        Broadcasts shutdown to all worker threads waiting on condition variables.
        """
        with self._lock:
            self._shutdown = True
            # Wake up all waiting consumer and producer threads
            self._not_empty.notify_all()
            self._not_full.notify_all()
            self._all_tasks_done.notify_all()


class VisitedRegistry:
    """
    Thread-safe registry for keeping track of visited URLs and their parent relationships.

    Addresses the 'Check-Then-Act' race condition:
    In a multithreaded crawler, two threads must not inspect a URL, both conclude
    it has not been visited, and both proceed to crawl it. The check and insertion
    must be executed as a single atomic critical section.

    Also tracks primary parent URL and multiple parent references thread-safely.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._visited: Set[str] = set()
        self._parent_map: Dict[str, Optional[str]] = {}
        self._all_parents: Dict[str, List[str]] = {}

    def check_and_add(self, url: str, parent_url: Optional[str] = None) -> bool:
        """
        Atomically checks if a URL is already registered.
        If not present, adds it to the registry, records primary parent, and returns True.
        If already present, records the additional referencing parent and returns False.
        """
        with self._lock:
            if url in self._visited:
                if parent_url:
                    parents_list = self._all_parents.setdefault(url, [])
                    if parent_url not in parents_list:
                        parents_list.append(parent_url)
                return False

            self._visited.add(url)
            self._parent_map[url] = parent_url
            self._all_parents[url] = [parent_url] if parent_url else []
            return True

    def contains(self, url: str) -> bool:
        """Thread-safe membership test."""
        with self._lock:
            return url in self._visited

    def add_bulk(self, urls: Set[str]) -> None:
        """Populates the visited set in bulk (used when resuming from database)."""
        with self._lock:
            self._visited.update(urls)

    def size(self) -> int:
        """Returns current count of visited URLs."""
        with self._lock:
            return len(self._visited)

    def get_all(self) -> Set[str]:
        """Returns a copy of all visited URLs."""
        with self._lock:
            return set(self._visited)

    def record_parent(self, url: str, parent_url: Optional[str]) -> None:
        """Thread-safely records an additional parent reference for an existing URL."""
        if not parent_url:
            return
        with self._lock:
            if url not in self._parent_map:
                self._parent_map[url] = parent_url
            parents_list = self._all_parents.setdefault(url, [])
            if parent_url not in parents_list:
                parents_list.append(parent_url)

    def get_parent(self, url: str) -> Optional[str]:
        """Returns the primary parent URL for the specified URL."""
        with self._lock:
            return self._parent_map.get(url)

    def get_all_parents(self, url: str) -> List[str]:
        """Returns all parent URLs that linked to the specified URL."""
        with self._lock:
            return list(self._all_parents.get(url, []))


@dataclass
class WorkerStateSnapshot:
    worker_id: str
    status: str       # "IDLE", "FETCHING", "PARSING", "WAITING", "DONE"
    current_url: str = "-"
    depth: int = 0
    pages_processed: int = 0


@dataclass
class MetricsSnapshot:
    start_time: float
    elapsed_seconds: float
    pages_crawled: int
    bytes_downloaded: int
    links_discovered: int
    internal_links: int
    external_links: int
    max_depth_reached: int
    errors_count: int
    queue_size: int
    active_workers: int
    crawl_rate: float
    status_codes: Dict[int, int]
    workers: Dict[str, WorkerStateSnapshot]


class MetricsTracker:
    """
    Thread-safe metrics accumulator and per-worker telemetry reporter.
    Provides snapshot capabilities for the real-time UI without holding locks.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._start_time = time.time()
        self._pages_crawled = 0
        self._reserved_slots = 0
        self._bytes_downloaded = 0
        self._links_discovered = 0
        self._internal_links = 0
        self._external_links = 0
        self._max_depth_reached = 0
        self._errors_count = 0
        self._status_codes: Dict[int, int] = {}
        self._workers: Dict[str, WorkerStateSnapshot] = {}

    def try_reserve_page_slot(self, max_pages: int) -> bool:
        """
        Atomically checks if pages_crawled + reserved_slots < max_pages.
        If yes, reserves a slot and returns True. Otherwise returns False.
        Acts as a counting semaphore preventing worker overshoot.
        """
        with self._lock:
            if (self._pages_crawled + self._reserved_slots) < max_pages:
                self._reserved_slots += 1
                return True
            return False

    def release_reserved_slot(self) -> None:
        """Releases a reserved slot without counting it as completed."""
        with self._lock:
            if self._reserved_slots > 0:
                self._reserved_slots -= 1

    def register_worker(self, worker_id: str) -> None:
        with self._lock:
            self._workers[worker_id] = WorkerStateSnapshot(
                worker_id=worker_id,
                status="IDLE"
            )

    def update_worker_status(self, worker_id: str, status: str, url: str = "-", depth: int = 0) -> None:
        with self._lock:
            if worker_id in self._workers:
                w = self._workers[worker_id]
                w.status = status
                w.current_url = url
                w.depth = depth

    def record_page_success(
        self,
        worker_id: str,
        status_code: int,
        bytes_count: int,
        new_links: int,
        internal_links: int = 0,
        external_links: int = 0,
        depth: int = 0
    ) -> None:
        with self._lock:
            if self._reserved_slots > 0:
                self._reserved_slots -= 1
            self._pages_crawled += 1
            self._bytes_downloaded += bytes_count
            self._links_discovered += new_links
            self._internal_links += internal_links
            self._external_links += external_links
            self._max_depth_reached = max(self._max_depth_reached, depth)
            self._status_codes[status_code] = self._status_codes.get(status_code, 0) + 1
            if worker_id in self._workers:
                self._workers[worker_id].pages_processed += 1

    def record_error(self, worker_id: str, depth: int = 0) -> None:
        with self._lock:
            if self._reserved_slots > 0:
                self._reserved_slots -= 1
            self._pages_crawled += 1
            self._errors_count += 1
            self._max_depth_reached = max(self._max_depth_reached, depth)
            if worker_id in self._workers:
                self._workers[worker_id].pages_processed += 1

    def get_snapshot(self, queue_size: int = 0) -> MetricsSnapshot:
        with self._lock:
            now = time.time()
            elapsed = max(0.001, now - self._start_time)
            rate = self._pages_crawled / elapsed

            active_workers = sum(1 for w in self._workers.values() if w.status not in ("IDLE", "DONE", "WAITING"))

            # Deep-copy worker states
            workers_copy = {
                wid: WorkerStateSnapshot(
                    worker_id=w.worker_id,
                    status=w.status,
                    current_url=w.current_url,
                    depth=w.depth,
                    pages_processed=w.pages_processed
                )
                for wid, w in self._workers.items()
            }

            return MetricsSnapshot(
                start_time=self._start_time,
                elapsed_seconds=elapsed,
                pages_crawled=self._pages_crawled,
                bytes_downloaded=self._bytes_downloaded,
                links_discovered=self._links_discovered,
                internal_links=self._internal_links,
                external_links=self._external_links,
                max_depth_reached=self._max_depth_reached,
                errors_count=self._errors_count,
                queue_size=queue_size,
                active_workers=active_workers,
                crawl_rate=rate,
                status_codes=dict(self._status_codes),
                workers=workers_copy
            )
