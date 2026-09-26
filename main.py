import argparse
import logging
import sys

from ad_sentinel.config import CrawlConfig
from ad_sentinel.crawler import Crawler
from ad_sentinel.storage import save_json


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="AD-Sentinel", description="공공 웹사이트 불법광고 탐지 도구 - 크롤러")
    p.add_argument("url", help="탐색을 시작할 URL")
    p.add_argument("--max-pages", type=int, default=30, help="최대 방문 페이지 수 (기본 30)")
    p.add_argument("--depth", type=int, default=3, help="링크를 따라갈 최대 깊이 (기본 3)")
    p.add_argument("--delay", type=float, default=0.5, help="페이지 사이 대기 시간(초) (기본 0.5)")
    p.add_argument("--out", default=None, help="결과 JSON 경로 (기본: output/crawl_날짜_시간.json)")
    p.add_argument("--same-host-only", action="store_true", help="하위 도메인은 탐색하지 않음")
    p.add_argument("--ignore-robots", action="store_true", help="robots.txt 제한을 무시 (자기 기관 사이트 점검 시)")
    p.add_argument("--show-browser", action="store_true", help="브라우저 창을 띄워서 실행")
    p.add_argument("--browser", default="", help="브라우저 실행 파일 경로 (기본: 자동 탐색)")
    return p.parse_args(argv)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    args = parse_args(argv)

    config = CrawlConfig(
        start_url=args.url,
        max_pages=args.max_pages,
        max_depth=args.depth,
        delay_sec=args.delay,
        include_subdomains=not args.same_host_only,
        respect_robots=not args.ignore_robots,
        headless=not args.show_browser,
        browser_executable=args.browser,
    )

    try:
        result = Crawler(config).run()
    except (ValueError, RuntimeError) as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1

    path = save_json(result, args.out)

    elements = [e for page in result["pages"] for e in page["elements"]]
    count = lambda t: sum(1 for e in elements if e["type"] == t)
    print(f"\n방문 페이지: {len(result['pages'])}개")
    print(f"텍스트 {count('text')} / 링크 {count('link')} / iframe {count('iframe')} / 숨김 요소 {count('hidden')}")
    print(f"결과 저장: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
