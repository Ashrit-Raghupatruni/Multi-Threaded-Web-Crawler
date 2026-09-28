"""
HTTP Fetcher Module.
Performs concurrent network I/O operations with configurable timeouts,
User-Agent headers, politeness delay, response time measurement, and content-type verification.
"""

import time
import urllib.error
import urllib.request
from typing import Optional, Tuple


class PageFetcher:
    """
    Handles network requests for worker threads.
    Demonstrates OS thread scheduling during blocking I/O calls.
    """

    def __init__(self, timeout: float = 5.0, user_agent: str = "OS-WebCrawler/1.0", politeness_delay: float = 0.05):
        self.timeout = timeout
        self.user_agent = user_agent
        self.politeness_delay = politeness_delay

    def fetch(self, url: str) -> Tuple[Optional[str], int, int, float, Optional[str]]:
        """
        Downloads a webpage and measures elapsed response time.

        Returns:
            Tuple of:
            - html_content: Decoded string or None on failure
            - status_code: HTTP response code (e.g. 200, 404) or 0 on network error
            - content_length: Length of downloaded content in bytes
            - response_time: Elapsed request time in seconds
            - error_message: Error string if an exception occurred, else None
        """
        # Politeness delay to prevent server rate-limiting/overload
        if self.politeness_delay > 0:
            time.sleep(self.politeness_delay)

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            }
        )

        start_time = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                status_code = response.getcode()
                content_type = response.headers.get("Content-Type", "").lower()
                response_time = round(time.perf_counter() - start_time, 2)

                # Only parse HTML/XML text documents; avoid downloading huge binaries
                if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
                    return None, status_code, 0, response_time, f"Skipped non-HTML content type: {content_type}"

                raw_bytes = response.read()
                content_length = len(raw_bytes)

                # Attempt decoding UTF-8 with fallback
                charset = response.headers.get_content_charset() or "utf-8"
                try:
                    html_text = raw_bytes.decode(charset, errors="replace")
                except Exception:
                    html_text = raw_bytes.decode("latin-1", errors="replace")

                return html_text, status_code, content_length, response_time, None

        except urllib.error.HTTPError as e:
            response_time = round(time.perf_counter() - start_time, 2)
            return None, e.code, 0, response_time, f"HTTP Error {e.code}: {e.reason}"
        except urllib.error.URLError as e:
            response_time = round(time.perf_counter() - start_time, 2)
            return None, 0, 0, response_time, f"URL Error: {e.reason}"
        except TimeoutError:
            response_time = round(time.perf_counter() - start_time, 2)
            return None, 408, 0, response_time, "Request timed out"
        except Exception as e:
            response_time = round(time.perf_counter() - start_time, 2)
            return None, 0, 0, response_time, f"Exception: {str(e)}"
