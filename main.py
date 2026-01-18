#!/usr/bin/env python3
"""
Export a Notion page AND all forward-linked Notion pages into Markdown files.

Forward links included:
- Rich-text mentions of type "page"
- Blocks of type "link_to_page"
- (Optional) child_page blocks (sub-pages in the tree) are naturally traversed because they appear as blocks too.

Requires:
  pip install notion-client python-slugify requests

Auth:
  export NOTION_TOKEN="secret_..."

Usage:
  uv run main.py \
    --root-url "https://www.notion.so/your-page-id" \
    --out "./export"

Notes:
- Notion API access generally requires the page be shared with your integration.
- File/image URLs returned by Notion are time-limited. This script embeds them by default.
"""

from __future__ import annotations

import argparse
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

import requests
from notion_client import Client
from notion_client.errors import APIResponseError
from slugify import slugify

NOTION_VERSION_DEFAULT = "2022-06-28"


# ----------------------------
# Helpers: IDs, filenames, retries
# ----------------------------

UUID32_RE = re.compile(r"([0-9a-fA-F]{32})")
UUID36_RE = re.compile(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")


def normalize_page_id(value: str) -> str:
    """
    Accepts:
      - full Notion URL containing 32-hex id
      - 32-hex id
      - canonical UUID with hyphens (36 chars)
    Returns canonical UUID with hyphens (lowercase).
    """
    value = value.strip()

    m36 = UUID36_RE.search(value)
    if m36:
        return m36.group(1).lower()

    m32 = UUID32_RE.search(value.replace("-", ""))
    if not m32:
        raise ValueError(f"Could not find a Notion page id in: {value}")

    raw = m32.group(1).lower()
    # Insert hyphens to make UUID v4 format: 8-4-4-4-12
    return f"{raw[0:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"


def safe_filename(title: str, page_id: str) -> str:
    """
    Create a stable, collision-resistant filename.
    """
    base = slugify(title) or "untitled"
    short = page_id.replace("-", "")[:10]
    return f"{base}--{short}.md"


def with_retry(fn, *, max_tries: int = 6, base_sleep: float = 0.6):
    """
    Basic exponential backoff for Notion API rate limits/transient errors.
    Does NOT retry on 400/404 errors (permanent failures).
    """
    last_err = None
    for i in range(max_tries):
        try:
            return fn()
        except APIResponseError as e:
            last_err = e
            status = getattr(e, "status", None)
            # Don't retry permanent client errors (400, 403, 404)
            if status in (400, 403, 404):
                raise
            # Retry on rate limits and server errors
            if status in (429, 500, 502, 503, 504) or status is None:
                sleep_s = base_sleep * (2**i)
                time.sleep(sleep_s)
                continue
            raise
    raise last_err


# ----------------------------
# Markdown rendering
# ----------------------------


def rich_text_to_md(rich: List[Dict[str, Any]], link_map: Dict[str, str]) -> Tuple[str, Set[str]]:
    """
    Convert Notion rich_text array to Markdown.
    Returns (md_text, linked_page_ids_found)
    """
    out: List[str] = []
    found_links: Set[str] = set()

    for rt in rich or []:
        plain = rt.get("plain_text", "")

        # mentions can encode page links
        if rt.get("type") == "mention":
            mention = rt.get("mention", {})
            if mention.get("type") == "page":
                pid = mention["page"]["id"]
                found_links.add(pid)

        # Notion also supports href on rich text
        href = rt.get("href")
        if href:
            # If href contains a Notion page id, rewrite to local file if known later
            try:
                pid = normalize_page_id(href)
                found_links.add(pid)
                # Use plain as label; target resolved later when link_map filled
                out.append(f"[{plain}]({{PAGE:{pid}}})")
                continue
            except Exception:
                # not a notion page link; keep as-is
                out.append(f"[{plain}]({href})")
                continue

        annotations = rt.get("annotations", {}) or {}
        text = plain

        # Apply styles (minimal but decent)
        if annotations.get("code"):
            text = f"`{text}`"
        if annotations.get("bold"):
            text = f"**{text}**"
        if annotations.get("italic"):
            text = f"*{text}*"
        if annotations.get("strikethrough"):
            text = f"~~{text}~~"
        if annotations.get("underline"):
            # Markdown underline isn't standard; use HTML
            text = f"<u>{text}</u>"

        out.append(text)

    return "".join(out), found_links


def replace_page_placeholders(md: str, link_map: Dict[str, str]) -> str:
    """
    Replace placeholders like {PAGE:<uuid>} with relative links based on link_map.
    """

    def repl(m):
        pid = m.group(1).lower()
        target = link_map.get(pid)
        if not target:
            # fallback to notion URL
            return f"https://www.notion.so/{pid.replace('-', '')}"
        return f"./{target}"

    return re.sub(r"\{PAGE:([0-9a-f\-]{36})\}", repl, md)


def indent_lines(text: str, n: int) -> str:
    pad = " " * n
    return "\n".join(pad + line if line.strip() else line for line in text.splitlines())


@dataclass
class RenderResult:
    md: str
    linked_pages: Set[str]


def blocks_to_md(blocks: List[Dict[str, Any]], link_map: Dict[str, str], depth: int = 0) -> RenderResult:
    """
    Render a list of Notion blocks into Markdown.
    Collects forward page links found in rich text and link_to_page blocks.
    """
    lines: List[str] = []
    linked: Set[str] = set()

    # List handling: Notion returns list items as consecutive blocks.
    # We'll render them with simple prefixes; nested list levels are represented via children.
    for b in blocks:
        btype = b.get("type")
        bid = b.get("id")
        has_children = b.get("has_children", False)

        def render_children() -> RenderResult:
            if not has_children:
                return RenderResult(md="", linked_pages=set())
            # Children are rendered by the caller (we fetch externally) — here we assume children already in b["_children"].
            children = b.get("_children", []) or []
            return blocks_to_md(children, link_map, depth=depth + 1)

        if btype in ("paragraph", "heading_1", "heading_2", "heading_3", "quote", "callout"):
            payload = b.get(btype, {})
            text, found = rich_text_to_md(payload.get("rich_text", []), link_map)
            linked |= found

            if btype == "paragraph":
                if text.strip():
                    lines.append(text)
                else:
                    lines.append("")  # preserve blank lines
            elif btype.startswith("heading_"):
                level = {"heading_1": "#", "heading_2": "##", "heading_3": "###"}[btype]
                lines.append(f"{level} {text}".rstrip())
            elif btype == "quote":
                lines.append(f"> {text}".rstrip())
            elif btype == "callout":
                icon = payload.get("icon")
                icon_txt = ""
                if isinstance(icon, dict):
                    if icon.get("type") == "emoji":
                        icon_txt = icon.get("emoji", "") + " "
                # A simple callout style
                lines.append(f"> {icon_txt}{text}".rstrip())

            child_res = render_children()
            if child_res.md.strip():
                lines.append(child_res.md)
            linked |= child_res.linked_pages

        elif btype in ("bulleted_list_item", "numbered_list_item", "to_do", "toggle"):
            payload = b.get(btype, {})
            text, found = rich_text_to_md(payload.get("rich_text", []), link_map)
            linked |= found

            prefix = "-"
            if btype == "numbered_list_item":
                prefix = "1."
            elif btype == "to_do":
                checked = payload.get("checked", False)
                prefix = "- [x]" if checked else "- [ ]"
            elif btype == "toggle":
                prefix = "-"

            if btype == "toggle":
                # Use HTML details/summary for a good Markdown experience
                lines.append(f"<details>")
                lines.append(f"<summary>{text}</summary>")
                child_res = render_children()
                if child_res.md.strip():
                    lines.append("")
                    lines.append(child_res.md)
                    lines.append("")
                lines.append(f"</details>")
                linked |= child_res.linked_pages
            else:
                lines.append(f"{prefix} {text}".rstrip())
                child_res = render_children()
                if child_res.md.strip():
                    lines.append(indent_lines(child_res.md, 2))
                linked |= child_res.linked_pages

        elif btype == "code":
            payload = b.get("code", {})
            code_text, found = rich_text_to_md(payload.get("rich_text", []), link_map)
            linked |= found
            lang = payload.get("language", "") or ""
            lines.append(f"```{lang}".rstrip())
            lines.append(code_text)
            lines.append("```")
            child_res = render_children()
            linked |= child_res.linked_pages
            if child_res.md.strip():
                lines.append(child_res.md)

        elif btype == "divider":
            lines.append("---")

        elif btype == "link_to_page":
            lp = b.get("link_to_page", {})
            lpt = lp.get("type")
            if lpt == "page_id":
                pid = lp.get("page_id")
                if pid:
                    linked.add(pid)
                    # Placeholder link; resolved later
                    lines.append(f"- [Linked page]({{PAGE:{pid}}})")
            else:
                # database_id etc.
                lines.append(f"- Linked: {lpt}")

        elif btype == "child_page":
            # This is a sub-page block; treat as a forward link too
            title = b.get("child_page", {}).get("title", "Subpage")
            # child_page has id = page id
            if bid:
                linked.add(bid)
                lines.append(f"- [{title}]({{PAGE:{bid}}})")

        elif btype in ("image", "file", "pdf", "video", "audio"):
            payload = b.get(btype, {})
            caption, found = rich_text_to_md(payload.get("caption", []), link_map)
            linked |= found

            # Files can be "external" or "file"
            url = None
            if payload.get("type") == "external":
                url = payload["external"].get("url")
            elif payload.get("type") == "file":
                url = payload["file"].get("url")

            if btype == "image" and url:
                alt = caption if caption.strip() else "image"
                lines.append(f"![{alt}]({url})")
            elif url:
                label = caption.strip() or btype
                lines.append(f"[{label}]({url})")

        elif btype == "bookmark":
            payload = b.get("bookmark", {})
            url = payload.get("url")
            caption, found = rich_text_to_md(payload.get("caption", []), link_map)
            linked |= found
            label = caption.strip() or url or "bookmark"
            if url:
                lines.append(f"[{label}]({url})")

        elif btype == "table":
            # Notion tables are blocks with child rows.
            # We'll do a basic HTML table fallback (widely compatible in Markdown renderers).
            rows = b.get("_children", []) or []
            html_lines = ["<table>"]
            for row in rows:
                if row.get("type") != "table_row":
                    continue
                cells = row.get("table_row", {}).get("cells", [])
                html_lines.append("<tr>")
                for cell in cells:
                    cell_md, found = rich_text_to_md(cell, link_map)
                    linked |= found
                    html_lines.append(f"<td>{cell_md}</td>")
                html_lines.append("</tr>")
            html_lines.append("</table>")
            lines.extend(html_lines)

        else:
            # Fallback: try to render any rich_text we can find
            payload = b.get(btype, {}) if btype else {}
            rt = payload.get("rich_text", []) if isinstance(payload, dict) else []
            text, found = rich_text_to_md(rt, link_map)
            linked |= found
            if text.strip():
                lines.append(text)

            child_res = render_children()
            linked |= child_res.linked_pages
            if child_res.md.strip():
                lines.append(child_res.md)

    md = "\n".join(lines).rstrip() + "\n"
    return RenderResult(md=md, linked_pages=linked)


# ----------------------------
# Notion fetching
# ----------------------------


def fetch_all_block_children(notion: Client, block_id: str) -> List[Dict[str, Any]]:
    """
    Get all children blocks for a block/page, handling pagination.
    """
    results: List[Dict[str, Any]] = []
    cursor = None

    while True:

        def call():
            return notion.blocks.children.list(block_id=block_id, start_cursor=cursor, page_size=100)

        resp = with_retry(call)
        results.extend(resp.get("results", []))
        if resp.get("has_more"):
            cursor = resp.get("next_cursor")
        else:
            break

    return results


def hydrate_children(notion: Client, blocks: List[Dict[str, Any]]) -> None:
    """
    Recursively fetch children for blocks that have_children.
    Store children in block["_children"] to avoid changing rendering signatures.
    """
    for b in blocks:
        if b.get("has_children"):
            bid = b.get("id")
            if not bid:
                continue
            kids = fetch_all_block_children(notion, bid)
            b["_children"] = kids
            hydrate_children(notion, kids)


def detect_id_type(notion: Client, id_str: str) -> str:
    """
    Detect if an ID is a page or database.
    Returns 'page', 'database', or raises an error.
    """
    # Try as page first
    try:
        def call_page():
            return notion.pages.retrieve(page_id=id_str)
        with_retry(call_page)
        return "page"
    except APIResponseError as e:
        if "is a database" in str(e).lower():
            return "database"
        # Try as database directly
        pass

    try:
        def call_db():
            return notion.databases.retrieve(database_id=id_str)
        with_retry(call_db)
        return "database"
    except APIResponseError:
        pass

    raise ValueError(f"Could not identify {id_str} as a page or database. Make sure it's shared with your integration.")


def get_database_pages(notion: Client, database_id: str) -> List[str]:
    """
    Query a database and return all page IDs within it.
    """
    results: List[str] = []
    cursor = None

    while True:
        def call():
            return notion.databases.query(
                database_id=database_id,
                start_cursor=cursor,
                page_size=100,
            )

        resp = with_retry(call)
        for item in resp.get("results", []):
            if item.get("object") == "page":
                results.append(item["id"])

        if resp.get("has_more"):
            cursor = resp.get("next_cursor")
        else:
            break

    return results


def get_page_title(notion: Client, page_id: str) -> Optional[str]:
    """
    Retrieve a page and extract its title property.
    Returns None if the page is inaccessible (404/403).
    """

    def call():
        return notion.pages.retrieve(page_id=page_id)

    try:
        page = with_retry(call)
    except APIResponseError as e:
        status = getattr(e, "status", None)
        if status in (403, 404):
            print(f"  [SKIP] Cannot access page {page_id}: {e}")
            return None
        raise

    props = page.get("properties", {}) or {}

    # Find the title property (type == "title")
    for _, prop in props.items():
        if isinstance(prop, dict) and prop.get("type") == "title":
            title_arr = prop.get("title", [])
            title = "".join([t.get("plain_text", "") for t in title_arr])
            return title.strip() or "Untitled"

    return "Untitled"


# ----------------------------
# Crawl + export
# ----------------------------


@dataclass
class PageExport:
    page_id: str
    title: str
    filename: str
    md_raw: str
    forward_links: Set[str]


def export_graph(
    notion: Client,
    root_id: str,
    out_dir: str,
    rewrite_links: bool = True,
) -> Dict[str, PageExport]:
    os.makedirs(out_dir, exist_ok=True)

    visited: Set[str] = set()
    skipped: Set[str] = set()
    queue: List[str] = []

    exports: Dict[str, PageExport] = {}

    # Detect if root is a page or database
    id_type = detect_id_type(notion, root_id)
    print(f"Detected root as: {id_type}")

    if id_type == "database":
        # Query all pages in the database
        print("Fetching pages from database...")
        db_pages = get_database_pages(notion, root_id)
        print(f"Found {len(db_pages)} pages in database")
        queue.extend(db_pages)
    else:
        queue.append(root_id)

    # First pass: crawl pages, collect raw markdown + link graph, pick filenames
    while queue:
        pid = queue.pop(0).lower()
        if pid in visited or pid in skipped:
            continue
        visited.add(pid)

        title = get_page_title(notion, pid)
        if title is None:
            # Page is inaccessible, skip it
            skipped.add(pid)
            visited.discard(pid)  # allow it to be skipped in link rewriting
            continue

        print(f"  Exporting: {title}")

        # Fetch page blocks (page content is stored as block children)
        blocks = fetch_all_block_children(notion, pid)
        hydrate_children(notion, blocks)

        # Temporarily empty link map for placeholders; we'll rewrite later
        render = blocks_to_md(blocks, link_map={})
        md_raw = render.md
        forward = set(x.lower() for x in render.linked_pages if x)

        filename = safe_filename(title, pid)

        exports[pid] = PageExport(
            page_id=pid,
            title=title,
            filename=filename,
            md_raw=md_raw,
            forward_links=forward,
        )

        # Enqueue newly discovered pages
        for fpid in forward:
            if fpid not in visited and fpid not in skipped:
                queue.append(fpid)

    # Build link map page_id -> filename
    link_map = {pid: exp.filename for pid, exp in exports.items()}

    # Second pass: write files, rewriting placeholders
    for pid, exp in exports.items():
        md = exp.md_raw

        if rewrite_links:
            # Replace {PAGE:<pid>} placeholders with relative links or notion URLs fallback
            md = replace_page_placeholders(md, link_map)

        # Prepend a small front-matter-ish header (optional; comment out if you don’t want it)
        header = f"<!-- Exported from Notion page: {pid} -->\n"
        content = header + md

        path = os.path.join(out_dir, exp.filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    return exports


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root-url", required=True, help="Root Notion page URL or page id")
    ap.add_argument("--out", default="./notion_export", help="Output folder")
    ap.add_argument("--token", default=os.getenv("NOTION_TOKEN"), help="Notion integration token (or env NOTION_TOKEN)")
    ap.add_argument("--notion-version", default=os.getenv("NOTION_VERSION", NOTION_VERSION_DEFAULT))
    ap.add_argument("--no-rewrite-links", action="store_true", help="Do not rewrite page links to relative paths")
    args = ap.parse_args()

    if not args.token:
        raise SystemExit("Missing Notion token. Provide --token or set NOTION_TOKEN env var.")

    root_page_id = normalize_page_id(args.root_url)

    notion = Client(auth=args.token, notion_version=args.notion_version)

    exports = export_graph(
        notion=notion,
        root_id=root_page_id,
        out_dir=args.out,
        rewrite_links=not args.no_rewrite_links,
    )

    print(f"Exported {len(exports)} pages to: {os.path.abspath(args.out)}")
    # Print an index file for convenience
    index_path = os.path.join(args.out, "_INDEX.md")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write("# Notion Export Index\n\n")
        for pid, exp in sorted(exports.items(), key=lambda kv: kv[1].title.lower()):
            f.write(f"- [{exp.title}](./{exp.filename})\n")
    print(f"Wrote index: {index_path}")


if __name__ == "__main__":
    main()
