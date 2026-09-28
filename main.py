#!/usr/bin/env python3
"""
Main CLI Entrypoint for the Multi-Threaded Web Crawler.
Operating Systems Course Project.

Provides both an interactive terminal interface (prompting for Website URL,
threads, and depth) and non-interactive command-line flags.
"""

import argparse
import os
import sys
from urllib.parse import urlparse

from crawler.config import CrawlerConfig
from crawler.engine import CrawlerEngine
from crawler.storage import StorageEngine
from crawler.structure_analyzer import StructureAnalyzer


def inspect_status(db_path: str) -> None:
    """Displays current persisted database stats and website structure without launching threads."""
    if not os.path.exists(db_path):
        print(f"No database file found at '{db_path}'.")
        return

    storage = StorageEngine(db_path)
    crawled, pending = storage.get_stats()
    records = storage.get_all_crawled_records()
    storage.close()

    print("=" * 50)
    print(f"DATABASE INSPECTION: {db_path}")
    print("=" * 50)
    print(f"Total Completed URLs: {crawled}")
    print(f"Total Pending URLs:   {pending}")
    print(f"Total Discovered:     {crawled + pending}")
    print("=" * 50)

    if records:
        target = records[0]["url"] if records else "Website"
        analyzer = StructureAnalyzer(records, target_url=target)
        print("\n" + analyzer.generate_structure_table())


def prompt_validated_url() -> str:
    """Prompts the user for a website URL and validates it."""
    while True:
        try:
            print("Enter website URL:")
            raw_url = input("> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled by user.")
            sys.exit(0)

        if not raw_url:
            print("[Error] URL cannot be empty. Please try again.\n")
            continue

        if " " in raw_url:
            print("[Error] URL cannot contain spaces. Please try again.\n")
            continue

        # Add https:// scheme if user omitted protocol
        if not (raw_url.startswith("http://") or raw_url.startswith("https://")):
            if "." not in raw_url and raw_url.lower() != "localhost":
                print(f"[Error] '{raw_url}' is not a valid domain name. Please try again.\n")
                continue
            candidate = "https://" + raw_url
        else:
            candidate = raw_url

        try:
            parsed = urlparse(candidate)
            if parsed.scheme in ("http", "https") and bool(parsed.netloc):
                return candidate
            else:
                print(f"[Error] '{raw_url}' is not a valid HTTP/HTTPS URL. Please try again.\n")
        except Exception:
            print(f"[Error] Failed to parse URL '{raw_url}'. Please try again.\n")


def prompt_validated_int(prompt_text: str, min_val: int = 1, default_val: int = None) -> int:
    """Prompts the user for an integer with bounds checking."""
    while True:
        try:
            print(prompt_text)
            raw = input("> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled by user.")
            sys.exit(0)

        if not raw and default_val is not None:
            return default_val

        try:
            val = int(raw)
            if val < min_val:
                print(f"[Error] Value must be at least {min_val}. Please try again.\n")
                continue
            return val
        except ValueError:
            default_hint = f" or press Enter for default {default_val}" if default_val is not None else ""
            print(f"[Error] Please enter a valid integer (minimum {min_val}){default_hint}.\n")


def interactive_mode(db_path: str = "crawler_state.db") -> CrawlerConfig:
    """Interactive terminal wizard prompting the user for crawl settings or resume."""
    print("=" * 72)
    print("      MULTI-THREADED WEB CRAWLER (Operating Systems Project)")
    print("=" * 72)

    # Check if existing session is present
    has_existing_state = False
    crawled_count = 0
    pending_count = 0

    if os.path.exists(db_path):
        try:
            storage = StorageEngine(db_path)
            crawled_count, pending_count = storage.get_stats()
            storage.close()
            if crawled_count > 0 or pending_count > 0:
                has_existing_state = True
        except Exception:
            has_existing_state = False

    resume = False

    if has_existing_state:
        print(f"Saved crawl session detected in '{db_path}':")
        print(f"  - Completed URLs: {crawled_count}")
        print(f"  - Pending URLs:   {pending_count}")
        print("\nSelect an option:")
        print("  [1] Start a New Crawl (overwrites previous session)")
        print("  [2] Resume Previous Crawl")
        print("  [3] Exit\n")

        while True:
            try:
                choice = input("Enter choice (1/2/3): ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\nExiting.")
                sys.exit(0)

            if choice == "1":
                # Clean old database for new crawl
                try:
                    os.remove(db_path)
                    for ext in ["-wal", "-shm"]:
                        if os.path.exists(db_path + ext):
                            os.remove(db_path + ext)
                except Exception:
                    pass
                print()
                break
            elif choice == "2":
                resume = True
                print()
                break
            elif choice == "3":
                print("Exiting.")
                sys.exit(0)
            else:
                print("Invalid choice. Please enter 1, 2, or 3.")

    if resume:
        # Prompt worker threads and max pages for resumed session
        workers = prompt_validated_int("Enter number of threads (e.g. 5):", min_val=1, default_val=4)
        print()
        max_pages = prompt_validated_int(
            "Enter maximum total pages to crawl (optional, press Enter for 50):",
            min_val=1,
            default_val=50
        )
        print()
        return CrawlerConfig(
            seed_url=None,
            max_workers=workers,
            max_pages=max_pages,
            max_depth=3,
            db_path=db_path,
            resume=True,
        )

    # New Crawl prompts:
    # 1. Website URL
    seed_url = prompt_validated_url()
    print()

    # 2. Number of threads
    workers = prompt_validated_int("Enter number of threads (e.g. 5):", min_val=1, default_val=4)
    print()

    # 3. Maximum crawl depth
    depth = prompt_validated_int("Enter maximum crawl depth (e.g. 3):", min_val=0, default_val=3)
    print()

    # 4. Maximum pages limit
    max_pages = prompt_validated_int(
        "Enter maximum pages to crawl (optional, press Enter for 50):",
        min_val=1,
        default_val=50
    )
    print()

    return CrawlerConfig(
        seed_url=seed_url,
        max_workers=workers,
        max_pages=max_pages,
        max_depth=depth,
        db_path=db_path,
        resume=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Multi-Threaded Web Crawler (Operating Systems Project)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--url", "-u",
        type=str,
        help="Seed URL to begin crawling from"
    )
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=None,
        help="Number of concurrent worker threads in the pool"
    )
    parser.add_argument(
        "--max-pages", "-m",
        type=int,
        default=50,
        help="Maximum number of web pages to crawl before stopping"
    )
    parser.add_argument(
        "--depth", "-d",
        type=int,
        default=3,
        help="Maximum link traversal depth from the seed URL"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.05,
        help="Politeness delay in seconds between requests per worker"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Network request timeout in seconds"
    )
    parser.add_argument(
        "--db",
        type=str,
        default="crawler_state.db",
        help="Path to SQLite persistent state file"
    )
    parser.add_argument(
        "--resume", "-r",
        action="store_true",
        help="Resume crawling from where it left off using the persistent database"
    )
    parser.add_argument(
        "--cross-domain",
        action="store_true",
        help="Allow crawling hyperlinks that point to external domains"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Disable the live terminal UI dashboard"
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        default="output",
        help="Directory to save exported structure reports (TXT, CSV, JSON)"
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Inspect existing crawl statistics in the database and exit"
    )
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Launch the interactive terminal prompt interface"
    )

    args = parser.parse_args()

    if args.status:
        inspect_status(args.db)
        return

    # If neither --url nor --resume is provided, or if --interactive is passed, launch interactive prompt
    if args.interactive or (not args.resume and not args.url):
        config = interactive_mode(db_path=args.db)
        config.output_dir = args.output_dir
        config.request_timeout = args.timeout
        config.politeness_delay = args.delay
        config.same_domain_only = not args.cross_domain
        config.headless_ui = args.headless
    else:
        config = CrawlerConfig(
            seed_url=args.url,
            max_workers=args.workers if args.workers is not None else 4,
            max_pages=args.max_pages,
            max_depth=args.depth,
            same_domain_only=not args.cross_domain,
            politeness_delay=args.delay,
            request_timeout=args.timeout,
            db_path=args.db,
            output_dir=args.output_dir,
            resume=args.resume,
            headless_ui=args.headless,
        )

    engine = CrawlerEngine(config)
    try:
        engine.start()
    except Exception as e:
        print(f"\n[FATAL ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
