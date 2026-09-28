"""
HTML Parser, Title Extractor, and Link Normalizer.
Extracts:
1. HTML <title> tag with sensible fallback to URL path slug and whitespace cleanup.
2. Internal hyperlinks (within the same domain).
3. External hyperlinks (pointing to outside domains).
"""

import html
import re
from html.parser import HTMLParser
from typing import List, Optional, Set, Tuple
from urllib.parse import unquote, urldefrag, urljoin, urlparse


class HTMLContentParser(HTMLParser):
    """HTML parser to collect both page title and href hyperlinks."""

    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.extracted_links: List[str] = []
        self._in_title = False
        self._title_parts: List[str] = []
        self.raw_title: Optional[str] = None

    def handle_starttag(self, tag: str, attrs: list):
        tag_lower = tag.lower()
        if tag_lower == "title":
            self._in_title = True
        elif tag_lower == "a":
            for attr_name, attr_value in attrs:
                if attr_name.lower() == "href" and attr_value:
                    self.extracted_links.append(attr_value.strip())

    def handle_endtag(self, tag: str):
        if tag.lower() == "title":
            self._in_title = False
            if self._title_parts:
                self.raw_title = "".join(self._title_parts)

    def handle_data(self, data: str):
        if self._in_title:
            self._title_parts.append(data)


def clean_title(raw_title: Optional[str], url: str) -> str:
    """
    Cleans raw HTML title:
    1. Unescapes HTML entities.
    2. Strips redundant whitespace and newlines.
    3. Strips site branding suffixes if present (e.g. 'Best Laptops | Example' -> 'Best Laptops').
    4. If title is missing or empty, generates a sensible human-readable fallback from URL path.
    """
    if raw_title:
        decoded = html.unescape(raw_title)
        # Collapse multiple whitespace/tabs/newlines into a single space
        cleaned = " ".join(decoded.split()).strip()

        if cleaned:
            # Strip site suffix branding (e.g. "Page Name | Site", "Page Name - Site")
            for separator in [" | ", " - ", " — ", " – ", " :: ", " • "]:
                if separator in cleaned:
                    parts = cleaned.split(separator)
                    if parts[0].strip():
                        cleaned = parts[0].strip()
                        break
            if cleaned:
                return cleaned

    # Fallback to URL path slug
    return fallback_title_from_url(url)


def fallback_title_from_url(url: str) -> str:
    """Derives a human-friendly title from a URL path."""
    try:
        parsed = urlparse(url)
        path = unquote(parsed.path or "").strip("/")

        if not path or path.lower() in ("index.html", "index.htm", "index.php", "home"):
            return "Home"

        # Take the last meaningful path segment
        segments = [seg for seg in path.split("/") if seg]
        if not segments:
            return "Home"

        last_seg = segments[-1]
        # Remove file extension (e.g., .html, .php, .aspx)
        last_seg = re.sub(r"\.[a-zA-Z0-9]{2,5}$", "", last_seg)

        # Replace hyphens, underscores, and plus signs with spaces
        slug_title = re.sub(r"[-_+]+", " ", last_seg).strip()
        if not slug_title:
            return "Home"

        # Capitalize words nicely
        return slug_title.title()
    except Exception:
        return "Untitled Page"


def is_valid_url(url: str) -> bool:
    """Checks whether URL has an HTTP or HTTPS scheme and valid netloc."""
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def is_same_domain(base_url: str, target_url: str) -> bool:
    """Checks if target_url belongs to the same domain (or subdomain) as base_url."""
    try:
        base_netloc = urlparse(base_url).netloc.lower()
        target_netloc = urlparse(target_url).netloc.lower()

        # Remove port numbers if present for domain comparison
        base_domain = base_netloc.split(":")[0]
        target_domain = target_netloc.split(":")[0]

        return target_domain == base_domain or target_domain.endswith("." + base_domain)
    except Exception:
        return False


def parse_page(
    html_content: str,
    base_url: str
) -> Tuple[str, Set[str], Set[str]]:
    """
    Parses HTML content, extracts page title, and categorizes links into
    internal (same domain) and external (cross domain).

    Returns:
        Tuple of (page_title, internal_links, external_links)
    """
    if not html_content:
        return clean_title(None, base_url), set(), set()

    parser = HTMLContentParser(base_url)
    try:
        parser.feed(html_content)
    except Exception:
        pass

    page_title = clean_title(parser.raw_title, base_url)

    internal_links: Set[str] = set()
    external_links: Set[str] = set()

    for raw_link in parser.extracted_links:
        raw_lower = raw_link.lower()
        # Filter out non-http protocols (mailto, javascript, tel, data, #)
        if raw_lower.startswith(("mailto:", "javascript:", "tel:", "data:", "#")):
            continue

        try:
            absolute_url = urljoin(base_url, raw_link)
            clean_url, _ = urldefrag(absolute_url)

            if not is_valid_url(clean_url):
                continue

            if is_same_domain(base_url, clean_url):
                internal_links.add(clean_url)
            else:
                external_links.add(clean_url)
        except Exception:
            continue

    return page_title, internal_links, external_links


def extract_links(
    html_content: str,
    base_url: str,
    same_domain_only: bool = True
) -> Set[str]:
    """Backwards-compatible helper returning normalized links."""
    _, internal_links, external_links = parse_page(html_content, base_url)
    if same_domain_only:
        return internal_links
    return internal_links.union(external_links)
