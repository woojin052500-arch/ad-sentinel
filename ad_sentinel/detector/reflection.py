import re
from urllib.parse import unquote_to_bytes, urlsplit

from ad_sentinel.detector.domains import suspicious_domain
from ad_sentinel.detector.keywords import find_keywords


def _decode(raw: str) -> str:
    data = unquote_to_bytes(raw.replace("+", " "))
    for encoding in ("utf-8", "cp949"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="replace")


def query_params(url: str) -> list[tuple[str, str]]:
    params = []
    for part in urlsplit(url or "").query.split("&"):
        if not part:
            continue
        name, _, raw = part.partition("=")
        value = _decode(raw).strip()
        if value:
            params.append((_decode(name), value))
    return params


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def is_suspicious_value(value: str) -> bool:
    return bool(find_keywords(value)) or bool(suspicious_domain(urlsplit(value).hostname or value))


def reflected_params(params: list[tuple[str, str]], content: str) -> list[dict]:
    text = _compact(content)
    hits = []
    for name, value in params:
        compact = _compact(value)
        if len(compact) >= 2 and compact in text and is_suspicious_value(value):
            hit = {"name": name, "value": value}
            if hit not in hits:
                hits.append(hit)
    return hits


SEARCH_PARAM_NAMES = {"q", "s", "query", "keyword", "keywords", "kwd", "kw", "search", "term", "text", "word",
                      "find", "stx", "sw", "searchword", "searchwrd", "searchkeyword", "searchtext", "searchtxt",
                      "srchwrd", "schword", "schtext", "qt"}
SEARCH_PARAM_PARTS = ("search", "srch", "keyword", "query", "sch")


def is_search_param(name: str) -> bool:
    name = name.lower()
    return name in SEARCH_PARAM_NAMES or any(part in name for part in SEARCH_PARAM_PARTS)


def strip_values(text: str, values: list[str]) -> str:
    for value in values:
        pattern = r"\s*".join(re.escape(c) for c in _compact(value))
        if pattern:
            text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    return text
