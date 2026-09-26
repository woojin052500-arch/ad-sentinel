from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from ad_sentinel import __version__
from ad_sentinel.crawler.url_utils import get_host, is_same_site
from ad_sentinel.detector.domains import is_whitelisted, load_whitelist, suspicious_domain
from ad_sentinel.detector.keywords import find_keywords, has_contact
from ad_sentinel.detector.reflection import is_search_param, query_params, reflected_params, strip_values

HIGH = "high"
SUSPECT = "suspect"
LEVEL_LABELS = {HIGH: "불법광고 의심", SUSPECT: "검토 필요"}

POINTS_HIDDEN = 2
POINTS_SUSPICIOUS_DOMAIN = 3
POINTS_REDIRECT = 3
POINTS_EXTERNAL = 1
POINTS_CONTACT = 1
POINTS_REFLECTION = 2

REFLECTION = "param_reflection"
SURFACE = "reflection_surface"
REDIRECT = "redirect"
HIDDEN = "hidden"
VISIBLE = "visible"
PATTERN_LABELS = {
    REFLECTION: "URL 파라미터 반사",
    SURFACE: "악용 가능 지점",
    REDIRECT: "자동 이동",
    HIDDEN: "숨김 광고",
    VISIBLE: "노출 광고",
}
ADVICE = {
    REFLECTION: "주소 파라미터 값이 화면에 그대로 출력되어 광고 문구가 노출됩니다. "
                "입력값을 그대로 출력하지 않도록 조치하고, 검색엔진에 노출된 해당 주소의 삭제를 요청하세요.",
    SURFACE: "입력값을 그대로 출력하지 않도록 조치를 권장합니다. "
             "현재 광고는 아니지만 같은 방식으로 광고 문구를 노출시키는 데 악용될 수 있습니다.",
    REDIRECT: "다른 사이트로 자동 이동시키는 코드가 있습니다. 페이지 소스와 서버 파일의 변조 여부를 점검하세요.",
    HIDDEN: "화면에 보이지 않게 숨겨진 광고입니다. 해당 요소를 삭제하고 게시판·편집기의 입력 필터와 계정 보안을 점검하세요.",
    VISIBLE: "화면에 노출된 광고입니다. 게시글·댓글을 삭제하고 작성 경로(게시판, 댓글 등)의 스팸 차단 설정을 점검하세요.",
}
MAX_CHILD_LINKS = 20
UNCHECKED_LABELS = {"page": "페이지", "iframe": "iframe", "robots": "수집 금지 주소"}


@dataclass
class DetectConfig:
    high_score: int = 5
    suspect_score: int = 4
    min_evidence: int = 2
    extra_whitelist: list[str] = field(default_factory=list)


class Detector:
    def __init__(self, crawl_result: dict, config: DetectConfig | None = None):
        self.crawl = crawl_result
        self.config = config or DetectConfig()
        meta = crawl_result.get("meta", {})
        self.start_url = meta.get("start_url", "")
        seeds = meta.get("seed_urls") or [self.start_url]
        self.seed_count = len(seeds)
        self.site_urls = list({get_host(u): u for u in reversed(seeds)}.values())
        self.include_subdomains = meta.get("config", {}).get("include_subdomains", True)
        self.whitelist = load_whitelist(self.config.extra_whitelist)
        self.external_hosts: Counter = Counter()

    def is_external(self, url: str) -> bool:
        host = get_host(url)
        if not host or not url.startswith("http"):
            return False
        return not any(is_same_site(url, site, self.include_subdomains) for site in self.site_urls)

    def is_trusted(self, url: str) -> bool:
        return not self.is_external(url) or is_whitelisted(get_host(url), self.whitelist)

    def run(self) -> dict:
        page_findings = []
        for page in self.crawl.get("pages", []):
            page_findings.extend(self._page_findings(page))

        findings = _group(page_findings)
        findings.sort(key=lambda f: (f["level"] != HIGH, -f["score"], -f["page_count"]))
        for i, f in enumerate(findings, 1):
            f["id"] = i

        unchecked = self._unchecked_areas()
        stats = self._stats(len(unchecked))
        by_category = Counter(f["category"] for f in findings)
        by_pattern = Counter(f["pattern_label"] for f in findings)
        return {
            "meta": {
                "tool": "AD Sentinel",
                "version": __version__,
                "detected_at": datetime.now().isoformat(timespec="seconds"),
                "start_url": self.start_url,
                "crawl_started_at": self.crawl.get("meta", {}).get("started_at"),
                "page_count": len(self.crawl.get("pages", [])),
                "mode": self.crawl.get("meta", {}).get("mode", "site"),
                "seed_count": self.seed_count,
                "notes": self.crawl.get("meta", {}).get("notes", []),
                "gate": self.crawl.get("meta", {}).get("gate"),
                "sitemap": self.crawl.get("meta", {}).get("sitemap"),
                "config": vars(self.config).copy(),
            },
            "summary": {
                "findings": len(findings),
                "high": sum(1 for f in findings if f["level"] == HIGH),
                "suspect": sum(1 for f in findings if f["level"] == SUSPECT),
                "by_category": dict(by_category),
                "by_pattern": dict(by_pattern),
                "unchecked": len(unchecked),
            },
            "stats": stats,
            "unchecked": unchecked,
            "external_domains": [
                {"host": host, "count": n, "whitelisted": is_whitelisted(host, self.whitelist)}
                for host, n in self.external_hosts.most_common()
            ],
            "findings": findings,
        }

    def _unchecked_areas(self) -> list[dict]:
        groups: dict[tuple, dict] = {}

        def add(kind: str, page_url: str, url: str, frame_path: list, reason: str):
            key = (kind, url, tuple(frame_path), reason)
            if key not in groups:
                host = get_host(url)
                groups[key] = {
                    "kind": kind, "kind_label": UNCHECKED_LABELS[kind], "url": url, "frame_path": list(frame_path),
                    "reason": reason, "host": host,
                    "trusted_domain": bool(host) and is_whitelisted(host, self.whitelist), "pages": [],
                }
            if page_url not in groups[key]["pages"]:
                groups[key]["pages"].append(page_url)

        for page in self.crawl.get("pages", []):
            if page.get("error"):
                add("page", page["url"], page["url"], [], f"페이지를 열지 못함: {page['error']}")
                continue
            for f in page.get("frames", []):
                url = f.get("frame_url") or f.get("src", "") or _iframe_src(page, f.get("frame_path", []))
                kind = "page" if f.get("is_main") else "iframe"
                if f.get("error"):
                    if not f.get("is_main") and f.get("loaded") is False:
                        reason = "iframe이 불러와지지 않아 내용을 확인하지 못함 (숨겨진 탭 안의 iframe 등)"
                    elif f.get("timed_out"):
                        reason = "응답이 없어 제한 시간 안에 내용을 확인하지 못함"
                    else:
                        reason = f"내용을 읽지 못함 ({f['error']})"
                    add(kind, page["url"], url, f.get("frame_path", []), reason)
                elif f.get("total_elements") and f.get("scanned", 0) < f["total_elements"]:
                    add(kind, page["url"], url, f.get("frame_path", []),
                        f"일부만 검사함 (요소 {f['total_elements']}개 중 {f['scanned']}개)")
            for skipped in page.get("frames_skipped", []):
                add("iframe", page["url"], skipped.get("frame_url", ""), [], skipped["reason"])
        for skipped in self.crawl.get("skipped", []):
            add("robots", skipped["url"], skipped["url"], [], "robots.txt에서 수집을 막아 둔 주소라 점검하지 않음")

        result = list(groups.values())
        for item in result:
            item["page_count"] = len(item["pages"])
        return result

    def _stats(self, unchecked_count: int) -> dict:
        pages = self.crawl.get("pages", [])
        frames = [f for p in pages for f in p.get("frames", [])]
        meta = self.crawl.get("meta", {})
        duration = None
        try:
            started = datetime.fromisoformat(meta["started_at"])
            finished = datetime.fromisoformat(meta["finished_at"])
            duration = int((finished - started).total_seconds())
        except (KeyError, TypeError, ValueError):
            pass
        return {
            "pages": len(pages),
            "page_errors": sum(1 for p in pages if p.get("error")),
            "frames": len(frames),
            "iframes": sum(1 for f in frames if not f.get("is_main") and not f.get("error")),
            "elements_scanned": sum(f.get("scanned", 0) for f in frames),
            "unchecked": unchecked_count,
            "duration_sec": duration,
            "stopped_by_user": bool(meta.get("stopped_by_user")),
        }

    def _page_findings(self, page: dict) -> list[dict]:
        elements = page.get("elements", [])
        hidden_frames = {
            tuple(e.get("frame_path", [])) + (e["selector"],)
            for e in elements
            if e["type"] == "iframe" and e.get("hidden")
        }

        page_params = _unique(query_params(page["url"]) + query_params(page.get("final_url", "")))
        main = next((f for f in page.get("frames", []) if f.get("is_main")), None)
        if main and main.get("title"):
            elements = elements + [{"type": "title", "selector": "title", "content": main["title"],
                                    "frame_path": [], "frame_url": main.get("frame_url", page["url"])}]

        child_links: dict[tuple, list[str]] = defaultdict(list)
        for e in elements:
            if e["type"] == "link" and e.get("href"):
                parts = e["selector"].split(" > ")
                for i in range(1, len(parts)):
                    key = (tuple(e.get("frame_path", [])), " > ".join(parts[:i]))
                    if len(child_links[key]) < MAX_CHILD_LINKS:
                        child_links[key].append(e["href"])

        results = []
        for rec in elements:
            for url in _urls_of(rec):
                if self.is_external(url):
                    self.external_hosts[get_host(url)] += 1
            if rec["type"] == "text":
                inner = child_links.get((tuple(rec.get("frame_path", [])), rec["selector"]))
                if inner:
                    rec = {**rec, "links": inner}
            frame_path = tuple(rec.get("frame_path", []))
            in_hidden_frame = any(frame_path[:i] in hidden_frames for i in range(1, len(frame_path) + 1))
            params = page_params if not frame_path else _unique(page_params + query_params(rec.get("frame_url", "")))
            finding = self.score(rec, in_hidden_frame, params)
            if finding:
                finding["page_url"] = page["url"]
                results.append(finding)

        if page.get("offsite_redirect") and page.get("final_url") and not self.is_trusted(page["final_url"]):
            evidence = [_ev("redirect", f"다른 사이트로 자동 이동: {get_host(page['final_url'])}", POINTS_REDIRECT),
                        _ev("external", "화이트리스트에 없는 외부 도메인", POINTS_EXTERNAL)]
            category = suspicious_domain(get_host(page["final_url"])) or "기타"
            finding = self._finding({"type": "page_redirect", "selector": "", "content": page["final_url"],
                                     "frame_path": [], "frame_url": page["url"]}, evidence, [category], page["url"])
            if finding:
                results.append(finding)

        return _drop_descendants(results)

    def score(self, rec: dict, in_hidden_frame: bool = False,
              params: list[tuple[str, str]] | None = None) -> dict | None:
        text = rec.get("content", "")
        evidence = []
        categories = []

        for kw in find_keywords(text):
            evidence.append(_ev("keyword", f"{kw.category} 키워드 '{kw.word}'", kw.weight))
            categories.extend([kw.category] * kw.weight)

        urls = _urls_of(rec)
        untrusted = [u for u in urls if not self.is_trusted(u)]
        for url in untrusted:
            category = suspicious_domain(get_host(url))
            if category:
                evidence.append(_ev("domain", f"의심 도메인: {get_host(url)}", POINTS_SUSPICIOUS_DOMAIN))
                categories.extend([category] * POINTS_SUSPICIOUS_DOMAIN)
                break

        if rec["type"] == "redirect" and untrusted:
            evidence.append(_ev("redirect", "meta refresh 자동 이동", POINTS_REDIRECT))

        if not evidence:
            return None

        if rec["type"] == "hidden" or rec.get("hidden"):
            reasons = ", ".join(rec.get("hidden_reasons", [])) or "숨김 영역 안"
            evidence.append(_ev("hidden", f"숨김 처리 ({reasons})", POINTS_HIDDEN))
        elif in_hidden_frame:
            evidence.append(_ev("hidden", "숨겨진 iframe 내부", POINTS_HIDDEN))

        external_frame = rec.get("frame_url") and not self.is_trusted(rec["frame_url"])
        if untrusted or external_frame:
            evidence.append(_ev("external", "화이트리스트에 없는 외부 도메인", POINTS_EXTERNAL))

        if has_contact(text):
            evidence.append(_ev("contact", "연락처·메신저 ID 포함", POINTS_CONTACT))

        reflected = reflected_params(params or [], text)
        surface = False
        if reflected:
            surface = self._is_surface_only(reflected, text, evidence)
            names = ", ".join(f"{p['name']}={p['value']}" for p in reflected)
            evidence.append(_ev("reflection", f"URL 파라미터 반사 ({names})", POINTS_REFLECTION))

        finding = self._finding(rec, evidence, categories or ["기타"], "")
        if finding:
            finding["reflected_params"] = reflected
            if surface:
                finding.update(level=SUSPECT, level_label=LEVEL_LABELS[SUSPECT], pattern=SURFACE,
                               pattern_label=PATTERN_LABELS[SURFACE], advice=ADVICE[SURFACE])
        return finding

    def _is_surface_only(self, reflected: list[dict], text: str, evidence: list[dict]) -> bool:
        if not all(is_search_param(p["name"]) for p in reflected):
            return False
        if any(e["kind"] in ("domain", "hidden", "redirect") for e in evidence):
            return False
        values = [p["value"] for p in reflected]
        outside = strip_values(text, values)
        if find_keywords(outside) or has_contact(outside):
            return False
        payload_keywords = {kw.word for v in values for kw in find_keywords(v)}
        payload_is_ad = len(payload_keywords) >= 2 or any(has_contact(v) for v in values)
        return not payload_is_ad

    def _finding(self, rec: dict, evidence: list[dict], categories: list[str], page_url: str) -> dict | None:
        cfg = self.config
        score = sum(e["points"] for e in evidence)
        if len(evidence) < cfg.min_evidence or score < cfg.suspect_score:
            return None
        level = HIGH if score >= cfg.high_score else SUSPECT
        kinds = {e["kind"] for e in evidence}
        if "reflection" in kinds:
            pattern = REFLECTION
        elif "redirect" in kinds:
            pattern = REDIRECT
        elif "hidden" in kinds:
            pattern = HIDDEN
        else:
            pattern = VISIBLE
        return {
            "level": level,
            "level_label": LEVEL_LABELS[level],
            "score": score,
            "pattern": pattern,
            "pattern_label": PATTERN_LABELS[pattern],
            "category": Counter(categories).most_common(1)[0][0],
            "type": rec["type"],
            "content": rec.get("content", ""),
            "selector": rec.get("selector", ""),
            "frame_path": rec.get("frame_path", []),
            "frame_url": rec.get("frame_url", ""),
            "urls": _urls_of(rec),
            "hidden_reasons": rec.get("hidden_reasons", []),
            "rect": rec.get("rect"),
            "evidence": evidence,
            "reflected_params": [],
            "advice": ADVICE[pattern],
            "page_url": page_url,
        }


def _iframe_src(page: dict, frame_path: list[str]) -> str:
    if not frame_path:
        return ""
    for e in page.get("elements", []):
        if e["type"] == "iframe" and e["selector"] == frame_path[-1] and e.get("frame_path", []) == frame_path[:-1]:
            return e.get("src", "")
    return ""


def _unique(params: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return list(dict.fromkeys(params))


def _ev(kind: str, label: str, points: int) -> dict:
    return {"kind": kind, "label": label, "points": points}


def _urls_of(rec: dict) -> list[str]:
    urls = []
    if rec["type"] == "link" and rec.get("href"):
        urls.append(rec["href"])
    if rec["type"] == "iframe" and rec.get("src"):
        urls.append(rec["src"])
    if rec["type"] == "redirect":
        content = rec.get("content", "")
        if "url=" in content.lower():
            urls.append(content[content.lower().index("url=") + 4:].strip(" '\""))
    urls.extend(rec.get("links", []))
    return [u for u in dict.fromkeys(urls) if u.startswith("http")]


def _drop_descendants(findings: list[dict]) -> list[dict]:
    kept = []
    for f in findings:
        prefix_of = [
            g for g in findings
            if g is not f and g["frame_path"] == f["frame_path"] and g["selector"]
            and f["selector"].startswith(g["selector"] + " > ")
        ]
        if not prefix_of:
            kept.append(f)
    return kept


def _group(findings: list[dict]) -> list[dict]:
    groups: dict[tuple, dict] = {}
    pages: dict[tuple, list[str]] = defaultdict(list)
    for f in findings:
        key = (tuple(f["frame_path"]), f["selector"], f["content"], f["type"])
        if key not in groups:
            groups[key] = {k: v for k, v in f.items() if k != "page_url"}
        if f["page_url"] not in pages[key]:
            pages[key].append(f["page_url"])
    result = []
    for key, f in groups.items():
        f["pages"] = pages[key]
        f["page_count"] = len(pages[key])
        f["location_label"] = f"{f['page_count']}개 페이지에서 발견" if f["page_count"] > 1 else pages[key][0]
        result.append(f)
    return result


def detect(crawl_result: dict, config: DetectConfig | None = None) -> dict:
    return Detector(crawl_result, config).run()
