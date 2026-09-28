"""
Persistent State Storage Engine.
Uses SQLite with Write-Ahead Logging (WAL) for atomic, crash-resilient persistence.
Tracks URL hierarchy (parent -> child), titles, HTTP status, and crawl telemetry.
Enables pausing, interrupting (Ctrl+C), and seamlessly resuming crawl progress.
"""

import os
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple


class StorageEngine:
    """
    Manages persistent state on disk using SQLite.
    Guarantees thread-safe database operations via an internal Mutex Lock.
    """

    def __init__(self, db_path: str = "crawler_state.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        """Initializes tables, indexes, and applies automatic schema migrations."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                # Table for fully processed URLs with hierarchy and title metadata
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS crawled_urls (
                        url TEXT PRIMARY KEY,
                        parent_url TEXT,
                        title TEXT,
                        depth INTEGER,
                        http_status INTEGER,
                        status TEXT DEFAULT 'Completed',
                        response_time REAL DEFAULT 0.0,
                        links_found INTEGER DEFAULT 0,
                        content_length INTEGER,
                        crawled_at REAL,
                        error TEXT
                    );
                """)

                # Table for pending frontier URLs with parent reference
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS pending_frontier (
                        url TEXT PRIMARY KEY,
                        parent_url TEXT,
                        depth INTEGER,
                        status TEXT DEFAULT 'QUEUED',
                        discovered_at REAL
                    );
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_pending_status
                    ON pending_frontier (status, depth, discovered_at);
                """)

                # Table for tracking all parent-child link relationships (multiple parents)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS page_parents (
                        child_url TEXT,
                        parent_url TEXT,
                        PRIMARY KEY (child_url, parent_url)
                    );
                """)

                # Schema migration check for existing databases
                cursor.execute("PRAGMA table_info(crawled_urls);")
                columns = {col[1] for col in cursor.fetchall()}
                if "parent_url" not in columns:
                    cursor.execute("ALTER TABLE crawled_urls ADD COLUMN parent_url TEXT;")
                if "title" not in columns:
                    cursor.execute("ALTER TABLE crawled_urls ADD COLUMN title TEXT;")
                if "status" not in columns:
                    cursor.execute("ALTER TABLE crawled_urls ADD COLUMN status TEXT DEFAULT 'Completed';")
                if "response_time" not in columns:
                    cursor.execute("ALTER TABLE crawled_urls ADD COLUMN response_time REAL DEFAULT 0.0;")
                if "links_found" not in columns:
                    cursor.execute("ALTER TABLE crawled_urls ADD COLUMN links_found INTEGER DEFAULT 0;")

                cursor.execute("PRAGMA table_info(pending_frontier);")
                p_columns = {col[1] for col in cursor.fetchall()}
                if "parent_url" not in p_columns:
                    cursor.execute("ALTER TABLE pending_frontier ADD COLUMN parent_url TEXT;")

                conn.commit()
            finally:
                conn.close()

    def record_parent_relationship(self, child_url: str, parent_url: Optional[str]) -> None:
        """Records a parent-child relationship (supports multiple parents per page)."""
        if not parent_url or not child_url:
            return
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO page_parents (child_url, parent_url) VALUES (?, ?);",
                    (child_url, parent_url)
                )
                conn.commit()
            finally:
                conn.close()

    def enqueue_frontier_urls(self, items: List[Any]) -> int:
        """
        Adds newly discovered URLs to pending_frontier if not already crawled or queued.
        Accepts tuples of (url, depth) or (url, depth, parent_url).
        Returns count of newly inserted URLs.
        """
        if not items:
            return 0

        inserted = 0
        now = time.time()
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                for item in items:
                    if len(item) == 2:
                        url, depth = item
                        parent_url = None
                    else:
                        url, depth, parent_url = item

                    # Record parent-child relationship if parent is present
                    if parent_url:
                        cursor.execute("""
                            INSERT OR IGNORE INTO page_parents (child_url, parent_url)
                            VALUES (?, ?);
                        """, (url, parent_url))

                    # Check if already crawled
                    cursor.execute("SELECT 1 FROM crawled_urls WHERE url = ? LIMIT 1;", (url,))
                    if cursor.fetchone():
                        continue

                    # Insert if not already in pending (preserves primary parent relationship)
                    cursor.execute("""
                        INSERT OR IGNORE INTO pending_frontier (url, parent_url, depth, status, discovered_at)
                        VALUES (?, ?, ?, 'QUEUED', ?)
                    """, (url, parent_url, depth, now))
                    if cursor.rowcount > 0:
                        inserted += 1
                conn.commit()
            finally:
                conn.close()
        return inserted

    def mark_url_in_progress(self, url: str) -> None:
        """Marks a URL as being currently downloaded by a worker."""
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    "UPDATE pending_frontier SET status = 'IN_PROGRESS' WHERE url = ?;",
                    (url,)
                )
                conn.commit()
            finally:
                conn.close()

    def mark_url_completed(
        self,
        url: str,
        depth: int,
        http_status: int,
        content_length: int,
        error: Optional[str] = None,
        parent_url: Optional[str] = None,
        title: Optional[str] = None,
        status: str = "Completed",
        response_time: float = 0.0,
        links_found: int = 0
    ) -> None:
        """
        Atomically records a completed or failed crawl:
        Deletes the URL from pending_frontier and inserts it into crawled_urls with full metadata.
        """
        now = time.time()
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM pending_frontier WHERE url = ?;", (url,))
                cursor.execute("""
                    INSERT OR REPLACE INTO crawled_urls (
                        url, parent_url, title, depth, http_status, status,
                        response_time, links_found, content_length, crawled_at, error
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    url, parent_url, title, depth, http_status, status,
                    response_time, links_found, content_length, now, error
                ))
                conn.commit()
            finally:
                conn.close()

    def reset_in_progress_tasks(self) -> int:
        """
        Resets any 'IN_PROGRESS' URLs back to 'QUEUED'.
        Called during engine startup/resume to recover from unexpected process crashes.
        """
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE pending_frontier SET status = 'QUEUED' WHERE status = 'IN_PROGRESS';"
                )
                count = cursor.rowcount
                conn.commit()
                return count
            finally:
                conn.close()

    def load_visited_urls(self) -> Set[str]:
        """Loads all previously crawled URLs into memory to populate VisitedRegistry."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT url FROM crawled_urls;")
                return {row[0] for row in cursor.fetchall()}
            finally:
                conn.close()

    def load_pending_urls(self) -> List[Tuple[str, int, Optional[str]]]:
        """
        Loads queued URLs ordered by depth (Breadth-First Search) and discovery order.
        Returns tuples of (url, depth, parent_url).
        """
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT url, depth, parent_url FROM pending_frontier
                    WHERE status = 'QUEUED'
                    ORDER BY depth ASC, discovered_at ASC;
                """)
                return cursor.fetchall()
            finally:
                conn.close()

    def load_all_parents(self) -> Dict[str, List[str]]:
        """Loads all discovered parent-child relationships from database."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT child_url, parent_url FROM page_parents;")
                parents_map: Dict[str, List[str]] = {}
                for c_url, p_url in cursor.fetchall():
                    parents_map.setdefault(c_url, []).append(p_url)
                return parents_map
            finally:
                conn.close()

    def get_all_crawled_records(self) -> List[Dict[str, Any]]:
        """
        Retrieves all crawled page records with complete parent, title, and telemetry metadata.
        Ordered hierarchically by depth and crawl time.
        Attaches all known parent URLs (multiple parents) for each record.
        """
        with self._lock:
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT child_url, parent_url FROM page_parents;")
                parents_map: Dict[str, List[str]] = {}
                for c_url, p_url in cursor.fetchall():
                    parents_map.setdefault(c_url, []).append(p_url)

                cursor.execute("""
                    SELECT
                        url, parent_url, title, depth, http_status,
                        status, response_time, links_found, content_length,
                        crawled_at, error
                    FROM crawled_urls
                    ORDER BY depth ASC, crawled_at ASC;
                """)
                records = []
                for row in cursor.fetchall():
                    rec = dict(row)
                    primary_p = rec.get("parent_url")
                    p_list = list(parents_map.get(rec["url"], []))
                    if primary_p and primary_p not in p_list:
                        p_list.insert(0, primary_p)
                    rec["all_parents"] = p_list
                    records.append(rec)
                return records
            finally:
                conn.close()

    def get_stats(self) -> Tuple[int, int]:
        """Returns (total_crawled, total_pending) from database."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM crawled_urls;")
                crawled_count = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM pending_frontier;")
                pending_count = cursor.fetchone()[0]
                return crawled_count, pending_count
            finally:
                conn.close()

    def close(self) -> None:
        """Checkpoints WAL journal and releases file handles."""
        with self._lock:
            try:
                conn = self._get_connection()
                try:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                finally:
                    conn.close()
            except Exception:
                pass
