"""URL 정규화와 '같은 사이트인지' 판정.

크롤러가 같은 페이지를 두 번 방문하지 않도록, 그리고 외부 사이트로 빠져나가지 않도록
URL을 일정한 형태로 맞추는 함수들이다. 브라우저 없이 동작하므로 단위 테스트하기 쉽다.
"""

from urllib.parse import urljoin, urlsplit, urlunsplit

# 페이지가 아니라 파일 다운로드로 이어지는 확장자 → 크롤링 대상에서 제외
SKIP_EXTENSIONS = {
    ".pdf", ".hwp", ".hwpx", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".rar", ".7z", ".egg", ".alz", ".exe", ".msi", ".apk",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico",
    ".mp3", ".mp4", ".avi", ".wmv", ".mov", ".css", ".js", ".xml", ".txt",
}

# 크롤링할 수 없는 링크 스킴
SKIP_SCHEMES = ("javascript:", "mailto:", "tel:", "sms:", "data:", "about:", "blob:")


def normalize_url(url: str, base: str = "") -> str:
    """상대 경로를 절대 경로로 바꾸고, 비교하기 쉬운 형태로 정리한다.

    - '#앵커' 제거 (같은 페이지이므로)
    - 스킴·호스트 소문자화
    - 기본 포트(:80, :443) 제거
    - 경로가 비어 있으면 '/'
    - 쿼리스트링은 유지 (게시판은 ?nttId=123 처럼 쿼리로 글을 구분하므로)

    크롤링할 수 없는 링크면 빈 문자열을 돌려준다.
    """
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
    """URL에서 호스트 이름만 꺼낸다. (포트 제외, 소문자)"""
    return (urlsplit(url).hostname or "").lower()


def _strip_www(host: str) -> str:
    return host[4:] if host.startswith("www.") else host


def is_same_site(url: str, start_url: str, include_subdomains: bool = True) -> bool:
    """url이 시작 URL과 같은 사이트인지 판정.

    include_subdomains=True 이면
        시작: www.example.go.kr  →  example.go.kr, board.example.go.kr 도 같은 사이트
    include_subdomains=False 이면 호스트가 완전히 같아야 한다.
    """
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
    """다운로드 파일이 아닌 일반 웹 페이지로 보이면 True."""
    path = urlsplit(url).path.lower()
    dot = path.rfind(".")
    if dot == -1 or "/" in path[dot:]:
        return True
    return path[dot:] not in SKIP_EXTENSIONS
