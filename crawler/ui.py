"""
Terminal User Interface and Real-Time Dashboard.
Uses ANSI escape codes and Colorama for cross-platform live thread telemetry.
Displays:
- Currently processed URLs per worker thread
- Active worker threads count
- Completed URLs count
- Pending URLs in queue
- Failed requests / errors count
"""

import sys
import time
from typing import Dict

try:
    import colorama
    colorama.init(autoreset=True)
    CYAN = colorama.Fore.CYAN
    GREEN = colorama.Fore.GREEN
    YELLOW = colorama.Fore.YELLOW
    RED = colorama.Fore.RED
    BLUE = colorama.Fore.BLUE
    MAGENTA = colorama.Fore.MAGENTA
    RESET = colorama.Style.RESET_ALL
    BRIGHT = colorama.Style.BRIGHT
    DIM = colorama.Style.DIM
except ImportError:
    CYAN = GREEN = YELLOW = RED = BLUE = MAGENTA = RESET = BRIGHT = DIM = ""

from .sync_primitives import MetricsSnapshot, WorkerStateSnapshot


def format_bytes(size: int) -> str:
    """Formats bytes to human-readable string (KB, MB, GB)."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024.0:
            return f"{size:3.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def format_time(seconds: float) -> str:
    """Formats seconds to MM:SS."""
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


class TerminalDashboard:
    """Renders a real-time OS process & thread status dashboard in the console."""

    def __init__(self, target_url: str, total_workers: int, max_pages: int):
        self.target_url = target_url
        self.total_workers = total_workers
        self.max_pages = max_pages
        self._last_render_time = 0.0

    def render(self, snapshot: MetricsSnapshot, is_final: bool = False) -> None:
        """Draws the live status board."""
        now = time.time()
        # Rate limit render updates to avoid CPU overhead
        if not is_final and (now - self._last_render_time) < 0.15:
            return
        self._last_render_time = now

        lines = []

        # Header
        lines.append(f"{BRIGHT}{BLUE}================================================================================{RESET}")
        lines.append(f"{BRIGHT}{CYAN}       MULTI-THREADED WEB CRAWLER  (Operating Systems Project){RESET}")
        lines.append(f"{DIM}Seed/Target: {self.target_url[:55]} | Max Pages: {self.max_pages} | Total Threads: {self.total_workers}{RESET}")
        lines.append(f"{BRIGHT}{BLUE}================================================================================{RESET}")

        # Worker Thread Status Table (Currently Processed URLs per thread)
        lines.append(f"{BRIGHT}{'Thread ID':<12} {'Status':<12} {'Depth':<7} {'Pages Done':<11} {'Currently Processed URL'}{RESET}")
        lines.append(f"{DIM}{'-'*80}{RESET}")

        for wid, worker in sorted(snapshot.workers.items()):
            status_color = RESET
            if worker.status == "FETCHING":
                status_color = CYAN
            elif worker.status == "PARSING":
                status_color = YELLOW
            elif worker.status == "DONE":
                status_color = GREEN
            elif worker.status in ("IDLE", "WAITING"):
                status_color = DIM

            curr_url = worker.current_url
            if len(curr_url) > 42:
                curr_url = curr_url[:39] + "..."

            depth_str = str(worker.depth) if worker.status in ("FETCHING", "PARSING") else "-"

            line = (
                f"{BRIGHT}{wid:<12}{RESET} "
                f"{status_color}{worker.status:<12}{RESET} "
                f"{depth_str:<7} "
                f"{worker.pages_processed:<11} "
                f"{DIM}{curr_url}{RESET}"
            )
            lines.append(line)

        # Metrics & Summary Footer (Active Threads, Completed URLs, Pending URLs, Failed Requests)
        lines.append(f"{DIM}{'-'*80}{RESET}")

        status_breakdown = ", ".join(f"{code}: {count}" for code, count in sorted(snapshot.status_codes.items()))
        if not status_breakdown:
            status_breakdown = "None"

        lines.append(
            f"Completed URLs: {GREEN}{snapshot.pages_crawled}{RESET}/{self.max_pages} | "
            f"Pending in Queue: {YELLOW}{snapshot.queue_size}{RESET} | "
            f"Failed Requests: {RED if snapshot.errors_count > 0 else GREEN}{snapshot.errors_count}{RESET} | "
            f"Speed: {CYAN}{snapshot.crawl_rate:.1f} p/s{RESET}"
        )
        lines.append(
            f"Active Threads: {CYAN}{snapshot.active_workers}{RESET}/{self.total_workers} | "
            f"Data Downloaded: {format_bytes(snapshot.bytes_downloaded)} | "
            f"Time Elapsed: {format_time(snapshot.elapsed_seconds)} | "
            f"HTTP Codes: [{status_breakdown}]"
        )
        lines.append(f"{DIM}Press Ctrl+C to pause and save state for resuming later.{RESET}")
        lines.append(f"{BRIGHT}{BLUE}================================================================================{RESET}")

        output = "\n".join(lines)

        # ANSI Clear screen and move cursor to top-left (home)
        sys.stdout.write("\033[H\033[J")
        sys.stdout.write(output + "\n")
        sys.stdout.flush()

    def print_final_summary(self, snapshot: MetricsSnapshot, paused: bool = False) -> None:
        """Prints a permanent summary report after crawler finishes or pauses."""
        status_msg = f"{YELLOW}PAUSED (State Saved){RESET}" if paused else f"{GREEN}COMPLETED{RESET}"

        print("\n" + "=" * 60)
        print(f"{BRIGHT}CRAWL SUMMARY REPORT - {status_msg}")
        print("=" * 60)
        print(f"Target URL:          {self.target_url}")
        print(f"Completed URLs:      {snapshot.pages_crawled}")
        print(f"Pending in Queue:    {snapshot.queue_size}")
        print(f"Links Discovered:    {snapshot.links_discovered}")
        print(f"Failed Requests:     {snapshot.errors_count}")
        print(f"Total Data Read:     {format_bytes(snapshot.bytes_downloaded)}")
        print(f"Total Time Elapsed:  {format_time(snapshot.elapsed_seconds)}")
        print(f"Average Throughput:  {snapshot.crawl_rate:.2f} pages/second")
        print(f"Worker Threads:      {self.total_workers}")
        print("=" * 60)
        if paused:
            print(f"{BRIGHT}{CYAN}To resume this crawl, run python main.py and select Resume (or use --resume).{RESET}\n")
        else:
            print(f"{BRIGHT}{GREEN}Crawl finished successfully.{RESET}\n")
