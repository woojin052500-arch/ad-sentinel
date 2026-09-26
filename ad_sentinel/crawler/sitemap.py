import gzip
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

from playwright.sync_api import APIRequestContext, Error as PlaywrightError

log = logging.getLogger(__name__)

MAX_SITEMAP_FILES = 30
MAX_BYTES = 20 * 1024 * 1024
SITEMAP_CANDIDATES = ["/sitemap.xml", "/sitemap_index.xml", "/all/sitemap.xml"]
FEED_CANDIDATES = ["/rss", "/feed", "/rss.xml"]
FEED_ENOUGH = 50


@dataclass
class Discovery:
    pages: list[str] = field(default_factory=list)
    titles: dict[str, str] = field(default_factory=dict)
    sources: list[dict] = field(default_factory=list)

    def add(self, url: str, title: str = "") -> None:
        if url not in self.titles:
            self.pages.append(url)
            self.titles[url] = title
        elif title and not self.titles[url]:
            self.titles[url] = title


def _get(request: APIRequestContext, url: str, timeout_ms: int) -> bytes | None:
    try:
        response = request.get(url, timeout=timeout_ms, fail_on_status_code=False, max_redirects=5)
    except PlaywrightError as e:
        log.debug("sitemap 요청 실패 %s: %s", url, e)
        return None
    if not response.ok:
        return None
    body = response.body()[:MAX_BYTES]
    if body[:2] == b"\x1f\x8b":
        try:
            body = gzip.decompress(body)
        except OSError:
            return None
    return body


def sitemap_locations(robots_txt: str, base: str) -> list[str]:
    found = []
    for line in robots_txt.splitlines():
        name, _, value = line.partition(":")
        if name.strip().lower() == "sitemap" and value.strip():
            url = urljoin(base, value.strip())
            if url not in found:
                found.append(url)
    return found


def _local(tag: str) -> str:
    return tag.split("}")[-1].lower()


def _child_text(el: ET.Element, name: str) -> str:
    for child in el:
        if _local(child.tag) == name:
            return (child.text or "").strip()
    return ""


def parse_document(data: bytes, base: str) -> tuple[str, list[tuple[str, str]], list[str]]:
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return "", [], []
    kind = _local(root.tag)
    if kind == "sitemapindex":
        locs = [urljoin(base, (el.text or "").strip()) for el in root.iter() if _local(el.tag) == "loc"]
        return "sitemap", [], [u for u in locs if u.startswith("http")]
    if kind == "urlset":
        locs = [urljoin(base, (el.text or "").strip()) for el in root.iter() if _local(el.tag) == "loc"]
        return "sitemap", [(u, "") for u in locs if u.startswith("http")], []
    if kind in ("rss", "rdf"):
        items = []
        for item in root.iter():
            if _local(item.tag) != "item":
                continue
            link = _child_text(item, "link")
            if not link:
                guid = next((c for c in item if _local(c.tag) == "guid"), None)
                if guid is not None and guid.get("isPermaLink", "true") != "false":
                    link = (guid.text or "").strip()
            if link:
                items.append((urljoin(base, link), _child_text(item, "title")))
        return "rss", [(u, t) for u, t in items if u.startswith("http")], []
    if kind == "feed":
        items = []
        for entry in root:
            if _local(entry.tag) != "entry":
                continue
            href = ""
            for link in entry:
                if _local(link.tag) == "link" and link.get("rel", "alternate") == "alternate":
                    href = link.get("href", "")
                    break
            if href:
                items.append((urljoin(base, href), _child_text(entry, "title")))
        return "atom", [(u, t) for u, t in items if u.startswith("http")], []
    return "", [], []


def parse_sitemap(data: bytes, base: str) -> tuple[list[str], list[str]]:
    _, pages, children = parse_document(data, base)
    return [u for u, _ in pages], children


def discover(request: APIRequestContext, start_url: str, max_urls: int, explicit: list[str] | None = None,
             timeout_ms: int = 10000) -> Discovery:
    parts = urlsplit(start_url)
    origin = f"{parts.scheme}://{parts.netloc}"
    result = Discovery()
    visited: set[str] = set()

    def read(url: str, source: str) -> None:
        queue = [url]
        while queue and len(visited) < MAX_SITEMAP_FILES and len(result.pages) < max_urls:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            data = _get(request, current, timeout_ms)
            if not data:
                continue
            kind, pages, children = parse_document(data, current)
            if not kind:
                continue
            before = len(result.pages)
            for page, title in pages:
                if len(result.pages) >= max_urls:
                    break
                result.add(page, title)
            result.sources.append({"url": current, "type": kind, "source": source,
                                   "urls": len(result.pages) - before})
            queue.extend(c for c in children if c not in visited)

    for url in explicit or []:
        read(urljoin(origin + "/", url.strip()), "지정")
    robots = _get(request, origin + "/robots.txt", timeout_ms)
    for url in sitemap_locations(robots.decode("utf-8", errors="ignore"), origin + "/") if robots else []:
        read(url, "robots.txt")
    for path in SITEMAP_CANDIDATES:
        read(origin + path, "자동 탐색")
    if len(result.pages) < FEED_ENOUGH:
        for path in FEED_CANDIDATES:
            read(origin + path, "자동 탐색")
    return result
