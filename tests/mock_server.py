"""
Local Multi-Threaded Mock HTTP Server for Offline Testing.
Serves a deterministic synthetic web graph containing:
- Deep links (hierarchical pages)
- Interconnected circular links (testing loop prevention)
- 404 dead links
- Non-HTML binary resources (testing MIME filter)
- External links (testing domain boundary enforcement)
"""

import http.server
import socketserver
import threading
from typing import Dict, Tuple


PAGES: Dict[str, Tuple[int, str, str]] = {
    "/": (
        200,
        "text/html; charset=utf-8",
        """<!DOCTYPE html>
        <html>
        <head><title>Home</title></head>
        <body>
            <h1>Welcome to Mock Site</h1>
            <a href="/section1">Section 1</a>
            <a href="/section2">Section 2</a>
            <a href="/section3">Section 3</a>
            <a href="/cycle_a">Cycle Start</a>
            <a href="/missing-page">Broken Link</a>
            <a href="https://example.com/external">External Link</a>
            <a href="/logo.png">Binary Image</a>
        </body>
        </html>"""
    ),
    "/section1": (
        200,
        "text/html; charset=utf-8",
        """<!DOCTYPE html>
        <html>
        <body>
            <h2>Section 1</h2>
            <a href="/section1/page1">Subpage 1.1</a>
            <a href="/section1/page2">Subpage 1.2</a>
            <a href="/">Back to Home</a>
        </body>
        </html>"""
    ),
    "/section1/page1": (
        200,
        "text/html; charset=utf-8",
        """<!DOCTYPE html><html><body><h2>Subpage 1.1</h2><a href="/section1/page1/deep">Deep Page</a></body></html>"""
    ),
    "/section1/page1/deep": (
        200,
        "text/html; charset=utf-8",
        """<!DOCTYPE html><html><body><h2>Deep Page Level 3</h2></body></html>"""
    ),
    "/section1/page2": (
        200,
        "text/html; charset=utf-8",
        """<!DOCTYPE html><html><body><h2>Subpage 1.2</h2><a href="/section2">Jump to Section 2</a></body></html>"""
    ),
    "/section2": (
        200,
        "text/html; charset=utf-8",
        """<!DOCTYPE html><html><body><h2>Section 2</h2><a href="/section3">To Section 3</a></body></html>"""
    ),
    "/section3": (
        200,
        "text/html; charset=utf-8",
        """<!DOCTYPE html><html><body><h2>Section 3</h2><a href="/">Home</a></body></html>"""
    ),
    "/cycle_a": (
        200,
        "text/html; charset=utf-8",
        """<!DOCTYPE html><html><body><h2>Cycle A</h2><a href="/cycle_b">Go to Cycle B</a></body></html>"""
    ),
    "/cycle_b": (
        200,
        "text/html; charset=utf-8",
        """<!DOCTYPE html><html><body><h2>Cycle B</h2><a href="/cycle_a">Loop back to Cycle A</a></body></html>"""
    ),
    "/logo.png": (
        200,
        "image/png",
        "FAKE_PNG_BYTES"
    ),
}


class MockHTTPHandler(http.server.BaseHTTPRequestHandler):
    """Custom request handler serving synthetic page graph."""

    def log_message(self, format, *args):
        # Suppress logging to stdout during unit tests
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in PAGES:
            status, ctype, body = PAGES[path]
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            data = body.encode("utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            msg = b"<h1>404 Not Found</h1>"
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class MockServer:
    """Manages the lifecycle of a background mock HTTP server for testing."""

    def __init__(self):
        self.server = ThreadedHTTPServer(("127.0.0.1", 0), MockHTTPHandler)
        self.host, self.port = self.server.server_address
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self) -> str:
        self._thread.start()
        return self.base_url

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
