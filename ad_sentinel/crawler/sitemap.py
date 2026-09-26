import gzip
import logging
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlsplit

from playwright.sync_api import APIRequestContext, Error as PlaywrightError

log = logging.getLogger(__name__)

MAX_SITEMAP_FILES = 30
MAX_BYTES = 20 * 1024 * 1024


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


def parse_sitemap(data: bytes, base: str) -> tuple[list[str], list[str]]:
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return [], []
    locs = [urljoin(base, (el.text or "").strip()) for el in root.iter() if el.tag.split("}")[-1] == "loc"]
    locs = [u for u in locs if u.startswith("http")]
    if root.tag.split("}")[-1] == "sitemapindex":
        return [], locs
    return locs, []


def discover(request: APIRequestContext, start_url: str, max_urls: int, timeout_ms: int = 10000) -> tuple[list[str], list[str]]:
    parts = urlsplit(start_url)
    origin = f"{parts.scheme}://{parts.netloc}"
    robots = _get(request, origin + "/robots.txt", timeout_ms)
    queue = sitemap_locations(robots.decode("utf-8", errors="ignore"), origin + "/") if robots else []
    if not queue:
        queue = [origin + "/sitemap.xml", origin + "/sitemap_index.xml"]

    pages: list[str] = []
    used: list[str] = []
    visited: set[str] = set()
    while queue and len(visited) < MAX_SITEMAP_FILES and len(pages) < max_urls:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        data = _get(request, url, timeout_ms)
        if not data:
            continue
        found, children = parse_sitemap(data, url)
        if found or children:
            used.append(url)
        queue.extend(c for c in children if c not in visited)
        for page in found:
            if page not in pages:
                pages.append(page)
    return pages[:max_urls], used
