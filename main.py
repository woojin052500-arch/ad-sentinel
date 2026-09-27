import argparse
import logging
import sys

from ad_sentinel.config import CrawlConfig
from ad_sentinel.crawler import Crawler
from ad_sentinel.detector import DetectConfig, detect
from ad_sentinel.paths import output_dir
from ad_sentinel.storage import load_json, save_json
from ad_sentinel.url_list import load_url_list


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="AD-Sentinel", description="공공 웹사이트 불법광고 탐지 도구")
    p.add_argument("url", nargs="?", help="탐색을 시작할 URL")
    p.add_argument("--url-list", default=None, help="URL 목록 점검: txt/csv/서치 콘솔 내보내기(zip) 파일의 주소만 점검")
    p.add_argument("--from-json", default=None, help="크롤링 없이 기존 크롤링 결과 JSON으로 탐지만 실행")
    p.add_argument("--max-pages", type=int, default=30, help="최대 방문 페이지 수 (기본 30)")
    p.add_argument("--depth", type=int, default=3, help="링크를 따라갈 최대 깊이 (기본 3)")
    p.add_argument("--page-timeout", type=float, default=60, help="페이지 하나의 전체 제한 시간(초) (기본 60)")
    p.add_argument("--delay", type=float, default=1.0, help="페이지 사이 요청 간격(초) (기본 1.0, 차단 시 자동으로 늘어남)")
    p.add_argument("--out", default=None, help="크롤링 결과 JSON 경로 (기본: output/crawl_날짜_시간.json)")
    p.add_argument("--report", default=None, help="탐지 결과 JSON 경로 (기본: output/detect_날짜_시간.json)")
    p.add_argument("--whitelist", nargs="*", default=[], help="추가로 신뢰할 도메인 (예: example.com)")
    p.add_argument("--same-host-only", action="store_true", help="하위 도메인은 탐색하지 않음")
    p.add_argument("--no-gate", action="store_true", help="첫 화면의 '입장' 버튼을 자동으로 누르지 않음")
    p.add_argument("--no-sitemap", action="store_true", help="sitemap.xml·RSS를 자동으로 찾지 않음")
    p.add_argument("--sitemap", action="append", default=[], metavar="URL",
                   help="sitemap 또는 RSS/Atom 주소 직접 지정 (여러 번 사용 가능)")
    p.add_argument("--ignore-robots", action="store_true",
                   help="내가 관리하는 사이트 점검: robots.txt 제한을 무시 (권한 있는 사이트에만 사용)")
    p.add_argument("--show-browser", action="store_true", help="브라우저 창을 띄워서 실행")
    p.add_argument("--cloaking", choices=["off", "suspect", "all"], default="off",
                   help="클로킹 검사: 구글봇·구글 검색 경유·모바일로도 열어 비교 (suspect=첫 페이지·의심 페이지만, all=모든 페이지)")
    p.add_argument("--screenshots", action="store_true",
                   help="진단용: 입장 버튼 클릭 직후와 대기 종료 시점 화면을 output/screenshots에 저장")
    p.add_argument("--browser", default="", help="브라우저 실행 파일 경로 (기본: 자동 탐색)")
    args = p.parse_args(argv)
    if not args.url and not args.from_json and not args.url_list:
        p.error("URL, --url-list, --from-json 중 하나가 필요합니다.")
    return args


def crawl(args) -> dict | None:
    url_list = load_url_list(args.url_list) if args.url_list else []
    if args.url_list:
        print(f"목록 파일에서 주소 {len(url_list)}개를 읽었습니다.")
    config = CrawlConfig(
        start_url=args.url or "",
        url_list=url_list,
        max_pages=args.max_pages,
        max_depth=args.depth,
        delay_sec=args.delay,
        page_total_timeout_sec=args.page_timeout,
        include_subdomains=not args.same_host_only,
        enter_gate=not args.no_gate,
        use_sitemap=not args.no_sitemap,
        sitemap_urls=args.sitemap,
        respect_robots=not args.ignore_robots,
        headless=not args.show_browser,
        browser_executable=args.browser,
        screenshot_dir=str(output_dir() / "screenshots") if args.screenshots else "",
        cloaking_check=args.cloaking,
    )
    try:
        result = Crawler(config).run()
    except (ValueError, RuntimeError) as e:
        print(f"오류: {e}", file=sys.stderr)
        return None

    path = save_json(result, args.out)
    elements = [e for page in result["pages"] for e in page["elements"]]
    count = lambda t: sum(1 for e in elements if e["type"] == t)
    print(f"\n방문 페이지: {len(result['pages'])}개")
    print(f"텍스트 {count('text')} / 링크 {count('link')} / iframe {count('iframe')} / 숨김 요소 {count('hidden')}")
    print(f"크롤링 결과 저장: {path}")
    return result


def print_report(report: dict) -> None:
    s = report["summary"]
    for note in report["meta"].get("notes") or []:
        print(f"\n[안내] {note}")
    print(f"\n탐지 결과: {s['findings']}건 (불법광고 의심 {s['high']}건, 검토 필요 {s['suspect']}건)")
    for f in report["findings"][:30]:
        print(f"  [{f['level_label']}] {f['pattern_label']} · {f['category']} {f['score']}점 | {f['content'][:60]}")
        if f["pattern"] == "reflection_surface":
            print(f"      안내: {f['advice']}")
        if f["reflected_params"]:
            print(f"      반사된 파라미터: {', '.join(p['name'] + '=' + p['value'] for p in f['reflected_params'])}")
        title = f" | 글: {f['post_title']}" if f.get("post_title") else ""
        print(f"      위치: {f['location_label']}{title} | {' > '.join(f['frame_path'] + [f['selector']])}")
        print(f"      근거: {', '.join(e['label'] for e in f['evidence'])}")
    unknown = [d["host"] for d in report["external_domains"] if not d["whitelisted"]]
    if unknown:
        print(f"\n화이트리스트에 없는 외부 도메인 {len(unknown)}개: {', '.join(unknown[:20])}")


def main(argv=None) -> int:
    if argv is None and len(sys.argv) == 1:
        from ad_sentinel.gui import run_gui

        run_gui()
        return 0
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    args = parse_args(argv)

    if args.from_json:
        crawl_result = load_json(args.from_json)
    else:
        crawl_result = crawl(args)
        if crawl_result is None:
            return 1

    report = detect(crawl_result, DetectConfig(extra_whitelist=args.whitelist))
    path = save_json(report, args.report, prefix="detect")
    print_report(report)
    print(f"탐지 결과 저장: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
