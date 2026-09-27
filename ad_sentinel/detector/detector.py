import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from ad_sentinel import __version__
from ad_sentinel.crawler.url_utils import get_host, is_same_site
from ad_sentinel.detector.domains import is_whitelisted, load_whitelist, suspicious_domain
from ad_sentinel.detector.keywords import (find_contact, find_keyword_spans, find_keywords, has_contact,
                                           is_prevention_context)
from ad_sentinel.detector.variants import analyze, evidence_label, normalize
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
POINTS_TELEGRAM = 2
POINTS_CLOAKING = 3
POINTS_CLOAKING_DIFF = 1
CLOAKING_SIMILARITY = 0.5
POINTS_SEARCH_LIST = 2
POINTS_STUFFING = 3
POINTS_STUFFING_DENSITY = 2
POINTS_STUFFING_LIST = 2

STUFFING_MIN_COUNT = 20
STUFFING_MIN_KINDS = 3
STUFFING_MIN_REPEAT = 2.0
STUFFING_DENSITY = 0.2
STUFFING_LIST_LINES = 3
STUFFING_LINE_RATIO = 0.5
HIDDEN_LOCATION_LABELS = {
    "meta": "검색엔진용 정보({field})에만 들어 있음",
    "alt": "이미지 대체 텍스트(alt)에 들어 있음",
    "noscript": "noscript 안(스크립트가 꺼진 환경·검색엔진에만 보임)",
}

REFLECTION = "param_reflection"
SURFACE = "reflection_surface"
REDIRECT = "redirect"
HIDDEN = "hidden"
VISIBLE = "visible"
SEARCH_LIST = "search_list"
STUFFING = "stuffing"
CLOAKING = "cloaking"
PATTERN_LABELS = {
    REFLECTION: "URL 파라미터 반사",
    SURFACE: "악용 가능 지점",
    REDIRECT: "자동 이동",
    CLOAKING: "클로킹 의심",
    STUFFING: "키워드 도배",
    SEARCH_LIST: "검색어 목록 오염",
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
    SEARCH_LIST: "사이트 내 검색어 목록(인기·최근 검색어 등)에 광고 문구가 올라 있습니다. 광고 문구를 반복 검색해 목록과 "
                 "검색엔진에 노출시키는 수법입니다. 해당 검색어를 삭제하고 금칙어(텔레그램 ID, 마약·환전 용어 등) 필터와 "
                 "검색어 목록 자동 노출 여부를 점검하세요.",
    STUFFING: "광고 키워드가 부자연스럽게 반복된 페이지로, 해킹으로 만들어진 스팸 페이지(해킹 생성 페이지)일 수 있습니다. "
              "서버의 파일·게시물 생성 이력과 관리자 계정을 점검하고, 페이지를 삭제한 뒤 검색엔진에 삭제를 요청하세요.",
    CLOAKING: "접속하는 방식(구글봇, 구글 검색 경유, 모바일)에 따라 다른 내용을 보여 주는 클로킹이 의심됩니다. 관리자가 "
              "주소를 직접 입력하면 정상으로 보여 발견이 어렵습니다. 서버 설정(.htaccess 등)과 페이지·스크립트 파일의 변조 "
              "여부를 점검하고, 구글 서치 콘솔의 'URL 검사'로 구글이 보는 화면도 확인하세요.",
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
            if page.get("error_page"):
                add("page", page["url"], page["url"], [], f"오류 페이지로 열림({page['error_page']})")
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
        for screen in self.crawl.get("meta", {}).get("repeated_screens") or []:
            for url in screen["urls"][1:]:
                add("page", url, url, [], f"다른 주소와 똑같은 화면('{screen['title'] or '제목 없음'}')이 나와 "
                                          "실제 내용이 점검되지 않았을 수 있음")
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
            "duplicate_pages": sum(d["count"] - 1 for d in meta.get("duplicate_screens") or []),
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
            if e["type"] == "link" and e.get("href") and not e.get("hidden"):
                parts = e["selector"].split(" > ")
                for i in range(1, len(parts)):
                    key = (tuple(e.get("frame_path", [])), " > ".join(parts[:i]))
                    if len(child_links[key]) < MAX_CHILD_LINKS:
                        child_links[key].append(e["href"])

        prevention_page = is_prevention_context(" ".join([page.get("title") or "", page.get("listed_title") or ""]))
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
            finding = self.score(rec, in_hidden_frame, params, prevention_page)
            if finding:
                finding["page_url"] = page["url"]
                finding["page_title"] = page.get("listed_title") or page.get("title") or ""
                finding["post_title"] = finding["context_title"] or page.get("listed_title") or ""
                results.append(finding)

        if page.get("offsite_redirect") and page.get("final_url") and not self.is_trusted(page["final_url"]):
            evidence = [_ev("redirect", f"다른 사이트로 자동 이동: {get_host(page['final_url'])}", POINTS_REDIRECT),
                        _ev("external", "화이트리스트에 없는 외부 도메인", POINTS_EXTERNAL)]
            category = suspicious_domain(get_host(page["final_url"])) or "기타"
            finding = self._finding({"type": "page_redirect", "selector": "", "content": page["final_url"],
                                     "frame_path": [], "frame_url": page["url"]}, evidence, [category], page["url"])
            if finding:
                results.append(finding)

        stuffing = self._stuffing(page)
        if stuffing:
            merged = [f for f in results if f["pattern"] == VISIBLE
                      and all(e["kind"] in ("keyword", "variant") for e in f["evidence"])]
            stuffing["stuffing"]["merged"] = len(merged)
            stuffing["stuffing"]["examples"] = [f["content"][:80] for f in merged[:5]]
            results = [f for f in results if f not in merged] + [stuffing]
        if page.get("cloaking"):
            results.extend(self._cloaking(page))

        return _drop_descendants(results)

    def _cloaking(self, page: dict) -> list[dict]:
        profiles = {p["key"]: p for p in page["cloaking"].get("profiles", [])}
        base = profiles.get("pc")
        if not base or base.get("error"):
            return []
        base_text = _snapshot_text(base)
        base_words = {h.keyword.word for h in analyze(base_text)}
        base_hosts = {get_host(u) for u in base.get("links", []) + base.get("redirects", [])}
        base_contact = find_contact(base_text)
        page_host = get_host(page.get("final_url") or page["url"])
        results = []
        for key, snap in profiles.items():
            if key == "pc" or snap.get("error"):
                continue
            text = _snapshot_text(snap)
            new_hits = [h for h in analyze(text) if h.keyword.word not in base_words]
            redirects = [u for u in snap.get("redirects", []) if not self.is_trusted(u) and get_host(u) not in base_hosts]
            final_host = get_host(snap.get("final_url", ""))
            if final_host and final_host != page_host and not self.is_trusted(snap["final_url"]):
                redirects.insert(0, snap["final_url"])
            redirects = list(dict.fromkeys(redirects))
            new_links = [u for u in snap.get("links", []) if not self.is_trusted(u) and get_host(u) not in base_hosts]
            new_hosts = list(dict.fromkeys(get_host(u) for u in new_links))
            suspicious = [h for h in new_hosts if suspicious_domain(h)]
            contact = find_contact(text) if not base_contact else None
            if not (new_hits or redirects or suspicious or (contact and contact[0] == "telegram")):
                continue

            label, only_in = snap["label"], snap["only_in"]
            evidence, categories = [], []
            if new_hits:
                words = ", ".join(h.keyword.word for h in new_hits[:5])
                evidence.append(_ev("cloaking", f"{only_in}: 광고 키워드 {words}", POINTS_CLOAKING))
                for hit in new_hits:
                    evidence.append(_ev("variant" if hit.variant else "keyword", evidence_label(hit), hit.weight))
                    categories.extend([hit.keyword.category] * hit.weight)
            if redirects:
                evidence.append(_ev("cloaking", f"{label} 접속일 때만 다른 사이트로 이동: {get_host(redirects[0])}",
                                    POINTS_CLOAKING))
            bad_hosts = [get_host(u) for u in redirects if suspicious_domain(get_host(u))] + suspicious
            if bad_hosts:
                evidence.append(_ev("domain", f"의심 도메인: {bad_hosts[0]}", POINTS_SUSPICIOUS_DOMAIN))
                categories.extend([suspicious_domain(bad_hosts[0])] * POINTS_SUSPICIOUS_DOMAIN)
            if new_hosts:
                evidence.append(_ev("external", f"{_with_ro(label)} 볼 때만 외부 링크: {', '.join(new_hosts[:3])}",
                                    POINTS_EXTERNAL))
            if contact:
                points = POINTS_TELEGRAM if contact[0] == "telegram" else POINTS_CONTACT
                evidence.append(_ev("contact", f"{_with_ro(label)} 볼 때만 연락처: {contact[1]}", points))
            similarity = _similarity(base_text, text)
            if similarity < CLOAKING_SIMILARITY:
                evidence.append(_ev("cloaking", f"일반 PC 화면과 내용이 크게 다름 (같은 단어 {similarity:.0%})",
                                    POINTS_CLOAKING_DIFF))

            content = _new_ad_text(base, snap, new_hits)
            if not content and redirects:
                content = f"다른 사이트로 이동: {redirects[0]}"
            content = content or _snippet(text, "")
            rec = {"type": "cloaking", "selector": f"[{label}]", "content": content, "frame_path": [],
                   "frame_url": page.get("final_url") or page["url"], "links": (redirects + new_links)[:10]}
            finding = self._finding(rec, evidence, categories or ["기타"], page["url"])
            if finding:
                finding["pattern_label"] = f"{PATTERN_LABELS[CLOAKING]}({label})"
                finding["cloaking"] = {"profile": key, "label": label, "only_in": only_in,
                                       "similarity": round(similarity, 2),
                                       "new_keywords": [h.keyword.word for h in new_hits],
                                       "redirects": redirects, "new_hosts": new_hosts,
                                       "title": snap.get("title", ""), "base_title": base.get("title", "")}
                results.append(finding)
        return results

    def _stuffing(self, page: dict) -> dict | None:
        texts = [f.get("text", "") for f in page.get("frames", []) if f.get("text")]
        texts += [e.get("content", "") for e in page.get("elements", []) if e["type"] == "hidden" and e.get("content")]
        stats = stuffing_stats("\n".join(texts))
        if not stats:
            return None
        evidence = [_ev("stuffing", f"광고 키워드 {stats['kinds']}종이 {stats['count']}회 반복됨", POINTS_STUFFING)]
        if stats["density"] >= STUFFING_DENSITY:
            evidence.append(_ev("stuffing", f"본문 글자의 {stats['density']:.0%}가 광고 키워드", POINTS_STUFFING_DENSITY))
        if stats["list_lines"] >= STUFFING_LIST_LINES:
            evidence.append(_ev("stuffing", f"의미 없이 키워드만 나열한 줄 {stats['list_lines']}개", POINTS_STUFFING_LIST))
        content = (f"키워드 도배(해킹 생성 페이지 의심): {', '.join(stats['top'])} 등 "
                   f"{stats['kinds']}종 {stats['count']}회")
        rec = {"type": "page_stuffing", "selector": "", "content": content, "frame_path": [], "frame_url": page["url"]}
        finding = self._finding(rec, evidence, stats["categories"], page["url"])
        if finding:
            finding["stuffing"] = stats
        return finding

    def score(self, rec: dict, in_hidden_frame: bool = False,
              params: list[tuple[str, str]] | None = None, prevention_page: bool = False) -> dict | None:
        text = rec.get("content", "")
        evidence = []
        categories = []

        for hit in analyze(text):
            kind = "variant" if hit.variant else "keyword"
            evidence.append(_ev(kind, evidence_label(hit), hit.weight))
            categories.extend([hit.keyword.category] * hit.weight)

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

        contact = find_contact(text)
        if (not contact and (prevention_page or is_prevention_context(text))
                and all(e["kind"] in ("keyword", "variant") for e in evidence)
                and rec["type"] in ("text", "title", "link", "meta", "alt") and not rec.get("hidden")
                and not rec.get("search_widget")):
            return None

        if rec.get("search_widget"):
            evidence.append(_ev("search_list", f"사이트 검색어 목록({rec['search_widget']})에 올라 있음",
                                POINTS_SEARCH_LIST))

        if rec["type"] in HIDDEN_LOCATION_LABELS:
            label = HIDDEN_LOCATION_LABELS[rec["type"]].format(field=rec.get("field", ""))
            evidence.append(_ev("hidden", label, POINTS_HIDDEN))
        elif rec["type"] == "hidden" or rec.get("hidden"):
            reasons = ", ".join(rec.get("hidden_reasons", [])) or "숨김 영역 안"
            evidence.append(_ev("hidden", f"숨김 처리 ({reasons})", POINTS_HIDDEN))
        elif in_hidden_frame:
            evidence.append(_ev("hidden", "숨겨진 iframe 내부", POINTS_HIDDEN))

        external_frame = rec.get("frame_url") and not self.is_trusted(rec["frame_url"])
        if untrusted or external_frame:
            evidence.append(_ev("external", "화이트리스트에 없는 외부 도메인", POINTS_EXTERNAL))

        if contact:
            kind, matched = contact
            if kind == "telegram":
                evidence.append(_ev("contact", f"텔레그램 ID 포함 ({matched})", POINTS_TELEGRAM))
            else:
                evidence.append(_ev("contact", f"연락처·메신저 ID 포함 ({matched})", POINTS_CONTACT))

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
        elif "cloaking" in kinds:
            pattern = CLOAKING
        elif "redirect" in kinds:
            pattern = REDIRECT
        elif "stuffing" in kinds:
            pattern = STUFFING
        elif "search_list" in kinds:
            pattern = SEARCH_LIST
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
            "context_title": rec.get("context_title", ""),
            "urls": _urls_of(rec),
            "hidden_reasons": rec.get("hidden_reasons", []),
            "rect": rec.get("rect"),
            "evidence": evidence,
            "reflected_params": [],
            "advice": ADVICE[pattern],
            "page_url": page_url,
        }


def _with_ro(word: str) -> str:
    last = word[-1:] if word else ""
    if "가" <= last <= "힣":
        final = (ord(last) - 0xAC00) % 28
        return word + ("로" if final in (0, 8) else "으로")
    return word + "(으)로"


def _snapshot_text(snap: dict) -> str:
    return "\n".join([snap.get("title", ""), snap.get("text", "")] + snap.get("hidden", []))


def _similarity(a: str, b: str) -> float:
    wa, wb = set(re.findall(r"\w{2,}", a.lower())), set(re.findall(r"\w{2,}", b.lower()))
    if not wa and not wb:
        return 1.0
    return len(wa & wb) / len(wa | wb)


def _new_ad_text(base: dict, snap: dict, hits: list) -> str:
    seen = {" ".join(line.split()) for line in _snapshot_text(base).splitlines()}
    candidates = [snap.get("title", "")] + snap.get("text", "").splitlines() + snap.get("hidden", [])
    fresh = [" ".join(c.split()) for c in candidates if c.strip() and " ".join(c.split()) not in seen]
    words = [h.original for h in hits if h.original] + [h.keyword.word for h in hits]
    for line in fresh:
        if any(w and w.lower() in line.lower() for w in words) or find_contact(line):
            return line[:200]
    return fresh[0][:200] if fresh and hits else ""


def _snippet(text: str, word: str, around: int = 80) -> str:
    flat = " ".join(text.split())
    if not word:
        return flat[:around * 2]
    i = flat.find(word)
    if i < 0:
        return flat[:around * 2]
    start = max(0, i - around // 2)
    return ("…" if start else "") + flat[start:i + len(word) + around].strip()


def stuffing_stats(text: str) -> dict | None:
    norm, _ = normalize(text or "")
    spans = find_keyword_spans(norm)
    if len(spans) < STUFFING_MIN_COUNT:
        return None
    counts = Counter(kw.word for kw, _, _ in spans)
    if len(counts) < STUFFING_MIN_KINDS or len(spans) / len(counts) < STUFFING_MIN_REPEAT:
        return None
    letters = sum(1 for c in norm if c.isalnum())
    keyword_chars = sum(sum(1 for c in norm[a:b] if c.isalnum()) for _, a, b in spans)
    density = keyword_chars / letters if letters else 0
    list_lines = 0
    for line in norm.splitlines():
        line_spans = find_keyword_spans(line)
        line_letters = sum(1 for c in line if c.isalnum())
        covered = sum(sum(1 for c in line[a:b] if c.isalnum()) for _, a, b in line_spans)
        if len(line_spans) >= 3 and line_letters and covered / line_letters >= STUFFING_LINE_RATIO:
            list_lines += 1
    if density < STUFFING_DENSITY and list_lines < STUFFING_LIST_LINES:
        return None
    categories = []
    by_word = {kw.word: kw for kw, _, _ in spans}
    for word, n in counts.items():
        categories.extend([by_word[word].category] * n * by_word[word].weight)
    return {"count": len(spans), "kinds": len(counts), "density": round(density, 3), "list_lines": list_lines,
            "top": [w for w, _ in counts.most_common(5)], "categories": categories}


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


def _is_inside(child: dict, parent: dict) -> bool:
    return (child is not parent and child["frame_path"] == parent["frame_path"] and bool(parent["selector"])
            and child["selector"].startswith(parent["selector"] + " > "))


def _same_spot(findings: list[dict]) -> list[dict]:
    best: dict[tuple, dict] = {}
    for f in findings:
        if not f["selector"]:
            best[(id(f),)] = f
            continue
        key = (tuple(f["frame_path"]), f["selector"])
        current = best.get(key)
        if current is None or (f["score"], f["type"] == "link") > (current["score"], current["type"] == "link"):
            best[key] = f
    return list(best.values())


def _drop_descendants(findings: list[dict]) -> list[dict]:
    findings = _same_spot(findings)
    kept = []
    for f in findings:
        covered_by_parent = any(_is_inside(f, g) and g["score"] >= f["score"] for g in findings)
        covers_stronger_child = any(_is_inside(g, f) and g["score"] > f["score"] for g in findings)
        if not covered_by_parent and not covers_stronger_child:
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
