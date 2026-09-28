"""
Website Structure Analyzer and Table-Based Sitemap Generator.
Generates:
1. Hierarchical Website Structure Table (Depth, Page, Parent, Status, HTTP, URL)
2. Crawl Details Table (URL, Status, HTTP Code, Response Time, Links Found)
3. Crawl Summary Report
4. Multi-format Exports (TXT, CSV, JSON) in output/ directory.
"""

import csv
import json
import os
from typing import Any, Dict, List, Optional, Set, Tuple


from .parser import clean_title


class StructureAnalyzer:
    """
    Analyzes crawled page records and reconstructs the discovered website blueprint
    based on true parent-child link relationships.
    """

    def __init__(self, records: List[Dict[str, Any]], target_url: str = ""):
        self.records = records
        self.target_url = target_url

        # Ensure all records have a valid, clean title
        for r in self.records:
            if not r.get("title") or r.get("title") == "Untitled":
                r["title"] = clean_title(None, r["url"])

        self.url_map: Dict[str, Dict[str, Any]] = {r["url"]: r for r in records}
        self.title_map: Dict[str, str] = {
            r["url"]: (r.get("title") or clean_title(None, r["url"])) for r in records
        }
        self.children_map: Dict[str, List[str]] = {}
        self._build_hierarchy()

    def _build_hierarchy(self) -> None:
        """Constructs parent -> children mapping based on discovered links."""
        for r in self.records:
            parent = r.get("parent_url")
            if parent:
                self.children_map.setdefault(parent, []).append(r["url"])

    def get_hierarchical_order(self) -> List[Dict[str, Any]]:
        """
        Traverses the parent-child graph in pre-order depth-first traversal
        starting from the root page(s) (depth 0), producing an intuitive site blueprint.
        """
        visited: Set[str] = set()
        ordered: List[Dict[str, Any]] = []

        # Find root nodes: depth == 0, or nodes whose parent is not in our dataset
        roots = [r for r in self.records if r.get("depth", 0) == 0 or not r.get("parent_url")]
        if not roots and self.records:
            # Fallback if no explicit depth 0 exists
            min_depth = min(r.get("depth", 0) for r in self.records)
            roots = [r for r in self.records if r.get("depth", 0) == min_depth]

        def traverse(url: str):
            if url in visited:
                return
            visited.add(url)

            if url in self.url_map:
                ordered.append(self.url_map[url])

            # Traverse children in discovery/depth order
            children = self.children_map.get(url, [])
            for child_url in children:
                traverse(child_url)

        for root in roots:
            traverse(root["url"])

        # Any remaining disconnected or orphaned nodes
        for r in self.records:
            if r["url"] not in visited:
                traverse(r["url"])

        return ordered

    def generate_structure_table(self) -> str:
        """
        Renders the required terminal table:
        Depth | Page | Parent | Status | HTTP | URL
        """
        ordered_records = self.get_hierarchical_order()
        if not ordered_records:
            return "No crawled pages to display in website structure.\n"

        rows = []
        for r in ordered_records:
            depth_str = str(r.get("depth", 0))
            page_title = r.get("title") or "Untitled"
            parent_url = r.get("parent_url")
            parent_title = self.title_map.get(parent_url, "—") if parent_url else "—"
            status = r.get("status") or ("Completed" if (r.get("http_status") or 0) < 400 else "Failed")
            http_code = str(r.get("http_status") or 0)
            url = r.get("url", "")

            rows.append({
                "depth": depth_str,
                "page": page_title,
                "parent": parent_title,
                "status": status,
                "http": http_code,
                "url": url,
            })

        # Calculate dynamic column widths with safe limits for terminal readability
        depth_w = max(5, max(len(row["depth"]) for row in rows))
        page_w = min(25, max(15, max(len(row["page"]) for row in rows)))
        parent_w = min(22, max(15, max(len(row["parent"]) for row in rows)))
        status_w = max(11, max(len(row["status"]) for row in rows))
        http_w = max(4, max(len(row["http"]) for row in rows))

        total_width = max(100, depth_w + page_w + parent_w + status_w + http_w + 35)

        lines = [
            "=" * total_width,
            "WEBSITE STRUCTURE".center(total_width),
            "=" * total_width,
            "",
            f"{'Depth':<{depth_w}} | {'Page':<{page_w}} | {'Parent':<{parent_w}} | {'Status':<{status_w}} | {'HTTP':<{http_w}} | URL",
            f"{'-' * depth_w}-+-{'-' * page_w}-+-{'-' * parent_w}-+-{'-' * status_w}-+-{'-' * http_w}-+-{'-' * 40}",
        ]

        for row in rows:
            p_display = row["page"] if len(row["page"]) <= page_w else row["page"][:page_w - 3] + "..."
            par_display = row["parent"] if len(row["parent"]) <= parent_w else row["parent"][:parent_w - 3] + "..."

            lines.append(
                f"{row['depth']:<{depth_w}} | "
                f"{p_display:<{page_w}} | "
                f"{par_display:<{parent_w}} | "
                f"{row['status']:<{status_w}} | "
                f"{row['http']:<{http_w}} | "
                f"{row['url']}"
            )

        lines.append("=" * total_width)
        return "\n".join(lines)

    def generate_crawl_details_table(self) -> str:
        """
        Renders the required Crawl Details table:
        URL | Status | HTTP Code | Response Time | Links Found
        """
        if not self.records:
            return "No crawl details available.\n"

        rows = []
        for r in self.records:
            url = r.get("url", "")
            status = r.get("status") or ("Completed" if (r.get("http_status") or 0) < 400 else "Failed")
            http_code = str(r.get("http_status") or 0)
            resp_time = f"{r.get('response_time', 0.0):.2f}s"
            links_found = str(r.get("links_found", 0))

            rows.append({
                "url": url,
                "status": status,
                "http": http_code,
                "resp_time": resp_time,
                "links": links_found,
            })

        status_w = max(11, max(len(row["status"]) for row in rows))
        http_w = max(9, max(len(row["http"]) for row in rows))
        resp_w = max(13, max(len(row["resp_time"]) for row in rows))
        links_w = max(11, max(len(row["links"]) for row in rows))
        url_w = max(40, min(60, max(len(row["url"]) for row in rows)))

        total_width = max(96, url_w + status_w + http_w + resp_w + links_w + 12)

        lines = [
            "=" * total_width,
            "CRAWL DETAILS".center(total_width),
            "=" * total_width,
            "",
            f"{'URL':<{url_w}} | {'Status':<{status_w}} | {'HTTP Code':<{http_w}} | {'Response Time':<{resp_w}} | {'Links Found':<{links_w}}",
            f"{'-' * url_w}-+-{'-' * status_w}-+-{'-' * http_w}-+-{'-' * resp_w}-+-{'-' * links_w}",
        ]

        for row in rows:
            url_disp = row["url"] if len(row["url"]) <= url_w else row["url"][:url_w - 3] + "..."
            lines.append(
                f"{url_disp:<{url_w}} | "
                f"{row['status']:<{status_w}} | "
                f"{row['http']:<{http_w}} | "
                f"{row['resp_time']:<{resp_w}} | "
                f"{row['links']:<{links_w}}"
            )

        lines.append("=" * total_width)
        return "\n".join(lines)

    def generate_crawl_summary(
        self,
        threads_used: int,
        max_depth_config: int,
        crawl_time_seconds: float,
        internal_links_total: int = 0,
        external_links_total: int = 0,
        discovered_total: int = 0,
    ) -> str:
        """
        Renders the required Crawl Summary box with dynamic values.
        """
        pages_crawled = len(self.records)
        pages_failed = sum(1 for r in self.records if (r.get("http_status") or 0) >= 400 or (r.get("status") == "Failed"))
        max_depth_reached = max((r.get("depth", 0) for r in self.records), default=0)

        if discovered_total == 0:
            discovered_total = pages_crawled

        lines = [
            "=" * 50,
            "CRAWL SUMMARY".center(50),
            "=" * 50,
            "",
            f"Website               : {self.target_url}",
            f"Threads Used          : {threads_used}",
            f"Maximum Depth         : {max_depth_config}",
            "",
            f"Pages Discovered      : {discovered_total}",
            f"Pages Crawled         : {pages_crawled}",
            f"Pages Failed          : {pages_failed}",
            f"Internal Links        : {internal_links_total}",
            f"External Links        : {external_links_total}",
            f"Maximum Depth Reached : {max_depth_reached}",
            f"Crawl Time            : {crawl_time_seconds:.2f} seconds",
            "",
            "=" * 50,
        ]
        return "\n".join(lines)

    def build_tree_dict(self) -> Dict[str, Any]:
        """
        Generates a nested dictionary representing the hierarchical tree structure
        for export to JSON.
        """
        roots = [r for r in self.records if r.get("depth", 0) == 0 or not r.get("parent_url")]
        if not roots and self.records:
            roots = [self.records[0]]

        def node_to_dict(rec: Dict[str, Any]) -> Dict[str, Any]:
            children_urls = self.children_map.get(rec["url"], [])
            children_nodes = []
            for curl in children_urls:
                if curl in self.url_map:
                    children_nodes.append(node_to_dict(self.url_map[curl]))

            return {
                "title": rec.get("title") or "Untitled",
                "url": rec.get("url", ""),
                "depth": rec.get("depth", 0),
                "status": rec.get("status", "Completed"),
                "http_status": rec.get("http_status", 200),
                "children": children_nodes,
            }

        if len(roots) == 1:
            return node_to_dict(roots[0])
        elif len(roots) > 1:
            return {
                "title": "Website Root",
                "url": self.target_url,
                "depth": 0,
                "children": [node_to_dict(r) for r in roots]
            }
        return {}

    def export_reports(self, output_dir: str = "output") -> Dict[str, str]:
        """
        Exports TXT, CSV, and JSON reports to output_dir:
        - website_structure.txt
        - website_structure.csv
        - website_structure.json
        - crawl_report.csv
        """
        os.makedirs(output_dir, exist_ok=True)
        paths = {}

        # 1. website_structure.txt
        txt_path = os.path.join(output_dir, "website_structure.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(self.generate_structure_table())
            f.write("\n")
        paths["txt"] = txt_path

        # 2. website_structure.csv
        csv_path = os.path.join(output_dir, "website_structure.csv")
        ordered_records = self.get_hierarchical_order()
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Depth", "Page Title", "Parent", "URL", "Status", "HTTP Status Code"])
            for r in ordered_records:
                parent_url = r.get("parent_url")
                parent_title = self.title_map.get(parent_url, "—") if parent_url else "—"
                writer.writerow([
                    r.get("depth", 0),
                    r.get("title") or "Untitled",
                    parent_title,
                    r.get("url", ""),
                    r.get("status") or "Completed",
                    r.get("http_status") or 0,
                ])
        paths["structure_csv"] = csv_path

        # 3. website_structure.json
        json_path = os.path.join(output_dir, "website_structure.json")
        tree_data = self.build_tree_dict()
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(tree_data, f, indent=2, ensure_ascii=False)
        paths["json"] = json_path

        # 4. crawl_report.csv
        report_path = os.path.join(output_dir, "crawl_report.csv")
        with open(report_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["URL", "Status", "HTTP Code", "Response Time", "Links Found"])
            for r in self.records:
                writer.writerow([
                    r.get("url", ""),
                    r.get("status") or "Completed",
                    r.get("http_status") or 0,
                    f"{r.get('response_time', 0.0):.2f}s",
                    r.get("links_found", 0),
                ])
        paths["crawl_report_csv"] = report_path

        return paths
