"""
Unit Tests for Concurrency and Synchronization Primitives.
Verifies:
1. ThreadSafeQueue correctly handles multi-producer / multi-consumer without item loss.
2. VisitedRegistry atomically prevents check-then-act race conditions across concurrent threads.
3. Queue condition variables correctly signal and terminate threads.
"""

import threading
import time
import unittest
from crawler.sync_primitives import ThreadSafeQueue, VisitedRegistry


class TestSyncPrimitives(unittest.TestCase):

    def test_visited_registry_race_condition(self):
        """
        Tests that multiple threads attempting to register the exact same set
        of URLs simultaneously do not suffer from Check-Then-Act race conditions.
        Exactly one thread should receive True for each unique URL.
        """
        registry = VisitedRegistry()
        num_threads = 20
        urls_to_test = [f"http://example.com/page_{i}" for i in range(100)]
        successful_inserts = []
        lock = threading.Lock()

        def worker():
            local_success = 0
            for url in urls_to_test:
                if registry.check_and_add(url):
                    local_success += 1
            with lock:
                successful_inserts.append(local_success)

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Across all 20 threads, the total number of successful additions must be exactly len(urls_to_test)
        total_unique_added = sum(successful_inserts)
        self.assertEqual(
            total_unique_added,
            len(urls_to_test),
            f"Race condition detected! Expected {len(urls_to_test)} successful adds, got {total_unique_added}"
        )
        self.assertEqual(registry.size(), len(urls_to_test))

    def test_thread_safe_queue_producer_consumer(self):
        """
        Tests multi-producer multi-consumer integrity under high contention.
        Pushes and pops items across multiple worker threads and ensures no items are lost or duplicated.
        """
        queue = ThreadSafeQueue()
        num_producers = 8
        num_consumers = 8
        items_per_producer = 500
        total_items = num_producers * items_per_producer

        consumed_items = []
        consumed_lock = threading.Lock()

        def producer_task(producer_id: int):
            for i in range(items_per_producer):
                item = f"prod-{producer_id}-item-{i}"
                queue.put(item)

        def consumer_task():
            while True:
                item = queue.get(timeout=0.2)
                if item is None:
                    break
                with consumed_lock:
                    consumed_items.append(item)
                queue.task_done()

        # Start consumers first (they block waiting on Condition Variable)
        consumers = [threading.Thread(target=consumer_task) for _ in range(num_consumers)]
        for c in consumers:
            c.start()

        # Start producers
        producers = [threading.Thread(target=producer_task, args=(i,)) for i in range(num_producers)]
        for p in producers:
            p.start()

        for p in producers:
            p.join()

        # Allow consumers to drain the queue
        for _ in range(50):
            if queue.is_empty():
                break
            time.sleep(0.05)

        queue.shutdown()
        for c in consumers:
            c.join()

        # Verify all items were consumed without duplicates
        self.assertEqual(len(consumed_items), total_items)
        self.assertEqual(len(set(consumed_items)), total_items)

    def test_queue_shutdown_unblocks_waiting_threads(self):
        """Tests that broadcast shutdown wakes up threads blocked on empty queue."""
        queue = ThreadSafeQueue()
        thread_exited = threading.Event()

        def waiting_worker():
            # Will block indefinitely until shutdown or put
            item = queue.get(timeout=None)
            self.assertIsNone(item)
            thread_exited.set()

        t = threading.Thread(target=waiting_worker)
        t.start()

        # Give thread time to block on Condition Variable
        time.sleep(0.1)
        self.assertFalse(thread_exited.is_set())

        # Trigger shutdown
        queue.shutdown()
        t.join(timeout=1.0)
        self.assertTrue(thread_exited.is_set())


if __name__ == "__main__":
    unittest.main()
