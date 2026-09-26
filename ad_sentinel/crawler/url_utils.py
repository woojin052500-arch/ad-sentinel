import re
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

SKIP_EXTENSIONS = {
    ".pdf", ".hwp", ".hwpx", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".rar", ".7z", ".egg", ".alz", ".exe", ".msi", ".apk",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico",
    ".mp3", ".mp4", ".avi", ".wmv", ".mov", ".css", ".js", ".xml", ".txt",
}

SKIP_SCHEMES = ("javascript:", "mailto:", "tel:", "sms:", "data:", "about:", "blob:")


def normalize_url(url: str, base: str = "") -> str:
    url = (url or "").strip()
    if not url or url.lower().startswith(SKIP_SCHEMES) or url.startswith("#"):
        return ""

    absolute = urljoin(base, url) if base else url
    parts = urlsplit(absolute)
    if parts.scheme not in ("http", "https"):
        return ""

    host = (parts.hostname or "").lower()
    if not host:
        return ""
    port = parts.port
    if port and not ((parts.scheme == "http" and port == 80) or (parts.scheme == "https" and port == 443)):
        host = f"{host}:{port}"

    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), host, path, parts.query, ""))


def get_host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _strip_www(host: str) -> str:
    return host[4:] if host.startswith("www.") else host


def is_same_site(url: str, start_url: str, include_subdomains: bool = True) -> bool:
    host = get_host(url)
    base = get_host(start_url)
    if not host or not base:
        return False
    if host == base:
        return True
    if not include_subdomains:
        return False

    root = _strip_www(base)
    return host == root or host.endswith("." + root)


def is_crawlable(url: str) -> bool:
    path = urlsplit(url).path.lower()
    dot = path.rfind(".")
    if dot == -1 or "/" in path[dot:]:
        return True
    return path[dot:] not in SKIP_EXTENSIONS


UNSAFE_URL = re.compile(
    r"log_?out|sign_?out|delete|remove|destroy|withdraw|unsubscribe|unregister|"
    r"[/_.?&=-]del[/_.?&=-]|[?&](act|mode|cmd|action|proc)=(del|delete|remove|drop|out)\b|"
    r"삭제|탈퇴|로그아웃",
    re.IGNORECASE,
)


def is_safe_to_visit(url: str) -> bool:
    return not UNSAFE_URL.search(unquote(url))
